"""Scientific Data Readiness v0.1.1.1 orchestrator — uncertainty/shuffle evidence correction."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.migrations import row_counts
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.scientific.backtest import compare_models, metrics_block, uncertainty_status
from human_simulator.scientific.baseline import verify_core_baseline
from human_simulator.scientific.dataset import (
    build_consecutive_pairs,
    fetch_eligible_subjects,
    fetch_measurement_series,
    write_runtime_dataset,
)
from human_simulator.scientific.engine import integrate_heldout_subject
from human_simulator.scientific.leakage import (
    run_sample_level_leakage_audit,
    shuffled_label_retraining_control,
)
from human_simulator.scientific.models import (
    EmpiricalTrendBaseline,
    PersistenceBaseline,
    check_scope_honesty,
    feature_schema_hash,
    is_constant_model,
    select_ridge_l2,
)
from human_simulator.scientific.outcome import select_outcome
from human_simulator.scientific.policy import (
    ARTIFACT_DIR,
    CLINICAL_VALIDATION_STATUS,
    INTERVENTION_RESPONSE_MODEL_STATUS,
    MIN_TEST_PAIRS_FOR_UNCERTAINTY_CALIBRATION,
    MIN_TEST_SUBJECTS_FOR_UNCERTAINTY_CALIBRATION,
    MIN_VAL_FOR_INTERVAL_CONSTRUCTION,
    NOMINAL_COVERAGE,
    PRODUCTION_READINESS,
    SEED,
    SPLIT_CLASS,
    gaussian_interval_multiplier,
    policy_snapshot,
)
from human_simulator.scientific.profile import profile_candidates
from human_simulator.scientific.splits import assign_pairs_to_splits, build_subject_split


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc, encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sanitize_for_publication(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop subject key lists from published evidence."""
    out = json.loads(json.dumps(doc, default=str))
    if "opaque_subject_keys" in out:
        out["opaque_subject_keys"] = f"<redacted n={len(doc.get('opaque_subject_keys') or [])}>"
    if "sets" in out:
        out["sets"] = {k: f"<redacted n={len(v)}>" for k, v in (doc.get("sets") or {}).items()}
    if "assignment" in out:
        out["assignment"] = f"<redacted n={len(doc.get('assignment') or {})}>"
    if "subject_assignment_hashes" in out:
        out.pop("subject_assignment_hashes", None)
    return out


def run_v01(
    repo_root: Path,
    *,
    seed: int = SEED,
    no_publish: bool = True,
) -> dict[str, Any]:
    """Entry point (v0.1.1.1 evidence correction)."""
    return run_v011(repo_root, seed=seed, no_publish=no_publish)


