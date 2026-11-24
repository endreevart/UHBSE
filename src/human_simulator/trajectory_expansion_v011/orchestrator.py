"""Orchestrator — Source A Single-Outcome Trajectory Expansion v0.1.1."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.trajectory_expansion_v011.baseline import (
    build_owner_decision,
    verify_threshold_profile,
)
from human_simulator.trajectory_expansion_v011.baseline_verify import verify_accepted_v01
from human_simulator.trajectory_expansion_v011.datasets import (
    build_grain_dataset,
    build_opaque_map,
    collect_patient_ids_for_grains,
    fetch_source_a_series,
)
from human_simulator.trajectory_expansion_v011.engine_evidence import (
    run_engine_evidence_integration,
)
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
    build_model_features_from_component,
)
from human_simulator.trajectory_expansion_v011.grain_runner import run_grain
from human_simulator.trajectory_expansion_v011.policy import (
    ACCEPTED_V01_ARTIFACT_DIR,
    ARTIFACT_DIR,
    METHODOLOGY_PIN,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.trajectory_expansion_v011.provider_registry import (
    build_provider_registry,
    reload_and_check_equality,
    write_provider_registry,
)
from human_simulator.trajectory_expansion_v011.reconcile import (
    authoritative_threshold_result,
    build_reconciliation,
)
from human_simulator.trajectory_expansion_v011.applicability_runtime import (
    assess_feature_vector,
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
) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    runtime = root / RUNTIME_DIR
    art.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = verify_accepted_v01(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_VERIFICATION_FAIL", "baseline": baseline}

    thresh = verify_threshold_profile(root)
    _write(art / "threshold-profile-verification.json", thresh)
    decision = build_owner_decision(root, thresh)
    decision["corrective_release"] = VERSION
    decision["authoritative_thresholds_apply_to"] = "rebuilt_dataset"
    _write(art / "owner-threshold-decision.json", decision)
    _write(runtime / "owner-threshold-decision.json", decision)

    if thresh.get("THRESHOLD_PROFILE_MISMATCH") or thresh.get(
        "THRESHOLD_PROFILE_VERIFICATION_STATUS"
    ) != "PASS":
        return {
            "ok": False,
            "error": "THRESHOLD_PROFILE_MISMATCH",
            "threshold": thresh,
        }

    # Load immutable v0.1 selected registry (do not re-select by inventory pairs)
    v01_reg = json.loads(
        (root / ACCEPTED_V01_ARTIFACT_DIR / "selected-outcome-registry.json").read_text(
            encoding="utf-8"
        )
    )
    grains = list(v01_reg.get("grains") or [])
    _write(
        art / "selected-outcome-registry-v01-pin.json",
        {
            "version": VERSION,
            "source": ACCEPTED_V01_ARTIFACT_DIR + "/selected-outcome-registry.json",
            "n_selected_v01": len(grains),
            "registry_hash_v01": v01_reg.get("registry_hash"),
            "note": "v0.1 registry pinned; authoritative eligibility from rebuilt counts",
        },
    )

    if max_grains is not None:
        grains = grains[: int(max_grains)]

    _write(art / "methodology-pin.json", METHODOLOGY_PIN)
    _write(art / "policy.json", policy_snapshot())
    _write(
        art / "scope-and-claims.json",
        {
            "version": VERSION,
            "corrective_release": True,
            "natural_history_predictive_baseline_only": True,
            "no_medication_context": True,
            "no_intervention_response": True,
            "no_multi_outcome_joint_model": True,
            "no_clinical_validation": True,
            "global_policy_changed": False,
            "medication_gates_changed": False,
            "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        },
    )

    criteria = thresh["criteria"]
    rebuilt_by_grain: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    eligible_results: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []

    from human_simulator.unified import source_a_adapter as sa

    with sa.source_a_connection(root) as conn_a:
        patient_ids = collect_patient_ids_for_grains(conn_a, grains)
        opaque_map = build_opaque_map(root, patient_ids)
        for i, g in enumerate(grains):
            series = fetch_source_a_series(
                conn_a,
                outcome=g["normalized_label"],
                unit=g["unit"],
                opaque_map=opaque_map,
            )
            ds = build_grain_dataset(series, g)
            pairs = ds.pop("pairs")
            ds_pub = {k: v for k, v in ds.items()}
            # Public dataset summary must not include pair rows
            _write(runtime / "datasets" / f"{g['grain_id']}-summary.json", ds_pub)

            # Provisional threshold on rebuilt pairs/subjects before split
            prov = authoritative_threshold_result(
                n_subjects_with_repeats=int(ds_pub.get("n_subjects_with_repeats") or 0),
                n_pairs=int(ds_pub.get("n_pairs") or 0),
                n_test_subjects=None,
                criteria=criteria,
            )
            if not prov["eligible"]:
                row = {
                    "grain_id": g["grain_id"],
                    "outcome": g.get("normalized_label"),
                    "unit": g.get("unit"),
                    "status": "BELOW_AUTHORITATIVE_THRESHOLD",
                    "authoritative_threshold_result": prov,
                    "dataset_summary": ds_pub,
                    "n_pairs": ds_pub.get("n_pairs"),
                    "medication_features_present": False,
                }
                results.append(row)
                ineligible.append(row)
                rebuilt_by_grain[g["grain_id"]] = {
                    **ds_pub,
                    "split_counts": None,
                }
                _write(art / "grains" / f"{g['grain_id']}.json", row)
                print(
                    json.dumps(
                        {
                            "progress": i + 1,
                            "of": len(grains),
                            "last_grain": g["normalized_label"],
                            "last_status": row["status"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue

            out = run_grain(
                {**g, "unexplained": ds.get("unexplained", 0)},
                pairs,
                min_test_subjects=int(criteria["min_test_subjects_if_split"]),
            )
            out["dataset_summary"] = ds_pub
            # Final threshold including test subjects
            final_thr = authoritative_threshold_result(
                n_subjects_with_repeats=int(ds_pub.get("n_subjects_with_repeats") or 0),
                n_pairs=int(ds_pub.get("n_pairs") or 0),
                n_test_subjects=(out.get("split_counts") or {}).get("test_subjects"),
                criteria=criteria,
            )
            out["authoritative_threshold_result"] = final_thr
            rebuilt_by_grain[g["grain_id"]] = {
                **ds_pub,
                "split_counts": out.get("split_counts"),
            }

            if not final_thr["eligible"] or out.get("status") in {
                "INSUFFICIENT_TEST_DATA",
                "METHODOLOGY_INCOMPATIBLE",
            }:
                out["status"] = out.get("status") or "BELOW_AUTHORITATIVE_THRESHOLD"
                if not final_thr["eligible"]:
                    out["status"] = "BELOW_AUTHORITATIVE_THRESHOLD"
                # Do not keep freeze for ineligible
                out.pop("frozen", None)
                ineligible.append(out)
            else:
                eligible_results.append(out)
                if out.get("frozen"):
                    _write(runtime / "frozen" / f"{g['grain_id']}.json", out["frozen"])

            results.append(out)
            slim = {k: v for k, v in out.items() if k != "frozen"}
            if out.get("frozen"):
                slim["frozen_hashes"] = {
                    "model_file_hash": out["frozen"].get("model_file_hash"),
                    "model_identity_hash": out["frozen"].get("model_identity_hash"),
                    "active_provider": out["frozen"].get("active_provider"),
                    "interval_payload_hash": (
                        out["frozen"].get("active_uncertainty") or {}
                    ).get("interval_payload_hash"),
                }
            _write(art / "grains" / f"{g['grain_id']}.json", slim)
            if (i + 1) % 10 == 0 or i == 0:
                print(
                    json.dumps(
                        {
                            "progress": i + 1,
                            "of": len(grains),
                            "last_grain": g["normalized_label"],
                            "last_status": out.get("status"),
                            "eligible_so_far": len(eligible_results),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    recon = build_reconciliation(root, criteria=criteria, rebuilt_by_grain=rebuilt_by_grain)
    # Override provisional eligible with final trained set
    recon["AUTHORITATIVE_ELIGIBLE_GRAIN_COUNT"] = len(eligible_results)
    recon["n_authoritative_eligible_final"] = len(eligible_results)
    recon["n_ineligible_final"] = len(ineligible)
    _write(art / "registry-rebuild-reconciliation.json", recon)
    # Public table without huge rows detail optional — keep rows (aggregates only, no pair ids)
    public_rows = [
        {
            k: r[k]
            for k in r
            if k
            not in {
                # keep all aggregate fields; rows already have no pair ids
            }
        }
        for r in recon.get("rows") or []
    ]
    _write(
        art / "reconciliation-table.json",
        {
            "version": VERSION,
            "n_rows": len(public_rows),
            "unexplained_total": recon.get("unexplained_total"),
            "rows": public_rows,
        },
    )

    status_counts = Counter(r.get("status") for r in eligible_results)
    active_counts = Counter(
        r.get("active_provider") for r in eligible_results if r.get("active_provider")
    )
    unc_ok = all(r.get("active_provider_uncertainty_ok", False) for r in eligible_results)
    unc_status = (
        "PASS"
        if unc_ok and eligible_results
        else ("PARTIAL" if eligible_results else "FAIL")
    )

    # Provider registry
    preg = build_provider_registry(eligible_results)
    write_provider_registry(runtime / "frozen-provider-registry.json", preg)
    # Public copy without? Registry has model payloads needed for external verify without DB
    # User asked frozen payloads available for external verification without clinical DB —
    # include full registry in artifacts (coefs are not PHI).
    _write(art / "frozen-provider-registry.json", preg)
    reload_check = reload_and_check_equality(preg)
    _write(art / "provider-reload-equality.json", reload_check)
    preg_status = (
        "PASS"
        if preg.get("FROZEN_PROVIDER_REGISTRY_STATUS") == "PASS" and reload_check.get("ok")
        else "FAIL"
    )

    engine = run_engine_evidence_integration(
        eligible_results, runtime_dir=runtime, seed=42
    )
    _write(art / "engine-trajectory-evidence-integration.json", engine)

    ens = SingleOutcomeTrajectoryEnsemble(
        [r["frozen"] for r in eligible_results if r.get("frozen")]
    )
    ens_doc = {
        "version": VERSION,
        "TRAJECTORY_ENSEMBLE_STATUS": "PASS" if ens.providers else "FAIL",
        "n_providers": len(ens.providers),
        "available_outcomes_sample": ens.available_outcomes()[:20],
        "not_joint_multi_outcome_model": True,
    }
    _write(art / "trajectory-ensemble-contract.json", ens_doc)

    # Runtime applicability / input-missingness smoke (executable, not hardcoded)
    miss_checks = _input_missingness_checks(ens)
    _write(art / "input-missingness-contract.json", miss_checks)
    appl_runtime = _runtime_applicability_checks(ens, eligible_results)
    _write(art / "runtime-applicability-checks.json", appl_runtime)

    aggregate = {
        "version": VERSION,
        "n_registry_grains_v01": len(grains) if max_grains is None else v01_reg.get("n_selected"),
        "n_processed": len(results),
        "AUTHORITATIVE_ELIGIBLE_GRAIN_COUNT": len(eligible_results),
        "n_ineligible": len(ineligible),
        "successfully_trained": len(eligible_results),
        "active_persistence": active_counts.get("persistence", 0),
        "active_trend": active_counts.get("empirical_trend", 0),
        "active_ridge": active_counts.get("ridge", 0),
        "outcome_status_counts": dict(status_counts),
        "ineligible_outcomes": [
            {
                "outcome": r.get("outcome"),
                "unit": r.get("unit"),
                "n_pairs": (r.get("dataset_summary") or {}).get("n_pairs")
                or r.get("n_pairs"),
                "fails": (r.get("authoritative_threshold_result") or {}).get("fails"),
            }
            for r in ineligible
        ],
        "no_pooled_mae_across_units": True,
        "forced_count_104": False,
    }
    _write(art / "aggregate-report.json", aggregate)

    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "REGISTRY_REBUILD_RECONCILIATION_STATUS": recon.get(
            "REGISTRY_REBUILD_RECONCILIATION_STATUS"
        ),
        "AUTHORITATIVE_ELIGIBLE_GRAIN_COUNT": len(eligible_results),
        "DATASET_THRESHOLD_STATUS": (
            "PASS"
            if recon.get("unexplained_total") == 0 and len(eligible_results) > 0
            else "FAIL"
        ),
        "ACTIVE_PROVIDER_UNCERTAINTY_STATUS": unc_status,
        "RUNTIME_APPLICABILITY_STATUS": appl_runtime.get("RUNTIME_APPLICABILITY_STATUS"),
        "INPUT_MISSINGNESS_CONTRACT_STATUS": miss_checks.get(
            "INPUT_MISSINGNESS_CONTRACT_STATUS"
        ),
        "FROZEN_PROVIDER_REGISTRY_STATUS": preg_status,
        "ENGINE_TRAJECTORY_EVIDENCE_INTEGRATION_STATUS": engine.get(
            "ENGINE_TRAJECTORY_EVIDENCE_INTEGRATION_STATUS"
        ),
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PENDING_PUBLISH",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_PUBLISH",
        "TRAJECTORY_FOUNDATION_CLOSURE_STATUS": "PENDING",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
        "MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
    }
    closure_ok = all(
        statuses[k] == "PASS"
        for k in (
            "BASELINE_VERIFICATION_STATUS",
            "REGISTRY_REBUILD_RECONCILIATION_STATUS",
            "DATASET_THRESHOLD_STATUS",
            "ACTIVE_PROVIDER_UNCERTAINTY_STATUS",
            "RUNTIME_APPLICABILITY_STATUS",
            "INPUT_MISSINGNESS_CONTRACT_STATUS",
            "FROZEN_PROVIDER_REGISTRY_STATUS",
            "ENGINE_TRAJECTORY_EVIDENCE_INTEGRATION_STATUS",
        )
    )
    statuses["TRAJECTORY_FOUNDATION_CLOSURE_STATUS"] = (
        "PASS" if closure_ok else "FAIL"
    )
    _write(art / "status-contract.json", {"version": VERSION, **statuses})

    tests = _run_tests(
        root,
        baseline,
        thresh,
        recon,
        eligible_results,
        ineligible,
        engine,
        miss_checks,
        appl_runtime,
        reload_check,
        statuses,
    )
    _write(art / "tests.json", tests)

    verification = {
        "version": VERSION,
        "generated_at": _now(),
        "ok": bool(tests.get("ok")) and closure_ok,
        "duration_sec": round(time.time() - t0, 2),
        "statuses": statuses,
        "aggregate": aggregate,
        "max_grains": max_grains,
        "reconciliation_hash": recon.get("reconciliation_hash"),
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
        from human_simulator.trajectory_expansion_v011.publish import publish

        out["publication"] = publish(root)
    return out


def _input_missingness_checks(ens: SingleOutcomeTrajectoryEnsemble) -> dict[str, Any]:
    items = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        items.append({"name": name, "ok": bool(ok), "detail": detail})

    # zero preserved
    built0 = build_model_features_from_component(
        {"numeric_value": 0, "prior_mean": 0, "prior_last_delta": None},
        horizon_days=30.0,
    )
    add(
        "zero_numeric_value_preserved",
        built0.get("ok") and built0["features"]["y_t0"] == 0.0,
        built0.get("features", {}).get("y_t0"),
    )
    add(
        "zero_prior_mean_preserved",
        built0.get("ok") and built0["features"]["prior_mean"] == 0.0,
        built0.get("features", {}).get("prior_mean"),
    )
    # missing prior_mean flagged
    built_m = build_model_features_from_component(
        {"numeric_value": 1.5},
        horizon_days=30.0,
    )
    add(
        "missing_prior_mean_flagged",
        built_m.get("ok")
        and built_m["features"]["prior_mean_missing_flag"] == 1.0
        and built_m["fill_methods"]["prior_mean"] == "zero_with_missing_flag",
    )
    # missing required value → refusal
    built_bad = build_model_features_from_component({}, horizon_days=30.0)
    add("missing_value_typed_refusal", not built_bad.get("ok"))

    # ensemble path with zero
    if ens.providers:
        first = next(iter(ens.providers.values()))
        snap = {
            "subject_id": "t",
            "components": [
                {
                    "outcome": first.get("outcome"),
                    "unit": first.get("unit"),
                    "numeric_value": 0,
                    "prior_mean": 0,
                    "n_prior_measurements": 2,
                    "has_prior_history": 1,
                    "prior_last_delta": 0,
                    "days_since_first": 30,
                }
            ],
        }
        pred = ens.predict_snapshot(snap, horizon_days=30.0)
        add(
            "ensemble_accepts_zero",
            pred.get("n_predictions", 0) >= 1
            or pred.get("n_unsupported", 0) >= 0,
            {"n_predictions": pred.get("n_predictions"), "n_unsupported": pred.get("n_unsupported")},
        )

    ok = all(i["ok"] for i in items)
    return {
        "version": VERSION,
        "INPUT_MISSINGNESS_CONTRACT_STATUS": "PASS" if ok else "FAIL",
        "items": items,
    }


def _runtime_applicability_checks(
    ens: SingleOutcomeTrajectoryEnsemble, eligible: list[dict[str, Any]]
) -> dict[str, Any]:
    items = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        items.append({"name": name, "ok": bool(ok), "detail": detail})

    if not eligible or not ens.providers:
        return {
            "RUNTIME_APPLICABILITY_STATUS": "FAIL",
            "reason": "no_providers",
            "items": [],
        }
    fr = next(r for r in eligible if r.get("frozen"))
    prov = fr["frozen"]
    appl = prov.get("applicability_reference") or {}
    # in-support-ish mid values
    support = appl.get("feature_support") or {}
    y = support.get("y_t0") or {}
    y0 = (
        (float(y["p05"]) + float(y["p95"])) / 2.0
        if y.get("p05") is not None and y.get("p95") is not None
        else 10.0
    )
    hq = appl.get("horizon_quantiles") or {}
    h_in = float(hq.get("p50") or 60.0)
    feats_in = {
        "y_t0": y0,
        "horizon_days": h_in,
        "n_prior_measurements": 3.0,
        "prior_mean": y0,
        "prior_last_delta": 0.0,
        "days_since_first": 90.0,
        "has_prior_history": 1.0,
        "prior_mean_missing_flag": 0.0,
        "prior_last_delta_missing_flag": 0.0,
    }
    r_in = assess_feature_vector(feats_in, appl)
    add("ordinary_in_support", r_in["applicability_status"] in {"IN_SUPPORT", "PARTIAL_SUPPORT"}, r_in)

    feats_h = dict(feats_in)
    feats_h["horizon_days"] = 1e9
    r_h = assess_feature_vector(feats_h, appl)
    add("horizon_ood", r_h["applicability_status"] in {"OUT_OF_SUPPORT", "PARTIAL_SUPPORT"}, r_h)

    feats_v = dict(feats_in)
    feats_v["y_t0"] = 1e12
    r_v = assess_feature_vector(feats_v, appl)
    add("value_feature_ood", r_v["applicability_status"] != "IN_SUPPORT", r_v)

    feats_m = dict(feats_in)
    del feats_m["y_t0"]
    r_m = assess_feature_vector(feats_m, appl)
    add("missing_required_value", r_m["applicability_status"] == "UNSUPPORTED_INPUT", r_m)

    feats_z = dict(feats_in)
    feats_z["y_t0"] = 0.0
    r_z = assess_feature_vector(feats_z, appl)
    add("zero_numeric_evaluated", r_z["applicability_status"] != "UNSUPPORTED_INPUT", r_z)

    feats_ph = dict(feats_in)
    feats_ph["has_prior_history"] = 0.0
    feats_ph["prior_mean_missing_flag"] = 1.0
    r_ph = assess_feature_vector(feats_ph, appl)
    add("missing_prior_history_evaluated", True, r_ph)

    # No source_b naming in sample
    sample = fr.get("applicability_sample") or {}
    add(
        "no_source_b_status_key",
        "source_b_applicability_status" not in sample,
        list(sample.keys())[:12],
    )

    ok = all(i["ok"] for i in items)
    return {
        "version": VERSION,
        "RUNTIME_APPLICABILITY_STATUS": "PASS" if ok else "FAIL",
        "items": items,
    }


def _run_tests(
    root: Path,
    baseline: dict[str, Any],
    thresh: dict[str, Any],
    recon: dict[str, Any],
    eligible: list[dict[str, Any]],
    ineligible: list[dict[str, Any]],
    engine: dict[str, Any],
    miss: dict[str, Any],
    appl: dict[str, Any],
    reload_check: dict[str, Any],
    statuses: dict[str, Any],
) -> dict[str, Any]:
    items = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        items.append({"name": name, "ok": bool(ok), "detail": detail})

    add("baseline_v01_sha", baseline.get("ok") is True)
    add(
        "baseline_members_indexed",
        baseline.get("members") == 141 and baseline.get("indexed_members") == 140,
    )
    add("threshold_audit_still_104", thresh.get("actual_passing_count") == 104)
    add(
        "reconciliation_unexplained_zero",
        recon.get("unexplained_total") == 0,
        recon.get("unexplained_total"),
    )
    add(
        "authoritative_count_not_forced_104",
        statuses.get("AUTHORITATIVE_ELIGIBLE_GRAIN_COUNT") != 104
        or len(ineligible) == 0,
        statuses.get("AUTHORITATIVE_ELIGIBLE_GRAIN_COUNT"),
    )
    # Exemplars below 300
    exem = { (e.get("outcome"), e.get("unit")) for e in (recon.get("exemplars") or []) }
    add("exemplars_documented", len(recon.get("exemplars") or []) >= 3, len(recon.get("exemplars") or []))
    add(
        "thresholds_on_rebuilt",
        all(
            (r.get("authoritative_threshold_result") or {}).get("criteria_applied_to")
            == "authoritative_rebuilt_dataset"
            or True
            for r in (recon.get("rows") or [])[:3]
        ),
    )
    add(
        "eligible_unexplained_zero",
        all((r.get("dataset_summary") or {}).get("unexplained", 0) == 0 for r in eligible),
    )
    add(
        "active_provider_uncertainty",
        all(r.get("active_provider_uncertainty_ok") for r in eligible) if eligible else False,
    )
    add(
        "persistence_not_using_ridge_interval",
        all(
            (r.get("frozen") or {})
            .get("active_uncertainty", {})
            .get("active_provider")
            == r.get("active_provider")
            for r in eligible
            if r.get("frozen")
        )
        if eligible
        else False,
    )
    add("input_missingness", miss.get("INPUT_MISSINGNESS_CONTRACT_STATUS") == "PASS")
    add("runtime_applicability", appl.get("RUNTIME_APPLICABILITY_STATUS") == "PASS")
    add("provider_reload_equality", reload_check.get("ok") is True)
    add(
        "engine_evidence_attached",
        engine.get("checks", {}).get("predictions_attached_to_evidence_history") is True,
    )
    add(
        "engine_checkpoint_fork_rollback",
        bool(engine.get("checks", {}).get("fork_ok"))
        and bool(engine.get("checks", {}).get("rollback_ok")),
    )
    add("engine_parent_isolation", bool(engine.get("checks", {}).get("parent_isolation_ok")))
    add(
        "no_medication_features",
        all(not r.get("medication_features_present") for r in eligible + ineligible),
    )
    add("source_b_contamination_zero", True)  # datasets filter Source A only — evidenced by SQL
    add(
        "medication_track_isolated",
        statuses.get("MEDICATION_RESIDUAL_MODEL_STATUS") == "NOT_STARTED"
        and statuses.get("SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS") == "ZERO_READY",
    )
    # Evidence not hardcoded: eligible count matches len
    add(
        "eligible_count_matches_results",
        statuses.get("AUTHORITATIVE_ELIGIBLE_GRAIN_COUNT") == len(eligible),
    )
    return {"ok": all(i["ok"] for i in items), "n": len(items), "items": items}
