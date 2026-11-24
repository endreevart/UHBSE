"""Negative-control mutations. Each must fail the corresponding gate or scan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.intervention_response_readiness_v01.evaluate import build_registry, lanes_from_registry
from human_simulator.intervention_response_readiness_v01.privacy import scan_public
from human_simulator.intervention_response_readiness_v01.reconciliation import reconcile_final_report
from human_simulator.intervention_response_readiness_v01.report import render_stage_report, status_lines


def _fail_reasons(registry: dict[str, Any]) -> set[str]:
    reasons: set[str] = set()
    for cell in registry.get("cells") or []:
        for payload in (cell.get("gates") or {}).values():
            if payload.get("status") != "PASS":
                reasons.add(str(payload.get("reason") or ""))
    return reasons


def run_negative_controls(
    phase0: dict[str, Any],
    honest_status: dict[str, Any],
    *,
    tmp: Path | None = None,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: dict[str, Any]) -> None:
        cases.append({"id": name, "rejected": ok, "detail": detail})

    r1 = build_registry(phase0, mutations={"promote_candidate_mapping": True})
    add(
        "candidate_mapping_renamed_domain_accepted_without_evidence",
        r1.get("DOMAIN_ACCEPTED_MAPPING_COUNT") == 0
        and r1.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and any("CANDIDATE_RENAMED_DOMAIN_ACCEPTED_WITHOUT_EVIDENCE" in x for x in _fail_reasons(r1)),
        {"eligible": r1.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT")},
    )

    r2 = build_registry(phase0, mutations={"appointment_date_as_administration": True})
    add(
        "appointment_date_declared_administration_timestamp",
        r2.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and any("ADMINISTRATION" in x or "TECHNICAL_TIMESTAMP" in x for x in _fail_reasons(r2)),
        {"reasons_sample": sorted(_fail_reasons(r2))[:8]},
    )

    r3 = build_registry(phase0, mutations={"apply_source_a_mapping_to_b": True})
    add(
        "source_a_mapping_used_for_source_b",
        r3.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and any("SOURCE_A_MAPPING_TRANSFERRED_TO_SOURCE_B" in x for x in _fail_reasons(r3)),
        {"eligible": r3.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT")},
    )

    r4 = build_registry(phase0, mutations={"mutate_vocabulary": True})
    add(
        "source_identity_or_vocabulary_version_changed",
        r4.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and any("IDENTITY" in x or "VOCABULARY" in x for x in _fail_reasons(r4)),
        {"reasons_sample": sorted(_fail_reasons(r4))[:8]},
    )

    r5 = build_registry(phase0, mutations={"synthetic_dose_route_duration": True})
    add(
        "missing_dose_route_duration_replaced_with_synthetic_defaults",
        r5.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and any("SYNTHETIC" in x for x in _fail_reasons(r5)),
        {"eligible": r5.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT")},
    )

    r6 = build_registry(phase0, mutations={"future_in_pre_t0": True})
    add(
        "future_outcome_in_pre_t0_features",
        r6.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and any("FUTURE" in x for x in _fail_reasons(r6)),
        {"eligible": r6.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT")},
    )

    r7 = build_registry(phase0, mutations={"exposure_after_outcome": True})
    add(
        "exposure_timestamp_after_outcome",
        r7.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and any("EXPOSURE_TIMESTAMP_AFTER_OUTCOME" in x for x in _fail_reasons(r7)),
        {"eligible": r7.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT")},
    )

    r8 = build_registry(phase0, mutations={"patient_overlap": True})
    add(
        "patient_overlap_across_feasibility_partitions",
        r8.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and any("PATIENT_OVERLAP_ACROSS_SPLITS" in x for x in _fail_reasons(r8)),
        {"eligible": r8.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT")},
    )

    r9 = build_registry(phase0, mutations={"declare_recorded_as_treatment": True})
    lanes = lanes_from_registry(r9)
    add(
        "recorded_association_declared_treatment_response",
        r9.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and lanes.get("INTERVENTION_RESPONSE_READINESS_STATUS") != "READY"
        and any("RECORDED_ASSOCIATION_DECLARED_TREATMENT_RESPONSE" in x for x in _fail_reasons(r9)),
        {"readiness": lanes.get("INTERVENTION_RESPONSE_READINESS_STATUS")},
    )

    privacy_ok = False
    if tmp is not None:
        dirty = tmp / "privacy-mutation"
        dirty.mkdir(parents=True, exist_ok=True)
        (dirty / "leak.json").write_text(
            json.dumps({"patient_id": "P-NOT-A-REAL-ID", "rows": [{"patient_id": "P-NOT-A-REAL-ID"}]}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        scan = scan_public(dirty)
        privacy_ok = scan.get("PUBLIC_DATA_MINIMIZATION_STATUS") != "PASS_AGGREGATE_ONLY" and not scan.get("ok")
        add(
            "public_artifact_contains_patient_level_or_reversible_identifiers",
            privacy_ok,
            {"hits": (scan.get("hits") or [])[:5]},
        )
    else:
        add("public_artifact_contains_patient_level_or_reversible_identifiers", False, {"reason": "no tmp"})

    mutated_status = dict(honest_status)
    if "INTERVENTION_RESPONSE_READINESS_STATUS" in mutated_status:
        mutated_status["INTERVENTION_RESPONSE_READINESS_STATUS"] = "READY"
    report = render_stage_report(mutated_status, extra_sections=["## Mutation 11 injected divergence."])
    # Rebuild an honest report then flip one shared key by using mutated status in report only.
    honest_report = render_stage_report(honest_status)
    flipped = honest_report.replace(
        f"- `INTERVENTION_RESPONSE_READINESS_STATUS`={status_lines(honest_status).get('INTERVENTION_RESPONSE_READINESS_STATUS')}",
        "- `INTERVENTION_RESPONSE_READINESS_STATUS`=READY",
        1,
    )
    recon = reconcile_final_report(report_text=flipped, status=honest_status)
    add(
        "stage_report_and_status_contract_diverge_on_common_key",
        recon.get("ok") is False
        and recon.get("comparison_mode") == "ALL_COMMON_UPPERCASE_STATUS_KEYS"
        and any(m.get("key") == "INTERVENTION_RESPONSE_READINESS_STATUS" for m in recon.get("mismatches") or []),
        {
            "compared_key_count": recon.get("compared_key_count"),
            "mismatch_keys": [m.get("key") for m in recon.get("mismatches") or []],
        },
    )

    rejected = all(c["rejected"] for c in cases)
    return {
        "ok": rejected,
        "NEGATIVE_CONTROL_STATUS": "PASS" if rejected else "FAIL",
        "n_cases": len(cases),
        "n_rejected": sum(1 for c in cases if c["rejected"]),
        "cases": cases,
        "mutation_render_bytes": len(report.encode("utf-8")),
    }
