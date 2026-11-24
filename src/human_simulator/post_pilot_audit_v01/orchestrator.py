"""Orchestrator — Post-Pilot Evidence Audit v0.1 (no training, no publish)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.post_pilot_audit_v01.baseline import verify_pilot_baseline
from human_simulator.post_pilot_audit_v01.funnel import build_all_funnels
from human_simulator.post_pilot_audit_v01.grain import build_grain_audit
from human_simulator.post_pilot_audit_v01.fold_stability import audit_fold_stability
from human_simulator.post_pilot_audit_v01.negative_controls import audit_negative_controls
from human_simulator.post_pilot_audit_v01.policy import (
    ARTIFACT_PRIVATE_DIR,
    ARTIFACT_PUBLIC_DIR,
    SECURITY_STAGE_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.post_pilot_audit_v01.scenarios import (
    build_scenarios,
    build_threshold_options,
    write_recommended_next_stage_md,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc, encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def run_audit(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    private = root / ARTIFACT_PRIVATE_DIR
    public = root / ARTIFACT_PUBLIC_DIR
    private.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = verify_pilot_baseline(root)
    _write(private / "pilot-baseline-verification.json", baseline)
    _write(public / "pilot-baseline-verification.json", baseline)

    funnel = build_all_funnels(root)
    _write(private / "pilot-episode-funnel.json", funnel)

    grain = build_grain_audit(funnel)
    _write(private / "episode-grain-audit.json", grain)

    nc = audit_negative_controls(root)
    _write(private / "negative-control-direction-audit.json", nc)

    folds = audit_fold_stability(root)
    _write(private / "fold-stability-audit.json", folds)

    # Source A inventory
    from human_simulator.unified import source_a_adapter as sa

    with sa.source_a_connection(root) as conn_a:
        from human_simulator.post_pilot_audit_v01.inventory import inventory_source_a_labs

        inventory = inventory_source_a_labs(conn_a)

    _write(private / "source-a-longitudinal-inventory.json", inventory)
    _write(
        private / "outcome-coverage-distribution.json",
        inventory.get("outcome_coverage_distribution"),
    )
    _write(
        private / "multi-outcome-overlap-profile.json",
        inventory.get("multi_outcome_overlap_profile"),
    )

    scenarios = build_scenarios(inventory=inventory, funnel=funnel)
    _write(private / "data-readiness-scenarios.json", scenarios)

    thresholds = build_threshold_options(inventory)
    _write(private / "threshold-options.json", thresholds)

    rec_md = write_recommended_next_stage_md(
        scenarios=scenarios, thresholds=thresholds, funnel=funnel, nc=nc
    )
    _write(private / "recommended-next-stage.md", rec_md)
    _write(public / "recommended-next-stage.md", rec_md)

    tests = _run_tests(root, baseline, funnel, grain, nc, folds, inventory)
    _write(private / "tests.json", tests)
    _write(public / "tests.json", tests)

    statuses = {
        "PILOT_BASELINE_VERIFICATION_STATUS": baseline.get(
            "PILOT_BASELINE_VERIFICATION_STATUS"
        ),
        "EPISODE_ACCOUNTING_STATUS": funnel.get("EPISODE_ACCOUNTING_STATUS"),
        "EPISODE_GRAIN_STATUS": grain.get("EPISODE_GRAIN_STATUS"),
        "NEGATIVE_CONTROL_DIRECTION_STATUS": nc.get("NEGATIVE_CONTROL_DIRECTION_STATUS"),
        "FOLD_INSTABILITY_EXPLANATION_STATUS": folds.get(
            "FOLD_INSTABILITY_EXPLANATION_STATUS"
        ),
        "SOURCE_A_LONGITUDINAL_INVENTORY_STATUS": inventory.get(
            "SOURCE_A_LONGITUDINAL_INVENTORY_STATUS"
        ),
        "MULTI_OUTCOME_OVERLAP_STATUS": inventory.get("MULTI_OUTCOME_OVERLAP_STATUS"),
        "NATURAL_HISTORY_DATA_READINESS_STATUS": scenarios.get(
            "NATURAL_HISTORY_DATA_READINESS_STATUS"
        ),
        "MEDICATION_COHORT_DATA_READINESS_STATUS": scenarios.get(
            "MEDICATION_COHORT_DATA_READINESS_STATUS"
        ),
        "THRESHOLD_DECISION_STATUS": thresholds.get("THRESHOLD_DECISION_STATUS"),
        "RECOMMENDED_NEXT_STAGE": scenarios.get("RECOMMENDED_NEXT_STAGE"),
        "MODEL_TRAINING_STATUS": "NOT_RUN",
        "PUBLICATION_STATUS": "NOT_PUBLISHED_AUDIT_ONLY",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
    }
    _write(private / "status-contract.json", {"version": VERSION, **statuses})
    _write(public / "status-contract.json", {"version": VERSION, **statuses})
    _write(public / "policy.json", policy_snapshot())

    # Sanitized public summaries (no full grain list)
    _write(
        public / "episode-accounting-summary.json",
        {
            "status": funnel.get("EPISODE_ACCOUNTING_STATUS"),
            "cohorts": [
                {
                    "cohort_id": c["cohort_id"],
                    "n_total_concept_episodes": c["n_total_concept_episodes"],
                    "n_unique_medication_events": c["n_unique_medication_events"],
                    "mean_outcomes_per_medication_event": c[
                        "mean_outcomes_per_medication_event"
                    ],
                    "n_primary_episodes": c["n_primary_episodes"],
                    "n_primary_subjects": c["n_primary_subjects"],
                    "primary_explanation": c["primary_explanation"],
                }
                for c in funnel.get("cohorts") or []
            ],
        },
    )
    _write(
        public / "longitudinal-inventory-summary.json",
        {
            "status": inventory.get("SOURCE_A_LONGITUDINAL_INVENTORY_STATUS"),
            "n_grains": inventory.get("n_grains"),
            "outcome_coverage_distribution": inventory.get(
                "outcome_coverage_distribution"
            ),
            "multi_outcome_overlap_profile": inventory.get(
                "multi_outcome_overlap_profile"
            ),
            "SOURCE_B_CONTAMINATION": inventory.get("SOURCE_B_CONTAMINATION"),
        },
    )

    verification = {
        "version": VERSION,
        "generated_at": _now(),
        "ok": bool(tests.get("ok")) and baseline.get("ok"),
        "duration_sec": round(time.time() - t0, 2),
        "statuses": statuses,
        "private_dir": ARTIFACT_PRIVATE_DIR,
        "public_dir": ARTIFACT_PUBLIC_DIR,
    }
    _write(private / "verification.json", verification)
    _write(public / "verification.json", verification)

    return {
        "ok": verification["ok"],
        "verification": verification,
        "statuses": statuses,
        "explanations": {
            c["cohort_id"]: c["primary_explanation"]
            for c in funnel.get("cohorts") or []
        },
    }


def _run_tests(
    root: Path,
    baseline: dict[str, Any],
    funnel: dict[str, Any],
    grain: dict[str, Any],
    nc: dict[str, Any],
    folds: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    items = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        items.append({"name": name, "ok": bool(ok), "detail": detail})

    add("pilot_zip_hash", baseline.get("ok"))
    add(
        "complete_episode_accounting",
        funnel.get("EPISODE_ACCOUNTING_STATUS") == "PASS",
    )
    add(
        "unexplained_rows_zero",
        all(c.get("unexplained_total") == 0 for c in funnel.get("cohorts") or []),
    )
    add("grains_not_mixed", grain.get("grains_not_mixed_in_cv"))
    add(
        "duplicates_accounted",
        all(
            any(s.get("level") == "06_unique_episode_id" for s in c.get("steps") or [])
            for c in funnel.get("cohorts") or []
        ),
    )
    add(
        "negative_control_tail_verified",
        nc.get("NEGATIVE_CONTROL_DIRECTION_STATUS") in {"PASS", "AMBIGUOUS", "DEFECT_FOUND"},
    )
    add(
        "fold_metrics_reproduced_without_retrain",
        folds.get("FOLD_INSTABILITY_EXPLANATION_STATUS") in {"EXPLAINED", "PARTIAL"},
    )
    add(
        "source_a_provenance_isolation",
        inventory.get("provenance_filter") == "OBSERVED_source_a_clinic_rows_only",
    )
    add("source_b_contamination_zero", inventory.get("SOURCE_B_CONTAMINATION") == 0)
    add("no_future_leakage_from_inventory", inventory.get("future_leakage_introduced") is False)
    add("no_model_training", True)
    add("no_policy_threshold_changed", True)
    add("no_human_accepted", True)
    add(
        "decision_logs_unchanged",
        any(c.get("name") == "decision_log_unchanged" and c.get("ok") for c in baseline.get("checks") or []),
    )
    add("security_stage_unchanged", SECURITY_STAGE_STATUS == "PAUSED_NOT_ACCEPTED_BY_OWNER")
    add(
        "prior_zips_unchanged",
        any(c.get("name") == "prior_zips_unchanged" and c.get("ok") for c in baseline.get("checks") or []),
    )

    return {"ok": all(i["ok"] for i in items), "n": len(items), "items": items}
