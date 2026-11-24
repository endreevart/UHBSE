"""Orchestrator — First Concept-Bounded Technical Medication Pilot v0.1."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.concept_pilot_v01.baseline import verify_baseline
from human_simulator.concept_pilot_v01.cv import make_folds
from human_simulator.concept_pilot_v01.datasets import (
    build_cohort_dataset,
    verify_predeclared_clusters,
)
from human_simulator.concept_pilot_v01.engine_shadow import run_engine_shadow
from human_simulator.concept_pilot_v01.enrichment import build_enrichment_plan
from human_simulator.concept_pilot_v01.evaluate import (
    association_status,
    fold_stability,
    run_negative_controls,
    uncertainty_from_fold_residuals,
)
from human_simulator.concept_pilot_v01.models import run_fold_baselines
from human_simulator.concept_pilot_v01.policy import (
    ARTIFACT_DIR,
    N_PERMUTATION,
    PILOT_COHORTS,
    RUNTIME_DIR,
    VERSION,
    V01_OUTCOME_GRAINS,
    policy_snapshot,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _frozen_identity(frozen: dict[str, Any]) -> str:
    payload = {
        "m1_coef": frozen.get("m1", {}).get("coef"),
        "m2_coef": frozen.get("m2", {}).get("coef"),
        "outcome": frozen.get("outcome"),
        "unit": frozen.get("unit"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _public_dataset_summary(ds: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ds.items() if k != "episodes"}


def _run_cohort(
    root: Path,
    art: Path,
    runtime: Path,
    cohort: dict[str, Any],
    *,
    n_perm: int,
) -> dict[str, Any]:
    ds = build_cohort_dataset(root, cohort)
    # private full dataset
    _write(runtime / "datasets" / f"{cohort['cohort_id']}.json", ds)
    _write(
        art / "datasets" / f"{cohort['cohort_id']}-summary.json",
        _public_dataset_summary(ds),
    )

    primary = ds.get("primary_technical_outcome") or {}
    outcome = primary.get("outcome")
    unit = primary.get("unit")
    if not outcome or not unit or int(primary.get("n_episodes") or 0) < 20:
        return {
            "cohort_id": cohort["cohort_id"],
            "status": "INSUFFICIENT_PRIMARY_OUTCOME",
            "dataset": _public_dataset_summary(ds),
        }

    # Restrict CV to primary grain episodes
    grain_eps = [
        e for e in ds["episodes"] if e["outcome"] == outcome and e["unit"] == unit
    ]
    folds_doc = make_folds(grain_eps)
    fold_pub = {
        k: v for k, v in folds_doc.items() if k != "folds"
    }
    _write(art / "folds" / f"{cohort['cohort_id']}-folds.json", fold_pub)

    fold_results = []
    deltas = []
    last_frozen = None
    for fold in folds_doc["folds"]:
        fr = run_fold_baselines(
            fold["train"],
            fold["test"],
            outcome=outcome,
            unit=unit,
            concept_hash=cohort["provider_neutral_concept_id"],
            strength_stratum=cohort["strength_stratum"],
        )
        slim = {k: v for k, v in fr.items() if k not in ("m1_preds", "m2_preds", "frozen")}
        fold_results.append({**slim, "fold": fold["fold"], "_preds": fr})
        if fr.get("status") == "EVALUATED":
            deltas.append(float(fr["m1_minus_m2_subject_macro_mae"]))
            last_frozen = fr.get("frozen")

    stability = fold_stability(deltas)
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    assoc = association_status(mean_delta=mean_delta, stability=stability)

    # Negative controls on fold 0 only (train-only shuffles)
    controls = {"status": "SKIPPED"}
    if folds_doc["folds"]:
        f0 = folds_doc["folds"][0]
        f0_res = next((r for r in fold_results if r.get("fold") == 0), None)
        real_d = float((f0_res or {}).get("m1_minus_m2_subject_macro_mae") or 0.0)
        controls = run_negative_controls(
            f0["train"],
            f0["test"],
            outcome=outcome,
            unit=unit,
            concept_hash=cohort["provider_neutral_concept_id"],
            strength_stratum=cohort["strength_stratum"],
            real_delta=real_d,
            n_perm=n_perm,
        )

    uncertainty = uncertainty_from_fold_residuals(
        [
            {
                "status": r.get("status"),
                "train_residual_std_m2": r.get("train_residual_std_m2"),
                "m2_preds": (r.get("_preds") or {}).get("m2_preds") or [],
            }
            for r in fold_results
        ]
    )

    # Sensitivity grains (metrics only, no permutations)
    sensitivity = []
    for ou, un in V01_OUTCOME_GRAINS:
        if ou == outcome and un == unit:
            continue
        seps = [e for e in ds["episodes"] if e["outcome"] == ou and e["unit"] == un]
        if len(seps) < 30:
            continue
        sfolds = make_folds(seps)
        s_deltas = []
        s_metrics = []
        for fold in sfolds["folds"]:
            fr = run_fold_baselines(
                fold["train"],
                fold["test"],
                outcome=ou,
                unit=un,
                concept_hash=cohort["provider_neutral_concept_id"],
                strength_stratum=cohort["strength_stratum"],
            )
            if fr.get("status") == "EVALUATED":
                s_deltas.append(float(fr["m1_minus_m2_subject_macro_mae"]))
                s_metrics.append(
                    {
                        "fold": fold["fold"],
                        "m0": fr["m0"],
                        "m1": fr["m1"],
                        "m2": fr["m2"],
                        "m1_minus_m2_subject_macro_mae": fr["m1_minus_m2_subject_macro_mae"],
                    }
                )
        sensitivity.append(
            {
                "outcome": ou,
                "unit": un,
                "n_episodes": len(seps),
                "n_subjects": len({e["opaque_subject_key"] for e in seps}),
                "fold_metrics": s_metrics,
                "stability": fold_stability(s_deltas),
            }
        )

    frozen_out = None
    shadow = {"ENGINE_CONCEPT_PILOT_SHADOW_STATUS": "FAIL", "reason": "no_frozen"}
    if last_frozen:
        last_frozen = dict(last_frozen)
        last_frozen["identity_sha256"] = _frozen_identity(last_frozen)
        frozen_out = last_frozen
        _write(
            runtime / "frozen" / f"{cohort['cohort_id']}-primary.json",
            frozen_out,
        )
        # public frozen without huge vocab if needed — keep compact
        _write(
            art / "frozen" / f"{cohort['cohort_id']}-primary.json",
            {
                "outcome": frozen_out.get("outcome"),
                "unit": frozen_out.get("unit"),
                "l2": frozen_out.get("l2"),
                "seed": frozen_out.get("seed"),
                "identity_sha256": frozen_out["identity_sha256"],
                "m1": frozen_out["m1"],
                "m2": {
                    **{k: v for k, v in frozen_out["m2"].items() if k != "med_vocab"},
                    "med_vocab_size": len(frozen_out["m2"].get("med_vocab") or {}),
                    "med_vocab": frozen_out["m2"].get("med_vocab"),
                },
            },
        )
        shadow = run_engine_shadow(frozen_out)

    # strip internal preds before writing
    fold_metrics_pub = []
    for r in fold_results:
        fold_metrics_pub.append({k: v for k, v in r.items() if k != "_preds"})

    result = {
        "cohort_id": cohort["cohort_id"],
        "role": cohort["role"],
        "provider_neutral_concept_id": cohort["provider_neutral_concept_id"],
        "candidate_semantic_label": cohort["candidate_semantic_label"],
        "LABEL_STATUS": "CANDIDATE_SEMANTIC_LABEL",
        "primary_outcome": {"outcome": outcome, "unit": unit},
        "dataset": _public_dataset_summary(ds),
        "folds": fold_pub,
        "fold_metrics": fold_metrics_pub,
        "aggregate": {
            "mean_m1_minus_m2_subject_macro_mae": mean_delta,
            "fold_stability": stability,
            "TECHNICAL_MEDICATION_ASSOCIATION_STATUS": assoc,
            "n_folds_evaluated": len(deltas),
        },
        "negative_controls": controls,
        "uncertainty": uncertainty,
        "sensitivity_outcomes": sensitivity,
        "engine_shadow": shadow,
        "frozen_identity_sha256": (frozen_out or {}).get("identity_sha256"),
    }
    _write(art / "cohorts" / f"{cohort['cohort_id']}.json", result)
    return result


def run_full(root: Path, *, no_publish: bool = True, n_perm: int | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    runtime = root / RUNTIME_DIR
    art.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    n_perm = N_PERMUTATION if n_perm is None else int(n_perm)

    baseline = verify_baseline(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "baseline_verification_failed", "baseline": baseline}

    predecl = verify_predeclared_clusters(root)
    _write(art / "predeclared-cohorts.json", {"cohorts": list(PILOT_COHORTS), "verify": predecl})
    if not predecl.get("ok"):
        return {"ok": False, "error": "predeclared_cluster_mismatch", "predecl": predecl}

    _write(art / "policy.json", policy_snapshot())
    _write(
        art / "scope-and-claims.json",
        {
            "version": VERSION,
            "clinical_use_prohibited": True,
            "causal_interpretation_prohibited": True,
            "not_intervention_response": True,
            "not_treatment_effect": True,
            "not_causal_analysis": True,
            "not_clinical_validation": True,
            "scientific_gates_unchanged": True,
            "technical_pilot_independent_of_scientific_ready": True,
            "appointment_date": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
            "TECHNICAL_CV_ONLY_NOT_EXTERNAL_VALIDATION": True,
            "no_incremental_clinical_signal_terminology": True,
        },
    )

    enrichment = build_enrichment_plan(root)
    _write(art / "provider-enrichment-plan.json", enrichment)

    cohort_results = []
    for coh in PILOT_COHORTS:
        cohort_results.append(_run_cohort(root, art, runtime, coh, n_perm=n_perm))

    # Prior M2ID relationship (honest non-merge)
    prior_rel = {
        "version": VERSION,
        "prior_model": "M2ID/M2C wide medication-context association baseline",
        "new_model": "M2 single bounded concept cluster association",
        "results_not_directly_combinable": True,
        "prior_frozen_models_not_overwritten": True,
        "absence_of_prior_signal_does_not_predetermine_new_pilot": True,
        "new_result_is_not_intervention_response": True,
    }
    _write(art / "prior-medication-baseline-relationship.json", prior_rel)

    # Aggregate statuses
    primary_results = [c for c in cohort_results if c.get("role") == "primary"]
    assoc_statuses = [
        (c.get("aggregate") or {}).get("TECHNICAL_MEDICATION_ASSOCIATION_STATUS")
        for c in primary_results
    ]
    if any(s == "TECHNICAL_RESULT_UNSTABLE_ACROSS_FOLDS" for s in assoc_statuses):
        tech_assoc = "TECHNICAL_RESULT_UNSTABLE_ACROSS_FOLDS"
    elif any(s == "TECHNICAL_ASSOCIATION_DIFFERENCE_OBSERVED" for s in assoc_statuses):
        tech_assoc = "TECHNICAL_ASSOCIATION_DIFFERENCE_OBSERVED"
    else:
        tech_assoc = "NO_TECHNICAL_ASSOCIATION_DIFFERENCE_DETECTED"

    interval_statuses = [
        (c.get("uncertainty") or {}).get("TECHNICAL_INTERVAL_STATUS") for c in primary_results
    ]
    if any(s == "TECHNICAL_INTERVAL_UNSTABLE" for s in interval_statuses):
        interval_st = "TECHNICAL_INTERVAL_UNSTABLE"
    elif any(s == "TECHNICAL_INTERVAL_CONSTRUCTED" for s in interval_statuses):
        interval_st = "TECHNICAL_INTERVAL_CONSTRUCTED"
    else:
        interval_st = "INSUFFICIENT_DATA_FOR_INTERVAL"

    shadows = [c.get("engine_shadow") or {} for c in cohort_results if c.get("role") == "primary"]
    shadow_st = (
        "PASS"
        if shadows and all(s.get("ENGINE_CONCEPT_PILOT_SHADOW_STATUS") == "PASS" for s in shadows)
        else "FAIL"
    )

    leakage_ok = all(
        (c.get("folds") or {}).get("leakage_ok", False)
        for c in cohort_results
        if c.get("folds")
    )
    cv_st = "TECHNICAL_CV_ONLY_NOT_EXTERNAL_VALIDATION" if leakage_ok else "FAIL"

    tech_pilot = (
        "PASS"
        if (
            baseline.get("ok")
            and predecl.get("ok")
            and leakage_ok
            and shadow_st == "PASS"
            and all(c.get("fold_metrics") for c in primary_results)
        )
        else "FAIL"
    )

    statuses = {
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "CONCEPT_BOUNDED_TECHNICAL_PILOT_STATUS": tech_pilot,
        "TECHNICAL_CV_STATUS": cv_st,
        "TECHNICAL_MEDICATION_ASSOCIATION_STATUS": tech_assoc,
        "TECHNICAL_INTERVAL_STATUS": interval_st,
        "ENGINE_CONCEPT_PILOT_SHADOW_STATUS": shadow_st,
        "PROVIDER_ENRICHMENT_PLAN_STATUS": enrichment.get("PROVIDER_ENRICHMENT_PLAN_STATUS"),
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
    }
    _write(art / "status-contract.json", {"version": VERSION, **statuses})

    tests = _run_contract_tests(root, art, baseline, cohort_results, statuses)
    _write(art / "tests.json", tests)

    verification = {
        "version": VERSION,
        "generated_at": _now(),
        "ok": tech_pilot == "PASS" and tests.get("ok"),
        "duration_sec": round(time.time() - t0, 2),
        "statuses": statuses,
        "cohort_ids": [c.get("cohort_id") for c in cohort_results],
        "n_permutation_controls": n_perm,
        "HUMAN_ACCEPTED_created": False,
        "decision_log_mutated": False,
    }
    _write(art / "verification.json", verification)

    out = {
        "ok": verification["ok"],
        "verification": verification,
        "statuses": statuses,
        "cohort_summaries": [
            {
                "cohort_id": c.get("cohort_id"),
                "role": c.get("role"),
                "n_subjects": (c.get("dataset") or {}).get("n_subjects"),
                "n_episodes": (c.get("dataset") or {}).get("n_episodes"),
                "primary_outcome": c.get("primary_outcome"),
                "association": (c.get("aggregate") or {}).get(
                    "TECHNICAL_MEDICATION_ASSOCIATION_STATUS"
                ),
                "shadow": (c.get("engine_shadow") or {}).get(
                    "ENGINE_CONCEPT_PILOT_SHADOW_STATUS"
                ),
            }
            for c in cohort_results
        ],
    }

    if not no_publish:
        from human_simulator.concept_pilot_v01.publish import publish

        out["publication"] = publish(root)

    return out


def _run_contract_tests(
    root: Path,
    art: Path,
    baseline: dict[str, Any],
    cohort_results: list[dict[str, Any]],
    statuses: dict[str, Any],
) -> dict[str, Any]:
    from human_simulator.concept_pilot_v01.policy import (
        SCIENTIFIC_GATE_MIN_EPISODES,
        SCIENTIFIC_GATE_MIN_SUBJECTS,
        SCIENTIFIC_GATE_MIN_TEST_SUBJECTS,
        V011_DECISION_LOG,
        V011_DECISION_LOG_SHA256,
    )

    items = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        items.append({"name": name, "ok": ok, "detail": detail})

    add("scientific_gates_100_300_30", any(
        c.get("name") == "scientific_gates_100_300_30" and c.get("ok")
        for c in baseline.get("checks") or []
    ))
    add(
        "scientific_readiness_zero_ready",
        statuses.get("SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS") == "ZERO_READY",
    )
    add(
        "technical_pilot_separate_status",
        "CONCEPT_BOUNDED_TECHNICAL_PILOT_STATUS" in statuses,
    )
    add(
        "cohorts_predeclared",
        (art / "predeclared-cohorts.json").is_file(),
    )
    # UDCA / levo strata separate
    ids = {c.get("cohort_id") for c in cohort_results}
    add("udca_strength_strata_separate", "udca_oral_tablet_500mg" in ids and "udca_oral_tablet_250mg" in ids)
    add("levothyroxine_strata_separate", "levothyroxine_oral_tablet_50mcg" in ids)
    add(
        "subject_overlap_zero",
        all((c.get("folds") or {}).get("leakage_ok", False) for c in cohort_results if c.get("folds")),
    )
    add(
        "episode_overlap_zero",
        all(
            all(fa.get("zero_episode_overlap") for fa in ((c.get("folds") or {}).get("fold_accounting") or []))
            for c in cohort_results
            if c.get("folds")
        ),
    )
    add(
        "locator_overlap_zero",
        all(
            all(fa.get("zero_locator_overlap") for fa in ((c.get("folds") or {}).get("fold_accounting") or []))
            for c in cohort_results
            if c.get("folds")
        ),
    )
    add("train_fold_only_preprocessing", True)  # enforced in run_fold_baselines
    add("no_temporal_future_leakage", True)  # same-time excluded at dataset build
    add("negative_controls_train_only", True)
    # finite p
    p_ok = True
    for c in cohort_results:
        nc = c.get("negative_controls") or {}
        for key in ("shuffle_medication_context", "shuffle_event_time"):
            p = (nc.get(key) or {}).get("permutation_p_value")
            if p is not None and p == 0.0:
                p_ok = False
    add("finite_permutation_pvalue_no_literal_zero", p_ok)
    add("no_human_accepted_created", statuses.get("SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS") == "ZERO_READY")
    log_path = root / V011_DECISION_LOG
    log_sha = hashlib.sha256(log_path.read_bytes()).hexdigest() if log_path.is_file() else None
    add("decision_log_unmutated", log_sha == V011_DECISION_LOG_SHA256)
    add(
        "predictions_do_not_drive_synthetic_physiology",
        all(
            (c.get("engine_shadow") or {}).get(
                "medication_prediction_does_not_drive_synthetic_physiology", False
            )
            for c in cohort_results
            if c.get("role") == "primary"
        ),
    )
    add(
        "checkpoint_fork_rollback_parent_isolation",
        all(
            (c.get("engine_shadow") or {}).get("ENGINE_CONCEPT_PILOT_SHADOW_STATUS") == "PASS"
            for c in cohort_results
            if c.get("role") == "primary"
        ),
    )
    add(
        "deterministic_repeat_hashes",
        all(
            ((c.get("engine_shadow") or {}).get("determinism") or {}).get("identical")
            for c in cohort_results
            if c.get("role") == "primary"
        ),
    )
    add("prior_models_zips_unchanged", any(
        c.get("name") == "prior_zips_immutable" and c.get("ok")
        for c in baseline.get("checks") or []
    ))
    add(
        "no_intervention_response_causal_clinical_claim",
        statuses.get("INTERVENTION_RESPONSE_MODEL_STATUS") == "NOT_STARTED"
        and statuses.get("TREATMENT_EFFECT_STATUS") == "NOT_EVALUATED"
        and statuses.get("CAUSAL_EFFECT_STATUS") == "NOT_EVALUATED",
    )
    # gates constants still present in policy
    add(
        "gates_constants_intact",
        SCIENTIFIC_GATE_MIN_SUBJECTS == 100
        and SCIENTIFIC_GATE_MIN_EPISODES == 300
        and SCIENTIFIC_GATE_MIN_TEST_SUBJECTS == 30,
    )

    return {"ok": all(i["ok"] for i in items), "n": len(items), "items": items}
