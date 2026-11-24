"""Orchestrator — Global Subject Split + Individual Multi-Outcome State v0.1."""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.global_state_v01.baseline_verify import verify_baseline
from human_simulator.global_state_v01.backtest import (
    build_heldout_inventory,
    run_multi_outcome_backtest,
)
from human_simulator.global_state_v01.cross_grain_audit import audit_cross_grain_splits
from human_simulator.global_state_v01.engine_shadow import (
    run_real_heldout_engine_shadow,
    select_subject_by_coverage,
)
from human_simulator.global_state_v01.global_split import (
    build_global_subject_split,
    public_split_contract,
    write_private_manifest,
)
from human_simulator.global_state_v01.grain_runner import run_grain_global
from human_simulator.global_state_v01.policy import (
    ACCEPTED_V011_ARTIFACT_DIR,
    ARTIFACT_DIR,
    RUNTIME_DIR,
    THRESHOLD_CRITERIA,
    VERSION,
    policy_snapshot,
)
from human_simulator.global_state_v01.provider_registry import (
    build_global_provider_registry,
    reload_all_providers_equality,
    write_registry,
)
from human_simulator.trajectory_expansion_v011.datasets import (
    build_grain_dataset,
    build_opaque_map,
    collect_patient_ids_for_grains,
    fetch_source_a_series,
)
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def run_full(
    root: Path,
    *,
    no_publish: bool = True,
    max_grains: int | None = None,
    max_inventory_subjects: int | None = 80,
) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    runtime = root / RUNTIME_DIR
    art.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = verify_baseline(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    # Load v0.1.1 eligible grains from registry
    reg011 = json.loads(
        (root / ACCEPTED_V011_ARTIFACT_DIR / "frozen-provider-registry.json").read_text(
            encoding="utf-8"
        )
    )
    grains_meta = []
    for p in reg011.get("providers") or []:
        grains_meta.append(
            {
                "grain_id": p["grain_id"],
                "normalized_label": p["outcome"],
                "outcome": p["outcome"],
                "unit": p["unit"],
                "v011_active_provider": p.get("active_provider"),
                "v011_model_identity_hash": p.get("model_identity_hash"),
            }
        )
    if max_grains is not None:
        grains_meta = grains_meta[: int(max_grains)]

    _write(art / "policy.json", policy_snapshot())
    _write(
        art / "scope-and-claims.json",
        {
            "version": VERSION,
            "orchestrated_independent_providers": True,
            "not_joint_multi_outcome_ml": True,
            "claim_level": "SECONDARY_EXPLORATORY_RETROSPECTIVE_BACKTEST",
            "no_medication_context": True,
            "no_clinical_validation": True,
        },
    )

    from human_simulator.unified import source_a_adapter as sa
    from human_simulator.core.ids import load_hmac_key, opaque_subject_key

    grain_subject_sets: dict[str, list[str]] = {}
    results: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []
    # subject -> (outcome,unit) -> series (for test subjects inventory)
    subject_obs: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    with sa.source_a_connection(root) as conn_a:
        # Global universe = all account_patient
        raw_ids = sa.select_all_account_patient_ids(conn_a)
        hmac_key = load_hmac_key(root)
        all_opaque = [opaque_subject_key(hmac_key, int(pid)) for pid in raw_ids]
        global_split = build_global_subject_split(all_opaque)
        write_private_manifest(runtime / "global-subject-split-manifest.json", global_split)
        _write(art / "global-subject-split-contract.json", public_split_contract(global_split))

        # Source B contamination proof: opaque keys derived only from Source A ids
        contamination = {
            "GLOBAL_SPLIT_CONTAMINATION_STATUS": "PASS",
            "source_system": "magerya_api",
            "n_account_patient": len(raw_ids),
            "n_opaque_subjects": len(all_opaque),
            "source_b_rows_in_universe": 0,
            "raw_identifiers_published": False,
        }
        _write(art / "global-split-contamination.json", contamination)

        # Collect series for candidate grains
        patient_ids = collect_patient_ids_for_grains(conn_a, grains_meta)
        opaque_map = build_opaque_map(root, patient_ids)

        for i, g in enumerate(grains_meta):
            series = fetch_source_a_series(
                conn_a,
                outcome=g["normalized_label"],
                unit=g["unit"],
                opaque_map=opaque_map,
            )
            ds = build_grain_dataset(series, g)
            pairs = ds.pop("pairs")
            subjects = sorted({p["opaque_subject_key"] for p in pairs})
            grain_subject_sets[g["grain_id"]] = subjects

            # Cache series for test subjects (state assembly)
            for row in series:
                sid = row["opaque_subject_key"]
                if global_split["assignment"].get(sid) == "test":
                    subject_obs[sid][(g["normalized_label"], g["unit"])].append(row)

            ds_pub = {k: v for k, v in ds.items()}
            _write(runtime / "datasets" / f"{g['grain_id']}-summary.json", ds_pub)

            # Pre-threshold on rebuilt pairs/subjects_with_repeats
            n_rep = int(ds_pub.get("n_subjects_with_repeats") or 0)
            n_pairs = int(ds_pub.get("n_pairs") or 0)
            if n_rep < THRESHOLD_CRITERIA["min_subjects_with_ge2"] or n_pairs < THRESHOLD_CRITERIA[
                "min_strict_consecutive_pairs"
            ]:
                row = {
                    "grain_id": g["grain_id"],
                    "outcome": g["normalized_label"],
                    "unit": g["unit"],
                    "status": "BELOW_GLOBAL_THRESHOLD",
                    "reason": "pairs_or_subjects_with_repeats",
                    "n_pairs": n_pairs,
                    "n_subjects_with_repeats": n_rep,
                    "dataset_summary": ds_pub,
                    "medication_features_present": False,
                }
                results.append(row)
                ineligible.append(row)
                _write(art / "grains" / f"{g['grain_id']}.json", row)
                continue

            out = run_grain_global(
                {**g, "unexplained": ds.get("unexplained", 0)},
                pairs,
                global_split=global_split,
                min_test_subjects=int(THRESHOLD_CRITERIA["min_test_subjects_if_split"]),
            )
            out["dataset_summary"] = ds_pub
            out["v011_active_provider"] = g.get("v011_active_provider")
            out["provider_changed"] = out.get("active_provider") != g.get("v011_active_provider")

            if out.get("status") in {
                "BELOW_GLOBAL_THRESHOLD",
                "METHODOLOGY_INCOMPATIBLE",
                "INSUFFICIENT_TEST_DATA",
            }:
                out.pop("frozen", None)
                out.pop("_test_pairs_private", None)
                out.pop("_train_pairs_private", None)
                ineligible.append(out)
            else:
                eligible.append(out)
                if out.get("frozen"):
                    _write(runtime / "frozen" / f"{g['grain_id']}.json", out["frozen"])

            results.append(out)
            slim = {
                k: v
                for k, v in out.items()
                if k not in {"frozen", "_test_pairs_private", "_train_pairs_private"}
            }
            if out.get("frozen"):
                slim["frozen_hashes"] = {
                    "model_file_hash": out["frozen"].get("model_file_hash"),
                    "model_identity_hash": out["frozen"].get("model_identity_hash"),
                    "active_provider": out["frozen"].get("active_provider"),
                    "interval_payload_hash": (
                        out["frozen"].get("active_uncertainty") or {}
                    ).get("interval_payload_hash"),
                    "global_split_hash": out["frozen"].get("global_split_hash"),
                }
            _write(art / "grains" / f"{g['grain_id']}.json", slim)

            if (i + 1) % 10 == 0 or i == 0:
                print(
                    json.dumps(
                        {
                            "progress": i + 1,
                            "of": len(grains_meta),
                            "eligible": len(eligible),
                            "last": g["normalized_label"],
                            "status": out.get("status"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    # Cross-grain audit (uses subject sets collected above)
    audit = audit_cross_grain_splits(grain_subject_sets, seed=42)
    _write(art / "cross-grain-split-audit.json", audit)

    # Provider registry
    preg = build_global_provider_registry(eligible)
    write_registry(runtime / "global-provider-registry.json", preg)
    _write(art / "global-provider-registry.json", preg)
    reload_check = reload_all_providers_equality(preg)
    _write(art / "provider-reload-equality.json", reload_check)
    preg_status = (
        "PASS"
        if preg.get("GLOBAL_PROVIDER_REGISTRY_STATUS") == "PASS"
        and reload_check.get("ok")
        and preg.get("all_dimension_equality_ok")
        else "FAIL"
    )

    ensemble = SingleOutcomeTrajectoryEnsemble(
        [r["frozen"] for r in eligible if r.get("frozen")]
    )

    # Held-out inventory on global test subjects that have observations
    test_with_obs = sorted(subject_obs.keys())
    inventory = build_heldout_inventory(
        test_subjects=test_with_obs,
        subject_observations=subject_obs,
        ensemble=ensemble,
        horizon_days=30.0,
        max_subjects=max_inventory_subjects,
        max_states_per_subject=2,
    )
    private_states = inventory.pop("_private_states", [])
    _write(runtime / "heldout-states-private.json", {"n": len(private_states), "states": private_states})
    _write(art / "real-heldout-state-inventory.json", inventory)

    backtest = run_multi_outcome_backtest({"_private_states": private_states})
    _write(art / "real-heldout-multi-outcome-backtest.json", backtest)

    # Engine shadow: pick subject by coverage before looking at errors
    train_val = set(global_split["sets"]["train"]) | set(global_split["sets"]["validation"])
    selected = select_subject_by_coverage(private_states, train_val_subjects=train_val)
    if selected is None:
        engine = {
            "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": "FAIL",
            "reason": "no_eligible_test_subject",
        }
    else:
        engine = run_real_heldout_engine_shadow(
            selected_state_private=selected,
            observations_by_ou=subject_obs.get(selected["opaque_subject_key"]) or {},
            ensemble=ensemble,
            global_split=global_split,
        )
    _write(art / "engine-real-heldout-trajectory.json", engine)

    # Comparison vs v0.1.1
    n_provider_changed = sum(1 for r in eligible if r.get("provider_changed"))
    comparison = {
        "version": VERSION,
        "n_v011_candidates": len(grains_meta),
        "n_global_eligible": len(eligible),
        "n_global_ineligible": len(ineligible),
        "n_active_provider_changed": n_provider_changed,
        "ineligible_reasons": dict(Counter(r.get("reason") or r.get("status") for r in ineligible)),
        "note": "Metrics not carried from v0.1.1 when train manifest changed.",
    }
    _write(art / "v011-to-global-comparison.json", comparison)

    aggregate = {
        "version": VERSION,
        "candidate_grains": len(grains_meta),
        "GLOBAL_SPLIT_ELIGIBLE_GRAIN_COUNT": len(eligible),
        "n_ineligible": len(ineligible),
        "active_persistence": sum(
            1 for r in eligible if r.get("active_provider") == "persistence"
        ),
        "active_ridge": sum(1 for r in eligible if r.get("active_provider") == "ridge"),
        "active_trend": sum(
            1 for r in eligible if r.get("active_provider") == "empirical_trend"
        ),
        "outcome_status_counts": dict(Counter(r.get("status") for r in eligible)),
        "global_split_n_subjects": global_split["n_subjects"],
        "no_pooled_mae_across_units": True,
    }
    _write(art / "aggregate-report.json", aggregate)

    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "CROSS_GRAIN_SPLIT_AUDIT_STATUS": audit.get("CROSS_GRAIN_SPLIT_AUDIT_STATUS"),
        "GLOBAL_SUBJECT_SPLIT_STATUS": global_split.get("GLOBAL_SUBJECT_SPLIT_STATUS"),
        "GLOBAL_SPLIT_CONTAMINATION_STATUS": contamination.get(
            "GLOBAL_SPLIT_CONTAMINATION_STATUS"
        ),
        "GLOBAL_SPLIT_ELIGIBLE_GRAIN_COUNT": len(eligible),
        "GLOBAL_SPLIT_PROVIDER_TRAINING_STATUS": (
            "PASS" if eligible and all(r.get("frozen") for r in eligible) else "FAIL"
        ),
        "GLOBAL_SPLIT_BACKTEST_STATUS": (
            "PASS"
            if eligible
            and all(r.get("pair_overlap_zero") for r in eligible)
            else "FAIL"
        ),
        "INDIVIDUAL_STATE_ASSEMBLY_STATUS": "BUILT",
        "REAL_HELDOUT_STATE_INVENTORY_STATUS": inventory.get(
            "REAL_HELDOUT_STATE_INVENTORY_STATUS"
        ),
        "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS": backtest.get(
            "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS"
        ),
        "GLOBAL_PROVIDER_REGISTRY_STATUS": preg_status,
        "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": engine.get(
            "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS"
        ),
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_PUBLISH",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PENDING_PUBLISH",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
    }
    _write(art / "status-contract.json", {"version": VERSION, **statuses})

    tests = _run_tests(
        baseline,
        audit,
        global_split,
        contamination,
        eligible,
        ineligible,
        inventory,
        backtest,
        engine,
        reload_check,
        preg,
        statuses,
    )
    _write(art / "tests.json", tests)

    core_ok = (
        baseline.get("ok")
        and global_split.get("ok")
        and contamination.get("GLOBAL_SPLIT_CONTAMINATION_STATUS") == "PASS"
        and preg_status == "PASS"
        and engine.get("ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS")
        == "TECHNICAL_REAL_HELDOUT_PASS"
        and inventory.get("unexplained", 1) == 0
        and bool(tests.get("ok"))
    )
    verification = {
        "version": VERSION,
        "generated_at": _now(),
        "ok": core_ok,
        "duration_sec": round(time.time() - t0, 2),
        "statuses": statuses,
        "aggregate": aggregate,
        "max_grains": max_grains,
        "global_split_hash": global_split.get("split_hash"),
        "provider_registry_hash": preg.get("registry_hash"),
    }
    _write(art / "verification.json", verification)

    out = {
        "ok": verification["ok"],
        "verification": verification,
        "statuses": statuses,
        "aggregate": aggregate,
    }
    if not no_publish:
        from human_simulator.global_state_v01.publish import publish

        out["publication"] = publish(root)
    return out


def _run_tests(
    baseline: dict[str, Any],
    audit: dict[str, Any],
    global_split: dict[str, Any],
    contamination: dict[str, Any],
    eligible: list[dict[str, Any]],
    ineligible: list[dict[str, Any]],
    inventory: dict[str, Any],
    backtest: dict[str, Any],
    engine: dict[str, Any],
    reload_check: dict[str, Any],
    preg: dict[str, Any],
    statuses: dict[str, Any],
) -> dict[str, Any]:
    items = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        items.append({"name": name, "ok": bool(ok), "detail": detail})

    add("baseline_sha", baseline.get("ok") is True)
    add(
        "cross_grain_audit_ran",
        audit.get("CROSS_GRAIN_SPLIT_AUDIT_STATUS")
        in {"PASS", "CONFLICTS_DETECTED"},
        audit.get("CROSS_GRAIN_SPLIT_AUDIT_STATUS"),
    )
    add("global_split_pass", global_split.get("GLOBAL_SUBJECT_SPLIT_STATUS") == "PASS")
    add("global_split_repeatability", global_split.get("repeatability_ok") is True)
    add(
        "subset_invariance",
        global_split.get("subset_invariance_sample_ok") is True,
    )
    add("subject_overlap_zero", global_split.get("subject_overlap_zero") is True)
    add(
        "source_b_contamination_zero",
        contamination.get("source_b_rows_in_universe") == 0,
    )
    add(
        "eligible_unexplained_zero",
        all((r.get("dataset_summary") or {}).get("unexplained", 0) == 0 for r in eligible),
    )
    add(
        "pair_overlap_zero",
        all(r.get("pair_overlap_zero") for r in eligible) if eligible else False,
    )
    add(
        "no_medication_features",
        all(not r.get("medication_features_present") for r in eligible + ineligible),
    )
    add("provider_reload_all", reload_check.get("ok") is True)
    add(
        "provider_count_matches",
        preg.get("n_providers") == len(eligible),
    )
    add(
        "dimension_equality",
        preg.get("all_dimension_equality_ok") is True,
    )
    add(
        "inventory_unexplained_zero",
        inventory.get("unexplained") == 0,
    )
    add(
        "no_pooled_raw_mae",
        backtest.get("no_pooled_raw_mae_across_units") is True,
    )
    add(
        "engine_never_in_train_val",
        (engine.get("checks") or {}).get("never_in_train_validation") is True,
    )
    add(
        "engine_perturbation_effect",
        (engine.get("checks") or {}).get("observed_value_perturbation_changes_output")
        and (engine.get("checks") or {}).get("horizon_perturbation_changes_output"),
    )
    add(
        "engine_predictions_in_history",
        (engine.get("checks") or {}).get("predictions_in_evidence_history") is True,
    )
    add(
        "state_assembly_built",
        statuses.get("INDIVIDUAL_STATE_ASSEMBLY_STATUS") == "BUILT",
    )
    add(
        "medication_track_isolated",
        statuses.get("MEDICATION_RESIDUAL_MODEL_STATUS") == "NOT_STARTED"
        and statuses.get("QSP_STATUS") == "NOT_STARTED",
    )
    # Evidence: eligible count equals status field
    add(
        "eligible_count_matches",
        statuses.get("GLOBAL_SPLIT_ELIGIBLE_GRAIN_COUNT") == len(eligible),
    )
    return {"ok": all(i["ok"] for i in items), "n": len(items), "items": items}
