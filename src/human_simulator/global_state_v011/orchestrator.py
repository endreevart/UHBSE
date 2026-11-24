"""Orchestrator — Global State v0.1.1 horizon-aligned corrective (no provider refit)."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.global_state_v011.baseline_verify import (
    assert_no_refit,
    verify_baseline,
)
from human_simulator.global_state_v011.defect_audit import audit_v01_horizon_defect
from human_simulator.global_state_v011.engine_replay import (
    run_engine_and_actual_horizon_replay,
    select_subject_by_coverage,
)
from human_simulator.global_state_v011.frozen_load import (
    build_ensemble,
    load_v01_global_split,
    load_v01_registry,
    provider_lookup,
)
from human_simulator.global_state_v011.horizon_eval import (
    audit_target_identity,
    build_horizon_aligned_rows,
    build_inventory_summary,
    compute_corrected_metrics,
    evidence_tiers,
    select_primary_unique_targets,
)
from human_simulator.global_state_v011.leakage import run_leakage_checks
from human_simulator.global_state_v011.policy import (
    ACCEPTED_V01_ARTIFACT_DIR,
    ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.global_state_v01.provider_registry import reload_all_providers_equality
from human_simulator.trajectory_expansion_v011.datasets import (
    build_opaque_map,
    collect_patient_ids_for_grains,
    fetch_source_a_series,
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
    max_test_subjects: int | None = None,
    owner_explicit_cap_contract: str | None = None,
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

    registry = load_v01_registry(root)
    # Carry registry forward unchanged (no refit)
    _write(art / "global-provider-registry.json", registry)
    _write(runtime / "global-provider-registry.json", registry)
    no_refit = assert_no_refit(
        hashes_before=baseline["provider_hashes_before"],
        registry_after=registry,
    )
    _write(art / "frozen-provider-no-refit.json", no_refit)
    if not no_refit.get("ok"):
        return {"ok": False, "error": "REFIT_DETECTED", "no_refit": no_refit}

    reload_check = reload_all_providers_equality(registry)
    _write(art / "provider-reload-equality.json", reload_check)

    global_split = load_v01_global_split(root)
    # Public split contract from v0.1 (counts only)
    split_pub = json.loads(
        (
            root / ACCEPTED_V01_ARTIFACT_DIR / "global-subject-split-contract.json"
        ).read_text(encoding="utf-8")
    )
    _write(art / "global-subject-split-contract.json", split_pub)
    contamination = json.loads(
        (
            root / ACCEPTED_V01_ARTIFACT_DIR / "global-split-contamination.json"
        ).read_text(encoding="utf-8")
    )
    _write(art / "global-split-contamination.json", contamination)

    _write(art / "policy.json", policy_snapshot())
    _write(
        art / "scope-and-claims.json",
        {
            "version": VERSION,
            "corrective_over": "v0.1",
            "accepted_v01_sha256": baseline.get("accepted_v01_sha256_observed"),
            "no_provider_refit": True,
            "horizon_alignment_required": True,
            "orchestrated_independent_providers": True,
            "not_joint_multi_outcome_ml": True,
            "claim_level": "SECONDARY_EXPLORATORY_RETROSPECTIVE_BACKTEST",
            "no_medication_context": True,
            "no_clinical_validation": True,
        },
    )

    # Preserve prior v0.1 metrics (do not rewrite)
    prior_bt = json.loads(
        (
            root / ACCEPTED_V01_ARTIFACT_DIR / "real-heldout-multi-outcome-backtest.json"
        ).read_text(encoding="utf-8")
    )
    prior_inv = json.loads(
        (
            root / ACCEPTED_V01_ARTIFACT_DIR / "real-heldout-state-inventory.json"
        ).read_text(encoding="utf-8")
    )
    _write(
        art / "prior-v01-metrics-preserved.json",
        {
            "PRIOR_V01_BACKTEST_HORIZON_STATUS": "INVALID_FOR_HORIZON_ALIGNED_EVALUATION",
            "prior_backtest": prior_bt,
            "prior_inventory": prior_inv,
            "note": "Preserved for comparison; not rewritten.",
        },
    )

    ensemble = build_ensemble(registry)
    providers = provider_lookup(registry)
    provider_active = {k: v.get("active_provider") for k, v in providers.items()}
    grains_meta = [
        {
            "grain_id": p["grain_id"],
            "normalized_label": p["outcome"],
            "outcome": p["outcome"],
            "unit": p["unit"],
        }
        for p in registry.get("providers") or []
    ]

    subject_obs: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    from human_simulator.unified import source_a_adapter as sa

    with sa.source_a_connection(root) as conn_a:
        patient_ids = collect_patient_ids_for_grains(conn_a, grains_meta)
        opaque_map = build_opaque_map(root, patient_ids)
        for i, g in enumerate(grains_meta):
            series = fetch_source_a_series(
                conn_a,
                outcome=g["normalized_label"],
                unit=g["unit"],
                opaque_map=opaque_map,
            )
            for row in series:
                sid = row["opaque_subject_key"]
                if global_split["assignment"].get(sid) == "test":
                    subject_obs[sid][(g["normalized_label"], g["unit"])].append(row)
            if (i + 1) % 10 == 0 or i == 0:
                print(
                    json.dumps(
                        {
                            "progress_fetch": i + 1,
                            "of": len(grains_meta),
                            "test_subjects_with_obs": len(subject_obs),
                            "last": g["normalized_label"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    # Defect audit (uses observations for ridge delta when available)
    defect = audit_v01_horizon_defect(
        root=root,
        subject_observations=subject_obs,
        ensemble=ensemble,
        provider_active=provider_active,
    )
    _write(art / "prior-v01-horizon-defect-audit.json", defect)

    test_subjects = sorted(global_split["sets"]["test"])
    test_with_obs = sorted(s for s in test_subjects if subject_obs.get(s))
    print(
        json.dumps(
            {
                "phase": "horizon_aligned_eval",
                "n_global_test": len(test_subjects),
                "n_with_obs": len(test_with_obs),
            }
        ),
        flush=True,
    )

    built = build_horizon_aligned_rows(
        test_subjects=test_with_obs,
        subject_observations=subject_obs,
        ensemble=ensemble,
        max_states_per_subject=3,
        max_test_subjects=max_test_subjects,
        owner_explicit_cap_contract=owner_explicit_cap_contract,
    )
    built["funnel"]["n_global_test_subjects"] = len(test_subjects)
    rows = built["rows"]
    _write(
        runtime / "horizon-aligned-rows-private.json",
        {"n": len(rows), "note": "private; not published"},
    )

    identity = audit_target_identity(rows)
    _write(art / "target-identity-accounting.json", {k: v for k, v in identity.items()})

    primary_doc = select_primary_unique_targets(rows)
    primary_rows = primary_doc.pop("rows")
    _write(art / "target-reuse-audit.json", primary_doc)
    _write(
        runtime / "primary-targets-private.json",
        {"n": len(primary_rows), "note": "private locators; not published"},
    )

    # Sensitivity: repeated-forecast view (pre-dedup) — counts only
    sensitivity = {
        "view": "repeated_forecast_all_cutoffs",
        "n_rows": len(rows),
        "n_unique_targets": identity.get("n_unique_targets"),
        "note": "Sensitivity only; primary uses unique targets. Clustered accounting required for inference.",
        "not_primary": True,
    }
    _write(art / "sensitivity-repeated-forecast-view.json", sensitivity)

    tiers_doc = evidence_tiers(primary_rows)
    _write(art / "per-outcome-evidence-tiers.json", tiers_doc)

    metrics = compute_corrected_metrics(primary_rows, tiers_doc.get("tiers") or [])
    _write(art / "real-heldout-multi-outcome-backtest.json", metrics)

    inventory = build_inventory_summary(
        primary_rows=primary_rows,
        funnel=built["funnel"],
        n_states=built["n_states_assembled"],
    )
    inventory["unexplained"] = built.get("unexplained", 0)
    inventory["n_horizon_mismatch_refused"] = built.get("n_horizon_mismatch_refused", 0)
    inventory["n_zero_or_negative_horizons"] = built.get("n_zero_or_negative_horizons", 0)
    _write(art / "real-heldout-state-inventory.json", inventory)

    leakage = run_leakage_checks(
        primary_rows=primary_rows,
        global_split=global_split,
        contamination=contamination,
        no_refit=no_refit,
        medication_features_present=False,
    )
    _write(art / "leakage-independence-checks.json", leakage)

    # Metrics comparison table (aggregate only)
    comparison = {
        "version": VERSION,
        "why_metrics_differ": (
            "v0.1 predicted at fixed horizon_days=30 but scored against next observation "
            "at actual horizon (1–923d). v0.1.1 rebuilds features/applicability/inference "
            "at actual_horizon_days, deduplicates to unique targets, and evaluates the "
            "full global-test population (not first-N)."
        ),
        "prior_v01": {
            "status_mark": "INVALID_FOR_HORIZON_ALIGNED_EVALUATION",
            "n_prediction_targets": prior_bt.get("n_prediction_targets"),
            "n_outcomes_evaluated": prior_bt.get("n_outcomes_evaluated"),
            "overall_interval_coverage": prior_bt.get("overall_interval_coverage"),
            "n_test_subjects_considered": prior_inv.get("n_test_subjects_considered"),
        },
        "corrected_v011": {
            "n_primary_targets": metrics.get("n_primary_targets"),
            "n_evaluable_outcomes": metrics.get("n_evaluable_outcomes"),
            "n_diagnostic_only_outcomes": metrics.get("n_diagnostic_only_outcomes"),
            "funnel": built["funnel"],
            "provider_hashes_before": no_refit.get("provider_hashes_digest_before"),
            "provider_hashes_after": no_refit.get("provider_hashes_digest_after"),
        },
    }
    _write(art / "v01-vs-v011-metrics-comparison.json", comparison)

    train_val = set(global_split["sets"]["train"]) | set(global_split["sets"]["validation"])
    selected = select_subject_by_coverage(primary_rows, train_val_subjects=train_val)
    if selected is None:
        engine = {
            "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": "FAIL",
            "reason": "no_eligible_test_subject",
            "ok": False,
        }
    else:
        engine = run_engine_and_actual_horizon_replay(
            selected=selected,
            observations_by_ou=subject_obs.get(selected["opaque_subject_key"]) or {},
            ensemble=ensemble,
            global_split=global_split,
        )
    _write(art / "engine-real-heldout-trajectory.json", engine)

    # Re-assert no-refit after evaluation
    no_refit_after = assert_no_refit(
        hashes_before=baseline["provider_hashes_before"],
        registry_after=load_v01_registry(root),
    )
    _write(art / "frozen-provider-no-refit-after.json", no_refit_after)

    preg_status = (
        "PASS"
        if registry.get("GLOBAL_PROVIDER_REGISTRY_STATUS") == "PASS"
        and reload_check.get("ok")
        and no_refit.get("ok")
        and no_refit_after.get("ok")
        else "FAIL"
    )

    aggregate = {
        "version": VERSION,
        "n_providers_frozen": len(registry.get("providers") or []),
        "active_ridge": sum(
            1 for p in registry.get("providers") or [] if p.get("active_provider") == "ridge"
        ),
        "active_persistence": sum(
            1
            for p in registry.get("providers") or []
            if p.get("active_provider") == "persistence"
        ),
        "n_evaluable": tiers_doc.get("n_evaluable"),
        "n_diagnostic_only": tiers_doc.get("n_diagnostic_only"),
        "n_primary_targets": len(primary_rows),
        "funnel": built["funnel"],
        "no_pooled_mae_across_units": True,
        "no_provider_refit": True,
    }
    _write(art / "aggregate-report.json", aggregate)

    # Publication lifecycle: inside artifacts, post-pack is EXTERNAL_ATTESTATION_REQUIRED
    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "PRIOR_V01_BACKTEST_HORIZON_STATUS": defect.get("PRIOR_V01_BACKTEST_HORIZON_STATUS"),
        "FROZEN_PROVIDER_NO_REFIT_STATUS": no_refit.get("FROZEN_PROVIDER_NO_REFIT_STATUS"),
        "HORIZON_ALIGNMENT_STATUS": metrics.get("HORIZON_ALIGNMENT_STATUS"),
        "TARGET_IDENTITY_ACCOUNTING_STATUS": identity.get("TARGET_IDENTITY_ACCOUNTING_STATUS"),
        "TARGET_REUSE_AUDIT_STATUS": primary_doc.get("TARGET_REUSE_AUDIT_STATUS"),
        "GLOBAL_TEST_POPULATION_EVALUATION_STATUS": inventory.get(
            "GLOBAL_TEST_POPULATION_EVALUATION_STATUS"
        ),
        "PER_OUTCOME_EVIDENCE_TIER_STATUS": tiers_doc.get("PER_OUTCOME_EVIDENCE_TIER_STATUS"),
        "REAL_HELDOUT_STATE_INVENTORY_STATUS": inventory.get(
            "REAL_HELDOUT_STATE_INVENTORY_STATUS"
        ),
        "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS": metrics.get(
            "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS"
        ),
        "GLOBAL_PROVIDER_REGISTRY_STATUS": preg_status,
        "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": engine.get(
            "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS"
        ),
        "INDIVIDUAL_STATE_ASSEMBLY_STATUS": "BUILT",
        "LEAKAGE_INDEPENDENCE_STATUS": leakage.get("LEAKAGE_INDEPENDENCE_STATUS"),
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        # Pre-pack / content checks (set PASS when green). Post-pack inside ZIP:
        "PUBLIC_DATA_MINIMIZATION_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "PUBLICATION_INTEGRITY_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "CONTENT_PREPACK_STATUS": "PENDING_VERIFY",
    }
    _write(art / "status-contract.json", {"version": VERSION, **statuses})

    tests = _run_tests(
        baseline=baseline,
        defect=defect,
        no_refit=no_refit,
        no_refit_after=no_refit_after,
        identity=identity,
        primary_doc=primary_doc,
        inventory=inventory,
        tiers_doc=tiers_doc,
        metrics=metrics,
        leakage=leakage,
        engine=engine,
        reload_check=reload_check,
        statuses=statuses,
        built=built,
    )
    _write(art / "tests.json", tests)

    # CONTENT_PREPACK becomes PASS after internal tests
    if tests.get("ok"):
        statuses["CONTENT_PREPACK_STATUS"] = "PASS"
        _write(art / "status-contract.json", {"version": VERSION, **statuses})

    core_ok = (
        baseline.get("ok")
        and no_refit.get("ok")
        and no_refit_after.get("ok")
        and metrics.get("ok")
        and primary_doc.get("ok")
        and tiers_doc.get("ok")
        and leakage.get("ok")
        and engine.get("ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS")
        == "TECHNICAL_REAL_HELDOUT_PASS"
        and inventory.get("unexplained", 1) == 0
        and built.get("n_horizon_mismatch_refused", 1) == 0
        and bool(tests.get("ok"))
        and statuses.get("PRIOR_V01_BACKTEST_HORIZON_STATUS")
        == "INVALID_FOR_HORIZON_ALIGNED_EVALUATION"
    )
    verification = {
        "version": VERSION,
        "generated_at": _now(),
        "ok": core_ok,
        "duration_sec": round(time.time() - t0, 2),
        "statuses": statuses,
        "aggregate": aggregate,
        "provider_registry_hash": registry.get("registry_hash"),
        "provider_hashes_before": no_refit.get("provider_hashes_digest_before"),
        "provider_hashes_after": no_refit_after.get("provider_hashes_digest_after"),
    }
    _write(art / "verification.json", verification)

    # Report
    _write_report(art, statuses, aggregate, comparison, defect, metrics, tiers_doc, inventory)

    out = {
        "ok": verification["ok"],
        "verification": verification,
        "statuses": statuses,
        "aggregate": aggregate,
    }
    if not verification["ok"]:
        blockers = _blockers(statuses, tests, built, primary_doc, metrics, leakage, engine)
        out["blockers"] = blockers
        print(json.dumps({"ok": False, "blockers": blockers}, indent=2), flush=True)
        return out

    if not no_publish:
        from human_simulator.global_state_v011.publish import publish

        out["publication"] = publish(root)
    return out


def _blockers(
    statuses: dict[str, Any],
    tests: dict[str, Any],
    built: dict[str, Any],
    primary_doc: dict[str, Any],
    metrics: dict[str, Any],
    leakage: dict[str, Any],
    engine: dict[str, Any],
) -> list[dict[str, Any]]:
    out = []
    for k, v in statuses.items():
        if k.endswith("_STATUS") and v in {"FAIL", "PENDING_VERIFY"}:
            if k in {
                "PUBLIC_DATA_MINIMIZATION_STATUS",
                "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS",
                "PUBLICATION_INTEGRITY_STATUS",
            }:
                continue  # expected EXTERNAL_ATTESTATION_REQUIRED until external att
            if v == "EXTERNAL_ATTESTATION_REQUIRED":
                continue
            if k == "PRIOR_V01_BACKTEST_HORIZON_STATUS":
                continue  # expected INVALID_...
            out.append({"status": k, "value": v})
    if statuses.get("PRIOR_V01_BACKTEST_HORIZON_STATUS") != (
        "INVALID_FOR_HORIZON_ALIGNED_EVALUATION"
    ):
        out.append(
            {
                "status": "PRIOR_V01_BACKTEST_HORIZON_STATUS",
                "value": statuses.get("PRIOR_V01_BACKTEST_HORIZON_STATUS"),
            }
        )
    if not tests.get("ok"):
        out.append({"status": "tests", "failed": tests.get("failed")})
    if built.get("n_horizon_mismatch_refused", 0):
        out.append(
            {
                "status": "horizon_mismatch_refused",
                "count": built.get("n_horizon_mismatch_refused"),
            }
        )
    if not primary_doc.get("ok"):
        out.append(
            {
                "status": "target_reuse",
                "count": primary_doc.get("primary_target_reuse"),
            }
        )
    if not metrics.get("ok"):
        out.append({"status": "metrics", "detail": metrics.get("HORIZON_ALIGNMENT_STATUS")})
    if not leakage.get("ok"):
        out.append(
            {
                "status": "leakage",
                "failed": [c for c in leakage.get("checks") or [] if not c.get("ok")],
            }
        )
    if engine.get("ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS") != "TECHNICAL_REAL_HELDOUT_PASS":
        out.append(
            {
                "status": "engine",
                "value": engine.get("ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS"),
            }
        )
    return out


def _write_report(
    art: Path,
    statuses: dict[str, Any],
    aggregate: dict[str, Any],
    comparison: dict[str, Any],
    defect: dict[str, Any],
    metrics: dict[str, Any],
    tiers_doc: dict[str, Any],
    inventory: dict[str, Any],
) -> None:
    lines = [
        f"# Global Split + Individual Multi-Outcome State v{VERSION}",
        "",
        "Corrective release: horizon-aligned full-test backtest and evidence closure.",
        "Frozen v0.1 providers were **not** refit.",
        "",
        "## Statuses",
        "",
    ]
    for k in (
        "BASELINE_VERIFICATION_STATUS",
        "PRIOR_V01_BACKTEST_HORIZON_STATUS",
        "FROZEN_PROVIDER_NO_REFIT_STATUS",
        "HORIZON_ALIGNMENT_STATUS",
        "TARGET_IDENTITY_ACCOUNTING_STATUS",
        "TARGET_REUSE_AUDIT_STATUS",
        "GLOBAL_TEST_POPULATION_EVALUATION_STATUS",
        "PER_OUTCOME_EVIDENCE_TIER_STATUS",
        "REAL_HELDOUT_STATE_INVENTORY_STATUS",
        "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS",
        "GLOBAL_PROVIDER_REGISTRY_STATUS",
        "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS",
        "CURRENT_STATE_CLASSIFIER_STATUS",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS",
        "MEDICATION_RESIDUAL_MODEL_STATUS",
        "INTERVENTION_RESPONSE_MODEL_STATUS",
        "CLINICAL_VALIDATION_STATUS",
        "PRODUCTION_READINESS",
        "SECURITY_STAGE_STATUS",
    ):
        lines.append(f"- `{k}` = `{statuses.get(k)}`")
    lines.extend(
        [
            "",
            "## Why v0.1 metrics are invalid for horizon-aligned evaluation",
            "",
            defect.get("defect_statement") or "",
            "",
            f"- exact horizon matches: {defect.get('n_exact_horizon_matches')} / "
            f"{defect.get('n_targets_audited')}",
            f"- mismatches: {defect.get('n_horizon_mismatches')}",
            f"- actual horizon median: {(defect.get('actual_horizon_distribution') or {}).get('median')}",
            "",
            "## Funnel (full global test)",
            "",
            "```json",
            json.dumps(inventory.get("funnel") or {}, indent=2),
            "```",
            "",
            f"- EVALUABLE outcomes: {tiers_doc.get('n_evaluable')}",
            f"- DIAGNOSTIC_ONLY outcomes: {tiers_doc.get('n_diagnostic_only')}",
            f"- primary unique targets: {metrics.get('n_primary_targets')}",
            "",
            "## Metrics comparison",
            "",
            comparison.get("why_metrics_differ") or "",
            "",
            "### Prior v0.1 (preserved, marked invalid)",
            "",
            "```json",
            json.dumps(comparison.get("prior_v01") or {}, indent=2),
            "```",
            "",
            "### Corrected v0.1.1",
            "",
            "```json",
            json.dumps(comparison.get("corrected_v011") or {}, indent=2),
            "```",
            "",
            "## Publication lifecycle",
            "",
            "Inside the review ZIP, post-pack statuses are "
            "`EXTERNAL_ATTESTATION_REQUIRED`. Final PASS is only in the external "
            "attestation sidecar.",
            "",
        ]
    )
    (art / "stage-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_tests(**kwargs: Any) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    baseline = kwargs["baseline"]
    defect = kwargs["defect"]
    no_refit = kwargs["no_refit"]
    no_refit_after = kwargs["no_refit_after"]
    identity = kwargs["identity"]
    primary_doc = kwargs["primary_doc"]
    inventory = kwargs["inventory"]
    tiers_doc = kwargs["tiers_doc"]
    metrics = kwargs["metrics"]
    leakage = kwargs["leakage"]
    engine = kwargs["engine"]
    reload_check = kwargs["reload_check"]
    statuses = kwargs["statuses"]
    built = kwargs["built"]

    add("baseline_ok", baseline.get("ok"))
    add(
        "prior_marked_invalid",
        defect.get("PRIOR_V01_BACKTEST_HORIZON_STATUS")
        == "INVALID_FOR_HORIZON_ALIGNED_EVALUATION",
    )
    add("no_refit", no_refit.get("ok") and no_refit_after.get("ok"))
    add("hashes_before_equals_after", no_refit.get("before_equals_after"))
    add("reload_equality", reload_check.get("ok"))
    add("target_reuse_zero", primary_doc.get("primary_target_reuse") == 0)
    add("horizon_mismatch_refused_zero", built.get("n_horizon_mismatch_refused") == 0)
    add("horizon_alignment", metrics.get("HORIZON_ALIGNMENT_STATUS") == "PASS")
    add("evaluable_ge1", (tiers_doc.get("n_evaluable") or 0) >= 1)
    add("full_test_funnel", inventory.get("funnel", {}).get("n_global_test_subjects") == 6635)
    add("no_silent_cap", inventory.get("funnel", {}).get("silent_cap_used") is False)
    add("leakage_ok", leakage.get("ok"))
    add(
        "engine_pass",
        engine.get("ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS") == "TECHNICAL_REAL_HELDOUT_PASS",
    )
    add(
        "publication_status_consistent",
        statuses.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "EXTERNAL_ATTESTATION_REQUIRED"
        and statuses.get("REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS")
        == "EXTERNAL_ATTESTATION_REQUIRED",
    )
    add("identity_status", identity.get("TARGET_IDENTITY_ACCOUNTING_STATUS") == "PASS")
    failed = [c for c in checks if not c["ok"]]
    return {
        "ok": len(failed) == 0,
        "n_checks": len(checks),
        "n_failed": len(failed),
        "failed": failed,
        "checks": checks,
    }
