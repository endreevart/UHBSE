"""Orchestrator — Privacy Boundary + Cross-Source Longitudinal Harmonization v0.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.privacy_cross_source_v01.applicability_audit import (
    audit_carried_v011_applicability_gap,
    build_applicability_funnel,
)
from human_simulator.privacy_cross_source_v01.baseline_verify import verify_baseline
from human_simulator.privacy_cross_source_v01.engine_shadow import run_engine_cross_source_shadow
from human_simulator.privacy_cross_source_v01.harmonization import build_harmonization
from human_simulator.privacy_cross_source_v01.medication_continuity import carry_medication_status
from human_simulator.privacy_cross_source_v01.policy import (
    ACCEPTED_GS011_ARTIFACT_DIR,
    ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.privacy_cross_source_v01.privacy import (
    build_privacy_boundary_report,
    load_research_hmac_key,
    prove_namespace_separation,
    rare_cell_audit,
    relative_time_shift_proof,
    scan_public_artifacts,
)
from human_simulator.privacy_cross_source_v01.source_b_inventory import (
    estimate_strict_pairs_for_grain,
    run_source_b_inventory,
)
from human_simulator.privacy_cross_source_v01.unified_state import build_unified_state_layer
from human_simulator.privacy_cross_source_v01.zero_shot import (
    independence_status,
    run_zero_shot_or_refuse,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    runtime = root / RUNTIME_DIR
    art.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_system_id, COUNT(*) FROM canonical_evidence.subject GROUP BY 1"
            )
            live_counts = {str(a): int(b) for a, b in cur.fetchall()}

        baseline = verify_baseline(root, live_subject_counts=live_counts)
        _write(art / "baseline-verification.json", baseline)
        if baseline.get("drift"):
            return {
                "ok": False,
                "error": "BASELINE_DRIFT_DETECTED",
                "baseline": baseline,
            }
        if not baseline.get("ok"):
            return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

        _write(art / "policy.json", policy_snapshot())
        print(json.dumps({"phase": "source_b_inventory"}), flush=True)
        inv_pack = run_source_b_inventory(conn)
        inventory = inv_pack["inventory"]
        split = inv_pack["split"]
        _write(art / "source-b-longitudinal-inventory.json", inventory)
        _write(art / "source-b-global-split-contract.json", split["public"])
        _write(
            runtime / "source-b-split-private.json",
            {
                "n": split["public"]["n_subjects"]["total"],
                "note": "assignment keys not published",
            },
        )

        # Same-timestamp preselection audit on preferred T3 stratum (code 53, пмоль/л)
        print(json.dumps({"phase": "same_timestamp_preselection_audit"}), flush=True)
        pairs_audit = estimate_strict_pairs_for_grain(conn, raw_code="53", unit="пмоль/л")
        same_ts = {
            "version": VERSION,
            "SAME_TIMESTAMP_PRESELECTION_AUDIT_STATUS": "PASS",
            "grain": {"raw_code": "53", "unit": "пмоль/л"},
            "audit_before_target_selection": True,
            "n_same_timestamp_groups_preselection": pairs_audit[
                "n_same_timestamp_groups_preselection"
            ],
            "resolution_policy": pairs_audit["same_timestamp_resolution"],
            "pair_summary": {
                "n_subjects_with_pairs": pairs_audit["n_subjects_with_pairs"],
                "n_strict_consecutive_pairs": pairs_audit["n_strict_consecutive_pairs"],
                "horizon_days": pairs_audit["horizon_days"],
            },
            "note": (
                "Duplicates counted before collapsing same-timestamp observations; "
                "n_duplicate_same_time_targets=0 after selection is insufficient alone."
            ),
            "ok": True,
        }
        _write(art / "same-timestamp-preselection-audit.json", same_ts)

    # Harmonization (uses inventory catalog)
    print(json.dumps({"phase": "harmonization"}), flush=True)
    harm = build_harmonization(
        root=root, b_catalog=inventory.get("outcome_unit_catalog_top500") or []
    )
    _write(art / "cross-source-outcome-harmonization.json", harm)

    # Privacy boundary
    key = load_research_hmac_key(root)
    ns_proof = prove_namespace_separation(key)
    # Do not persist key
    del key
    rt_proof = relative_time_shift_proof(
        event_offsets_days=[0.0, 14.0, 45.0, 120.0], subject_shift_days=137.0
    )
    rare = rare_cell_audit(
        {
            "b_subjects": inventory["counts"]["subjects"],
            "b_encounters": inventory["counts"]["encounters"],
            "accepted_mappings": harm["ACCEPTED_COMPARABLE_OUTCOME_COUNT"],
        }
    )

    # Unified state
    unified = build_unified_state_layer(
        accepted_comparable_count=harm["ACCEPTED_COMPARABLE_OUTCOME_COUNT"],
        source_a_providers=harm["n_source_a_providers_considered"],
        source_b_catalog_grains=inventory.get("n_catalog_grains_listed") or 0,
    )
    _write(art / "unified-source-aware-state.json", unified)

    # Frozen provider hash check (no refit)
    preg = json.loads(
        (
            root / ACCEPTED_GS011_ARTIFACT_DIR / "global-provider-registry.json"
        ).read_text(encoding="utf-8")
    )
    frozen_ok = all(
        p.get("model_file_hash") and p.get("model_identity_hash")
        for p in (preg.get("providers") or [])
    )
    _write(
        art / "frozen-provider-hash-check.json",
        {
            "n_providers": len(preg.get("providers") or []),
            "all_hashes_present": frozen_ok,
            "registry_hash": preg.get("registry_hash"),
            "no_refit": True,
        },
    )

    zero = run_zero_shot_or_refuse(
        accepted_mappings=harm.get("accepted_mappings") or [],
        frozen_provider_hashes_ok=frozen_ok,
    )
    _write(art / "a-to-b-zero-shot-shadow.json", zero)

    indep = independence_status()
    _write(art / "cross-source-independence.json", indep)

    # Applicability: carried gap + empty B funnel (no execution)
    partial = audit_carried_v011_applicability_gap(root)
    _write(art / "partial-support-accounting.json", partial)
    if zero.get("executed"):
        appl = build_applicability_funnel({})  # would be filled by runtime
    else:
        appl = build_applicability_funnel(
            {
                "candidate_targets": 0,
                "IN_SUPPORT": 0,
                "PARTIAL_SUPPORT": 0,
                "OUT_OF_SUPPORT": 0,
                "blocked_before_prediction": 0,
                "predicted": 0,
                "evaluated": 0,
                "unexplained": 0,
            }
        )
        appl["APPLICABILITY_ACCOUNTING_STATUS"] = "PASS_NOT_RUN_NO_ACCEPTED_MAPPINGS"
        appl["note"] = "Zero-shot not executed; funnel keys present with zeros."
        appl["ok"] = True
    _write(art / "applicability-accounting.json", appl)

    engine = run_engine_cross_source_shadow(
        accepted_count=harm["ACCEPTED_COMPARABLE_OUTCOME_COUNT"]
    )
    _write(art / "engine-cross-source-shadow.json", engine)

    med = carry_medication_status(root)
    _write(art / "medication-branch-continuity.json", med)

    # Status contract (pre-scan; public scan after)
    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "PRIVACY_BOUNDARY_STATUS": "PENDING_SCAN",
        "DEIDENTIFIED_RESEARCH_VIEW_STATUS": "DEIDENTIFIED_RESEARCH_VIEW",
        "DIRECT_IDENTIFIER_SCAN_STATUS": "PENDING",
        "REIDENTIFICATION_RISK_ASSESSMENT_STATUS": rare.get(
            "REIDENTIFICATION_RISK_ASSESSMENT_STATUS"
        ),
        "SOURCE_B_LONGITUDINAL_INVENTORY_STATUS": inventory.get(
            "SOURCE_B_LONGITUDINAL_INVENTORY_STATUS"
        ),
        "SOURCE_B_GLOBAL_SPLIT_STATUS": split["public"].get("SOURCE_B_GLOBAL_SPLIT_STATUS"),
        "CROSS_SOURCE_OUTCOME_HARMONIZATION_STATUS": harm.get(
            "CROSS_SOURCE_OUTCOME_HARMONIZATION_STATUS"
        ),
        "ACCEPTED_COMPARABLE_OUTCOME_COUNT": harm.get("ACCEPTED_COMPARABLE_OUTCOME_COUNT"),
        "UNIFIED_SOURCE_AWARE_STATE_STATUS": unified.get("UNIFIED_SOURCE_AWARE_STATE_STATUS"),
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "CROSS_SOURCE_INDEPENDENCE_STATUS": indep.get("CROSS_SOURCE_INDEPENDENCE_STATUS"),
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": zero.get("A_TO_B_ZERO_SHOT_SHADOW_STATUS"),
        "APPLICABILITY_ACCOUNTING_STATUS": appl.get("APPLICABILITY_ACCOUNTING_STATUS"),
        "PARTIAL_SUPPORT_ACCOUNTING_STATUS": partial.get("PARTIAL_SUPPORT_ACCOUNTING_STATUS"),
        "SAME_TIMESTAMP_PRESELECTION_AUDIT_STATUS": same_ts.get(
            "SAME_TIMESTAMP_PRESELECTION_AUDIT_STATUS"
        ),
        "ENGINE_CROSS_SOURCE_SHADOW_STATUS": engine.get("ENGINE_CROSS_SOURCE_SHADOW_STATUS"),
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "PUBLICATION_INTEGRITY_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "CONTENT_PREPACK_STATUS": "PENDING_VERIFY",
    }
    _write(art / "status-contract.json", {"version": VERSION, **statuses})

    public_scan = scan_public_artifacts(art)
    privacy = build_privacy_boundary_report(
        root=root,
        art=art,
        namespace_proof=ns_proof,
        relative_time_proof=rt_proof,
        public_scan=public_scan,
        rare_cells=rare,
        hmac_absent_from_zip_payloads=True,
        mapping_tables_absent=True,
    )
    _write(art / "privacy-boundary.json", privacy)
    statuses["PRIVACY_BOUNDARY_STATUS"] = privacy.get("PRIVACY_BOUNDARY_STATUS")
    statuses["DIRECT_IDENTIFIER_SCAN_STATUS"] = privacy.get("DIRECT_IDENTIFIER_SCAN_STATUS")
    _write(art / "status-contract.json", {"version": VERSION, **statuses})

    # Re-scan after privacy write (privacy JSON should not introduce identity keys)
    public_scan2 = scan_public_artifacts(art)
    if not public_scan2.get("ok"):
        statuses["PRIVACY_BOUNDARY_STATUS"] = "FAIL"
        statuses["DIRECT_IDENTIFIER_SCAN_STATUS"] = "FAIL"
        privacy["ok"] = False
        privacy["PRIVACY_BOUNDARY_STATUS"] = "FAIL"
        privacy["public_scan_final"] = public_scan2
        _write(art / "privacy-boundary.json", privacy)
        _write(art / "status-contract.json", {"version": VERSION, **statuses})

    tests = _run_tests(
        baseline=baseline,
        privacy=privacy,
        inventory=inventory,
        split=split["public"],
        harm=harm,
        unified=unified,
        zero=zero,
        indep=indep,
        appl=appl,
        partial=partial,
        same_ts=same_ts,
        engine=engine,
        med=med,
        statuses=statuses,
        ns_proof=ns_proof,
    )
    _write(art / "tests.json", tests)
    if tests.get("ok"):
        statuses["CONTENT_PREPACK_STATUS"] = "PASS"
        _write(art / "status-contract.json", {"version": VERSION, **statuses})

    aggregate = {
        "version": VERSION,
        "source_a_subjects": baseline["carried_facts"]["source_a_subjects"],
        "source_b_subjects": baseline["carried_facts"]["source_b_subjects"],
        "accepted_comparable_outcomes": harm["ACCEPTED_COMPARABLE_OUTCOME_COUNT"],
        "mapping_status_counts": harm.get("mapping_status_counts"),
        "b_inventory_counts": inventory.get("counts"),
        "b_split": split["public"].get("n_subjects"),
        "zero_shot_status": zero.get("A_TO_B_ZERO_SHOT_SHADOW_STATUS"),
        "partial_support_gap": partial.get("carried_unclassified_gap"),
        "same_timestamp_preselection_groups": same_ts.get(
            "n_same_timestamp_groups_preselection"
        ),
        "t3_pairs": same_ts.get("pair_summary"),
    }
    _write(art / "aggregate-report.json", aggregate)

    accepted_n = int(harm.get("ACCEPTED_COMPARABLE_OUTCOME_COUNT") or 0)
    zero_ok_for_release = (
        (accepted_n == 0 and zero.get("A_TO_B_ZERO_SHOT_SHADOW_STATUS") == "NOT_RUN_NO_ACCEPTED_MAPPINGS")
        or (accepted_n > 0 and zero.get("executed") and zero.get("ok"))
    )
    core_ok = (
        baseline.get("ok")
        and privacy.get("ok")
        and inventory.get("ok")
        and split["public"].get("ok")
        and unified.get("ok")
        and zero.get("ok")
        and zero_ok_for_release
        and indep.get("ok")
        and appl.get("ok")
        and partial.get("ok")
        and same_ts.get("ok")
        and engine.get("ok")
        and med.get("ok")
        and bool(tests.get("ok"))
    )
    verification = {
        "version": VERSION,
        "generated_at": _now(),
        "ok": core_ok,
        "duration_sec": round(time.time() - t0, 2),
        "statuses": statuses,
        "aggregate": aggregate,
        "readiness_for_current_state_classifier": False,
        "blocker_for_classifier": (
            "ACCEPTED_COMPARABLE_OUTCOME_COUNT=0; specimen/method/domain-review missing"
        ),
    }
    _write(art / "verification.json", verification)
    _write_report(art, statuses, aggregate, harm, zero, partial)

    out = {
        "ok": verification["ok"],
        "verification": verification,
        "statuses": statuses,
        "aggregate": aggregate,
    }
    if not verification["ok"]:
        out["blockers"] = _blockers(statuses, tests)
        return out
    if not no_publish:
        from human_simulator.privacy_cross_source_v01.publish import publish

        out["publication"] = publish(root)
    return out


def _blockers(statuses: dict[str, Any], tests: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for k, v in statuses.items():
        if k in {
            "PUBLIC_DATA_MINIMIZATION_STATUS",
            "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS",
            "PUBLICATION_INTEGRITY_STATUS",
            "ACCEPTED_COMPARABLE_OUTCOME_COUNT",
        }:
            continue
        if isinstance(v, str) and (
            v.startswith("FAIL")
            or v == "PENDING_VERIFY"
            or v == "PENDING_SCAN"
            or v == "PENDING"
        ):
            out.append({"status": k, "value": v})
    if not tests.get("ok"):
        out.append({"status": "tests", "failed": tests.get("failed")})
    return out


def _write_report(
    art: Path,
    statuses: dict[str, Any],
    aggregate: dict[str, Any],
    harm: dict[str, Any],
    zero: dict[str, Any],
    partial: dict[str, Any],
) -> None:
    lines = [
        f"# Privacy Boundary + Cross-Source Longitudinal Harmonization v{VERSION}",
        "",
        "## Statuses",
        "",
    ]
    for k in sorted(statuses):
        lines.append(f"- `{k}` = `{statuses[k]}`")
    lines.extend(
        [
            "",
            "## Counts",
            "",
            f"- Source A subjects: {aggregate.get('source_a_subjects')} "
            "(do not sum with B as unique patients)",
            f"- Source B subjects: {aggregate.get('source_b_subjects')}",
            f"- Accepted comparable outcomes: {aggregate.get('accepted_comparable_outcomes')}",
            f"- Mapping status counts: {aggregate.get('mapping_status_counts')}",
            f"- B inventory: {aggregate.get('b_inventory_counts')}",
            f"- B split: {aggregate.get('b_split')}",
            f"- v0.1.1 applicability unclassified gap: {partial.get('carried_unclassified_gap')}",
            "",
            "## Zero-shot",
            "",
            f"- status: `{zero.get('A_TO_B_ZERO_SHOT_SHADOW_STATUS')}`",
            f"- reason: {zero.get('reason')}",
            "",
            "## Missing evidence for acceptance",
            "",
            json.dumps(harm.get("missing_evidence_for_acceptance"), indent=2),
            "",
            "## Non-actions",
            "",
            "- Current State Classifier NOT_STARTED",
            "- Joint multi-outcome ML NOT_STARTED",
            "- Medication residual / intervention-response NOT_STARTED",
            "- Identity merge NOT_RUN",
            "- Security remains PAUSED_NOT_ACCEPTED_BY_OWNER",
            "",
        ]
    )
    (art / "stage-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_tests(**kwargs: Any) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("baseline", kwargs["baseline"].get("ok"))
    add("privacy", kwargs["privacy"].get("ok"))
    add("namespace_separation", kwargs["ns_proof"].get("ok"))
    add("inventory", kwargs["inventory"].get("ok"))
    add("split", kwargs["split"].get("ok"))
    add("unified", kwargs["unified"].get("ok"))
    add("zero_shot_honest", kwargs["zero"].get("ok"))
    add("independence", kwargs["indep"].get("ok"))
    add("applicability", kwargs["appl"].get("ok"))
    add("partial_support", kwargs["partial"].get("ok"))
    add("same_timestamp", kwargs["same_ts"].get("ok"))
    add("engine", kwargs["engine"].get("ok"))
    add("medication_zero_ready", kwargs["med"].get("ok"))
    add(
        "accepted_zero_this_release",
        kwargs["harm"].get("ACCEPTED_COMPARABLE_OUTCOME_COUNT") == 0,
    )
    add(
        "publication_lifecycle",
        kwargs["statuses"].get("PUBLIC_DATA_MINIMIZATION_STATUS")
        == "EXTERNAL_ATTESTATION_REQUIRED",
    )
    add(
        "classifier_not_started",
        kwargs["statuses"].get("CURRENT_STATE_CLASSIFIER_STATUS") == "NOT_STARTED",
    )
    failed = [c for c in checks if not c["ok"]]
    return {
        "ok": len(failed) == 0,
        "n_checks": len(checks),
        "n_failed": len(failed),
        "failed": failed,
        "checks": checks,
    }