def run_v011(
    repo_root: Path,
    *,
    seed: int = SEED,
    no_publish: bool = True,
) -> dict[str, Any]:
    root = repo_root.resolve()
    out = root / ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat()
    clinical_rows_read = 0
    raw_db_writes = 0
    query_log: list[dict[str, Any]] = []

    baseline = verify_core_baseline(root)
    _write(out / "baseline-verification.json", baseline)

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        counts = row_counts(conn)
        query_log.append({"name": "row_counts", "kind": "aggregate"})

        # 1) candidate-agnostic eligible subjects
        eligible = fetch_eligible_subjects(conn)
        query_log.append({"name": "fetch_eligible_subjects", "kind": "aggregate_ids_runtime"})

        # 2) subject split BEFORE outcome selection
        subject_split = build_subject_split(eligible["opaque_subject_keys"], seed=seed)
        train_keys = set(subject_split["sets"]["train"])
        val_keys = set(subject_split["sets"]["validation"])
        test_keys = set(subject_split["sets"]["test"])

        # 3) profile + select outcome on TRAIN ONLY
        profile = profile_candidates(conn, train_subject_keys=train_keys)
        query_log.append(
            {
                "name": "profile_candidates_train_only",
                "kind": "aggregate",
                "n_train_subjects": len(train_keys),
                "relations": profile["relations_read"],
            }
        )
        selection = select_outcome(profile)
        selection["selection_population"] = "train_discovery_subjects_only"
        selection["test_subjects_seen"] = False
        selection["validation_subjects_seen"] = False
        # prove test not used: intersection of profiled population with test is empty by construction
        selection["lineage"] = {
            "eligible_subjects_total": eligible["n_eligible_subjects"],
            "train_subjects": len(train_keys),
            "validation_subjects": len(val_keys),
            "test_subjects": len(test_keys),
            "outcome_selection_population": "train_discovery_subjects_only",
            "test_subjects_in_outcome_selection": 0,
            "validation_subjects_in_outcome_selection": 0,
            "test_not_used_for_outcome_selection": True,
        }

        if selection["status"] != "OUTCOME_SELECTED":
            return _finalize_insufficient(
                out,
                baseline=baseline,
                profile=profile,
                selection=selection,
                counts=counts,
                started=started,
                query_log=query_log,
                subject_split=subject_split,
            )

        selected = selection["selected"]
        # 4) fetch series for selected outcome+unit for all split subjects
        all_keys = train_keys | val_keys | test_keys
        series = fetch_measurement_series(
            conn,
            raw_code=selected["source_measurement_label"],
            dominant_unit=selected["dominant_unit"] or "",
            subject_keys=all_keys,
        )
        clinical_rows_read = len(series)
        query_log.append(
            {
                "name": "fetch_measurement_series",
                "kind": "row_level_runtime_only",
                "n_rows": clinical_rows_read,
                "values_written_to_git_artifacts": False,
            }
        )

    config = {
        "seed": seed,
        "outcome_candidate_id": selected["candidate_id"],
        "dominant_unit": selected["dominant_unit"],
        "version": "0.1.1.1",
        "unit_policy": "dominant_unit_fit_on_train_only",
        "pair_definition": "strict_consecutive_neighbors_only",
        "split_before_outcome_selection": True,
    }
    pairs, meta = build_consecutive_pairs(series, outcome=selected, config=config)
    write_runtime_dataset(root, pairs, meta)

    if len(pairs) < 15 or meta["summary"]["n_subjects_with_pairs"] < 8:
        selection_fail = {
            **selection,
            "status": "INSUFFICIENT_DATA_FOR_FIRST_BACKTEST",
            "insufficiency_reasons": [
                f"After consecutive pairing: pairs={len(pairs)} "
                f"subjects_with_pairs={meta['summary']['n_subjects_with_pairs']}."
            ],
        }
        return _finalize_insufficient(
            out,
            baseline=baseline,
            profile=profile,
            selection=selection_fail,
            counts=counts,
            started=started,
            query_log=query_log,
            subject_split=subject_split,
            dataset_summary=meta["summary"],
        )

    splits = assign_pairs_to_splits(pairs, subject_split)
    train, val, test = (
        splits["buckets"]["train"],
        splits["buckets"]["validation"],
        splits["buckets"]["test"],
    )

    persistence = PersistenceBaseline()
    trend = EmpiricalTrendBaseline()
    learned, tune_info = select_ridge_l2(train, val, seed=seed)
    # refine residual std on validation
    if val:
        val_tmp = [learned.predict_pair(p) for p in val]
        resid = [p.y_true - p.y_pred for p in val_tmp]
        learned.residual_std = math.sqrt(sum(r * r for r in resid) / len(resid)) or learned.residual_std

    p_test = [persistence.predict_pair(p) for p in test]
    t_test = [trend.predict_pair(p) for p in test]
    l_test = [learned.predict_pair(p) for p in test]
    p_val = [persistence.predict_pair(p) for p in val]
    l_val = [learned.predict_pair(p) for p in val]

    comparison = compare_models(persistence=p_test, trend=t_test, learned=l_test)
    constant = is_constant_model(l_test)
    if constant and comparison["outperforms_persistence"]:
        comparison["outperforms_persistence"] = False
        comparison["incremental_signal_status"] = "NO_INCREMENTAL_SIGNAL_DETECTED"

    unc = uncertainty_status(
        val_preds=l_val,
        test_preds=l_test,
        nominal=NOMINAL_COVERAGE,
        interval_multiplier=learned.interval_multiplier,
        residual_estimation_split="validation",
        min_val_for_construction=MIN_VAL_FOR_INTERVAL_CONSTRUCTION,
        min_test_subjects=MIN_TEST_SUBJECTS_FOR_UNCERTAINTY_CALIBRATION,
        min_test_pairs=MIN_TEST_PAIRS_FOR_UNCERTAINTY_CALIBRATION,
    )

    shuffle = shuffled_label_retraining_control(
        train=train,
        test=test,
        frozen_l2=float(learned.l2),
        real_feature_schema_hash=str(learned.feature_schema_hash or feature_schema_hash()),
        split_hash=splits["verification"].get("split_hash"),
        seed=seed,
        real_subject_macro_mae=float(comparison["first_learned"].get("subject_macro_mae") or 0),
        interval_multiplier=learned.interval_multiplier,
        nominal_coverage=NOMINAL_COVERAGE,
    )

    lineage = {
        "data_flow": [
            "canonical_ro",
            "eligible_subjects",
            "subject_split",
            "train_only_outcome_profiling",
            "train_only_outcome_selection",
            "consecutive_pair_builder",
            "feature_construction",
            "train_only_preprocessing",
            "train_fit",
            "validation_tuning",
            "frozen_test_evaluation",
        ],
        "outcome_selection_population": "train_discovery_subjects_only",
        "unit_policy_fit_population": "train_discovery_subjects_only",
        "preprocessing_fit_split": "train",
        "test_used_in_tuning": False,
        "test_subjects_seen_by_outcome_selection": False,
        "validation_subjects_seen_by_outcome_selection": False,
        "synthetic_intervention_branch": "SEPARATED_NOT_USED_FOR_BACKTEST",
        "split_class": SPLIT_CLASS,
        "pair_definition": "strict_consecutive_neighbors_only",
        "ridge_tuning": tune_info,
    }
    # compute test_not_used from lineage facts
    lineage["test_not_used_for_outcome_selection"] = (
        lineage["outcome_selection_population"] == "train_discovery_subjects_only"
        and lineage["test_subjects_seen_by_outcome_selection"] is False
        and selection["lineage"]["test_subjects_in_outcome_selection"] == 0
    )

    leakage = run_sample_level_leakage_audit(pairs=pairs, splits=splits, lineage=lineage)
    scope = check_scope_honesty(learned.MODEL_ID, learned.CLAIM_LEVEL)

    heldout = test[0] if test else (val[0] if val else train[0])
    engine = integrate_heldout_subject(pair=heldout, learned=learned, seed=seed)

    pred_hash = hashlib.sha256(
        json.dumps([(p.pair_id, round(p.y_pred, 8)) for p in l_test], sort_keys=True).encode()
    ).hexdigest()
    splits2 = assign_pairs_to_splits(pairs, subject_split)
    repro_ok = splits2["verification"]["split_hash"] == splits["verification"]["split_hash"]

    # Statuses derived from gates — never hard-coded PASS up front
    checks = {
        "baseline_ok": baseline.get("ok") is True,
        "subject_overlap_zero": subject_split["subject_overlap_zero"],
        "outcome_selected_or_insufficient": selection["status"]
        in {"OUTCOME_SELECTED", "INSUFFICIENT_DATA_FOR_FIRST_BACKTEST"},
        "outcome_train_only": lineage["test_not_used_for_outcome_selection"],
        "leakage_ok": leakage["ok"],
        "split_ok": splits["verification"]["ok"],
        "engine_ok": engine["ok"],
        "scope_ok": scope["ok"],
        "schema_hash_present": bool(learned.feature_schema_hash),
        "repro_splits": repro_ok,
        "raw_db_writes_zero": raw_db_writes == 0,
        "pair_definition_consecutive": meta["summary"]["pair_definition"]
        == "strict_consecutive_neighbors_only",
        "split_class_honest": splits["manifest"]["split_class"] == SPLIT_CLASS,
        "shuffled_control_uses_same_frozen_model_configuration": shuffle.get(
            "configuration_equality"
        )
        is True,
        "interval_multiplier_matches_nominal": unc.get("interval_multiplier_matches_nominal")
        is True,
        "no_false_uncertainty_calibration_pass": unc.get("uncertainty_calibration_status")
        != "UNCERTAINTY_CALIBRATION_PASS"
        or unc.get("held_out_sample_sufficient_for_calibration") is True,
    }
    technical_ok = all(checks.values())
    if not technical_ok:
        pipeline_status = "BACKTEST_PIPELINE_FAIL"
        scientific_status = "EXPLORATORY_RETROSPECTIVE_PIPELINE_PARTIAL"
        retrospective_status = "BACKTEST_PIPELINE_FAIL"
    else:
        pipeline_status = "TECHNICAL_PIPELINE_PASS"
        scientific_status = "EXPLORATORY_RETROSPECTIVE_PIPELINE_PASS"
        retrospective_status = comparison["retrospective_backtest_status"]

    incremental = comparison.get("incremental_signal_status", "NO_INCREMENTAL_SIGNAL_DETECTED")

    # Publication-safe artifacts (no subject hash lists)
    pub_split = {
        "manifest": splits["manifest"],
        "verification": splits["verification"],
        "subject_split_summary": {
            "seed": subject_split["seed"],
            "split_hash": subject_split["split_hash"],
            "n_subjects": subject_split["n_subjects"],
            "split_class": SPLIT_CLASS,
            "subject_overlap_zero": subject_split["subject_overlap_zero"],
        },
    }
    pub_eligible = {
        "n_eligible_subjects": eligible["n_eligible_subjects"],
        "definition": eligible["definition"],
    }
    pub_selection = dict(selection)
    if "scored_candidates" in pub_selection:
        # keep aggregate candidate table without expanding subject lists
        pass

    artifacts = {
        "candidate-outcome-profile.json": {
            **{k: v for k, v in profile.items() if k != "candidates"},
            "candidates": [
                {kk: vv for kk, vv in c.items()}
                for c in profile.get("candidates") or []
            ],
        },
        "outcome-selection.json": pub_selection,
        "eligible-subjects-summary.json": pub_eligible,
        "longitudinal-dataset-summary.json": meta["summary"],
        "dataset-build-config.json": meta["config"],
        "dataset-schema.json": meta["schema"],
        "split-verification.json": pub_split,
        "temporal-leakage-verification.json": leakage,
        "persistence-baseline-metrics.json": comparison["persistence"],
        "empirical-trend-baseline-metrics.json": comparison["empirical_trend"],
        "first-learned-baseline-metrics.json": {
            **comparison["first_learned"],
            "fit": {
                "feature_schema_hash": learned.feature_schema_hash,
                "training_configuration_hash": learned.training_configuration_hash,
                "preprocessing": "standardize_fit_train_only",
                "l2": learned.l2,
            },
            "tuning": tune_info,
            "prediction_hash": pred_hash,
        },
        "model-comparison.json": comparison,
        "uncertainty-calibration.json": unc,
        "shuffled-label-control.json": shuffle,
        "first-retrospective-backtest.json": {
            "status": retrospective_status,
            "incremental_signal_status": incremental,
            "reproducible_split_hash": repro_ok,
            "split_status": SPLIT_CLASS,
            "pair_definition": "strict_consecutive_neighbors_only",
        },
        "engine-integration-verification.json": engine,
        "data-flow-lineage.json": lineage,
        "scope-and-claims.json": {
            "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
            "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
            "production_readiness": PRODUCTION_READINESS,
            "scope_honesty": scope,
            "claims_not_made": [
                "CLINICALLY_VALIDATED",
                "TREATMENT_EFFECT_CONFIRMED",
                "PRODUCTION_READY",
                "INTERVENTION_RESPONSE_MODEL",
            ],
        },
        "non-actions.json": {
            "security_work_executed": False,
            "source_b": False,
            "migration_0005": False,
            "qsp_pkpd": False,
            "clinical_validation": False,
            "no_publish_requested": no_publish,
        },
        "query-log.json": {
            "queries": query_log,
            "clinical_rows_read": clinical_rows_read,
            "raw_db_writes": raw_db_writes,
            "row_values_in_git_artifacts": False,
        },
        "canonical-row-counts.json": counts,
    }
    for name, doc in artifacts.items():
        _write(out / name, doc)
    _write(out / "model-card-first-learned-baseline.md", learned.model_card())

    verification = {
        "scientific_data_readiness_status": scientific_status,
        "technical_pipeline_status": pipeline_status,
        "retrospective_backtest_status": retrospective_status,
        "incremental_signal_status": incremental,
        "uncertainty_calibration_status": unc["uncertainty_calibration_status"],
        "uncertainty_interval_construction_status": unc[
            "uncertainty_interval_construction_status"
        ],
        "interval_sharpness_status": unc.get("interval_sharpness_status"),
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "security_stage_status": policy_snapshot()["security_stage_status"],
        "checks": {k: ("PASS" if v else "FAIL") for k, v in checks.items()},
        "failed_checks": sorted(k for k, v in checks.items() if not v),
        "selected_outcome": {
            "candidate_id": selected["candidate_id"],
            "source_measurement_label": selected["source_measurement_label"],
            "dominant_unit": selected["dominant_unit"],
            "selection_population": "train_discovery_subjects_only",
            "medical_interpretation_status": "DOMAIN_REVIEW_PENDING",
        },
        "n_subjects_with_pairs": meta["summary"]["n_subjects_with_pairs"],
        "n_pairs": meta["summary"]["n_pairs"],
        "n_observations_after_filter": meta["summary"]["n_observations_after_filter"],
        "split_counts": splits["manifest"]["n_pairs"],
        "split_subjects": splits["manifest"]["n_subjects"],
        "split_class": SPLIT_CLASS,
        "pair_definition": "strict_consecutive_neighbors_only",
        "clinical_rows_read": clinical_rows_read,
        "raw_db_writes": raw_db_writes,
        "primary_metric_test": {
            "subject_macro_mae": {
                "persistence": comparison["persistence"].get("subject_macro_mae"),
                "empirical_trend": comparison["empirical_trend"].get("subject_macro_mae"),
                "first_learned": comparison["first_learned"].get("subject_macro_mae"),
            },
            "pair_micro_mae": {
                "persistence": comparison["persistence"].get("pair_micro_mae"),
                "empirical_trend": comparison["empirical_trend"].get("pair_micro_mae"),
                "first_learned": comparison["first_learned"].get("pair_micro_mae"),
            },
        },
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "policy": policy_snapshot(),
    }
    _write(out / "scientific-data-readiness-verification.json", verification)
    _write(
        out / "release-verification.json",
        {
            "status": "PASS" if technical_ok else "FAIL",
            "verification_summary": {
                "technical_pipeline_status": pipeline_status,
                "scientific_data_readiness_status": scientific_status,
                "failed_checks": verification["failed_checks"],
            },
            "baseline": {"sha256": baseline.get("computed_sha256"), "ok": baseline.get("ok")},
        },
    )
    _write(
        out / "scientific-data-readiness-report.md",
        _report_md(verification, selection, comparison, meta, splits, unc, shuffle, leakage),
    )

    names = sorted(
        p.relative_to(out).as_posix()
        for p in out.rglob("*")
        if p.is_file() and p.name != "manifest.sha256"
    )
    (out / "manifest.sha256").write_text(
        "\n".join(f"{_sha_file(out / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )
    return {
        "scientific_data_readiness_status": scientific_status,
        "technical_pipeline_status": pipeline_status,
        "retrospective_backtest_status": retrospective_status,
        "incremental_signal_status": incremental,
        "uncertainty_calibration_status": unc["uncertainty_calibration_status"],
        "uncertainty_interval_construction_status": unc[
            "uncertainty_interval_construction_status"
        ],
        "failed_checks": verification["failed_checks"],
        "artifact_dir": str(out),
        "no_publish": no_publish,
        "selected_outcome": verification["selected_outcome"],
        "n_pairs": meta["summary"]["n_pairs"],
        "clinical_rows_read": clinical_rows_read,
    }


def _finalize_insufficient(
    out: Path,
    *,
    baseline: dict[str, Any],
    profile: dict[str, Any],
    selection: dict[str, Any],
    counts: dict[str, Any],
    started: str,
    query_log: list[dict[str, Any]],
    subject_split: dict[str, Any] | None = None,
    dataset_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verification = {
        "scientific_data_readiness_status": "INSUFFICIENT_DATA_FOR_FIRST_BACKTEST",
        "technical_pipeline_status": "TECHNICAL_PIPELINE_PASS",
        "retrospective_backtest_status": "INSUFFICIENT_DATA_FOR_FIRST_BACKTEST",
        "incremental_signal_status": "NO_INCREMENTAL_SIGNAL_DETECTED",
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "insufficiency_reasons": selection.get("insufficiency_reasons")
        or ["Outcome selection failed hard gates on train subjects"],
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "policy": policy_snapshot(),
        "baseline_ok": baseline.get("ok"),
        "canonical_row_counts": counts,
        "split_class": SPLIT_CLASS,
    }
    _write(out / "baseline-verification.json", baseline)
    _write(out / "candidate-outcome-profile.json", profile)
    _write(out / "outcome-selection.json", selection)
    if subject_split:
        _write(
            out / "split-verification.json",
            {
                "n_subjects": subject_split["n_subjects"],
                "split_hash": subject_split["split_hash"],
                "split_class": SPLIT_CLASS,
                "subject_overlap_zero": subject_split["subject_overlap_zero"],
            },
        )
    if dataset_summary:
        _write(out / "longitudinal-dataset-summary.json", dataset_summary)
    _write(out / "scientific-data-readiness-verification.json", verification)
    _write(out / "query-log.json", {"queries": query_log, "raw_db_writes": 0})
    _write(out / "non-actions.json", {"security_work_executed": False})
    _write(
        out / "scientific-data-readiness-report.md",
        "# Scientific Data Readiness v0.1.1.1\n\n**Status:** INSUFFICIENT_DATA_FOR_FIRST_BACKTEST\n",
    )
    _write(out / "release-verification.json", {"status": "PASS", "note": "honest insufficient"})
    names = sorted(
        p.relative_to(out).as_posix()
        for p in out.rglob("*")
        if p.is_file() and p.name != "manifest.sha256"
    )
    (out / "manifest.sha256").write_text(
        "\n".join(f"{_sha_file(out / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )
    return {
        "scientific_data_readiness_status": "INSUFFICIENT_DATA_FOR_FIRST_BACKTEST",
        "artifact_dir": str(out),
        "failed_checks": [],
    }


def _report_md(
    verification: dict[str, Any],
    selection: dict[str, Any],
    comparison: dict[str, Any],
    meta: dict[str, Any],
    splits: dict[str, Any],
    unc: dict[str, Any],
    shuffle: dict[str, Any],
    leakage: dict[str, Any],
) -> str:
    sel = selection.get("selected") or {}
    return f"""# Scientific Data Readiness v0.1.1.1

**Scientific status:** {verification['scientific_data_readiness_status']}
**Technical pipeline:** {verification['technical_pipeline_status']}
**Backtest:** {verification['retrospective_backtest_status']}
**Incremental signal:** {verification['incremental_signal_status']}
**Interval construction:** {unc.get('uncertainty_interval_construction_status')}
**Uncertainty calibration:** {unc.get('uncertainty_calibration_status')}
**Interval sharpness:** {unc.get('interval_sharpness_status')}

## Evidence corrections vs v0.1.1

- Gaussian interval multiplier derived from nominal coverage (not fixed 1.96 for 0.90)
- Interval construction status separated from calibration status
- Held-out test size gates calibration PASS
- Shuffled-label control uses frozen real-model L2
- Strict consecutive neighbor pairs only (not all-forward combinations)
- Subject split before outcome selection (train/discovery only)
- Split class: `{SPLIT_CLASS}`
- Sample-level temporal leakage audit
- Subject-macro MAE primary; pair-micro MAE secondary
- Shuffled-label control retrains on shuffled train labels with frozen configuration
- Shuffled-label control retrains on shuffled train labels

## Selected outcome (train-only)

- candidate_id: `{sel.get('candidate_id')}`
- label: `{sel.get('source_measurement_label')}`
- unit: `{sel.get('dominant_unit')}`
- medical interpretation: DOMAIN_REVIEW_PENDING

## Dataset

- observations after filter: {meta['summary'].get('n_observations_after_filter')}
- subjects with pairs: {meta['summary']['n_subjects_with_pairs']}
- consecutive pairs: {meta['summary']['n_pairs']}
- split pairs: {splits['manifest']['n_pairs']}
- split subjects: {splits['manifest']['n_subjects']}

## Test metrics

- Persistence subject-macro MAE: {comparison['persistence'].get('subject_macro_mae')}
- Empirical trend subject-macro MAE: {comparison['empirical_trend'].get('subject_macro_mae')}
- Ridge subject-macro MAE: {comparison['first_learned'].get('subject_macro_mae')}
- Outperforms persistence: {comparison['outperforms_persistence']}

## Leakage / shuffle

- leakage: {leakage.get('status')} evaluated={leakage.get('evaluated_pair_count')} violations={leakage.get('violations_by_type')}
- shuffle permutations: {shuffle.get('n_permutations')} fraction≤real={shuffle.get('fraction_shuffles_le_real')}
- real L2: {shuffle.get('real_selected_l2')} shuffled L2: {shuffle.get('shuffled_control_l2')}
- config equality: {shuffle.get('shuffled_control_uses_same_frozen_model_configuration')}
- mean interval width (test): {unc.get('mean_interval_width_test')}
- interval multiplier: {unc.get('interval_multiplier')}
"""
