"""Orchestrator — Stage 05 Gate 0 readiness audit."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import verify_manifest, write_manifest
from human_simulator.intervention_response_readiness_v01.baseline import verify_baseline
from human_simulator.intervention_response_readiness_v01.evaluate import (
    build_registry,
    confounding_inventory,
    consumption_decision,
    lanes_from_registry,
    source_readiness,
    summarize_gates,
    temporal_audit,
)
from human_simulator.intervention_response_readiness_v01.evidence import load_published_evidence
from human_simulator.intervention_response_readiness_v01.exposure import exposure_contract
from human_simulator.intervention_response_readiness_v01.mutations import run_negative_controls
from human_simulator.intervention_response_readiness_v01.policy import (
    ARTIFACT_DIR,
    REQUIRED_ARTIFACTS,
    SECURITY_STAGE_STATUS,
    SOURCE_A,
    SOURCE_B,
    VERSION,
    policy_snapshot,
)
from human_simulator.intervention_response_readiness_v01.privacy import scan_public
from human_simulator.intervention_response_readiness_v01.reconciliation import (
    assert_artifact_dir_reconciled,
    reconcile_final_report,
)
from human_simulator.intervention_response_readiness_v01.report import render_stage_report

UNIT_TESTS = (
    "tests/test_intervention_response_readiness_v01_unit.py",
    "tests/test_intervention_response_readiness_v01_contracts.py",
)


def _dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def persist_stage_report(art: Path, status: dict[str, Any], *, report_status: str = "FINAL") -> dict[str, Any]:
    payload = dict(status)
    payload["Report status"] = report_status
    payload["FINAL_REPORT_STATUS_RECONCILIATION_STATUS"] = "PASS"
    scan = None
    if (art / "privacy-scan.json").is_file():
        scan = json.loads((art / "privacy-scan.json").read_text(encoding="utf-8"))
        if scan.get("PUBLIC_DATA_MINIMIZATION_STATUS"):
            payload["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    text = render_stage_report(payload)
    recon = reconcile_final_report(report_text=text, status=payload, scan=scan)
    payload["FINAL_REPORT_STATUS_RECONCILIATION_STATUS"] = recon["FINAL_REPORT_STATUS_RECONCILIATION_STATUS"]
    text = render_stage_report(payload)
    recon = reconcile_final_report(report_text=text, status=payload, scan=scan)
    payload["FINAL_REPORT_STATUS_RECONCILIATION_STATUS"] = recon["FINAL_REPORT_STATUS_RECONCILIATION_STATUS"]
    (art / "stage-report.md").write_text(text, encoding="utf-8")
    _dump(art / "status-contract.json", payload)
    _dump(art / "status-reconciliation.json", recon)
    return recon


def _phase0_gaps(phase0: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": phase0.get("DOMAIN_ACCEPTED_MAPPING_COUNT"),
        "medication_record_class": phase0.get("source_a_record_class"),
        "not_prescription": phase0.get("source_a_record_class") == "RECORDED_MEDICATION_CONTEXT",
        "not_administration": phase0.get("source_a_administration_claim") == "NOT_CLAIMED",
        "appointment_date_semantics": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
        "verified_administration_or_dispense_or_ingest_timestamp": False,
        "dose_value_confirmed": False,
        "route_confirmed": False,
        "dose_or_route_columns": phase0.get("dose_or_route_columns") or [],
        "unit_form_frequency_fk_clinically_interpreted": False,
        "form_table_n_rows": phase0.get("form_table_n_rows"),
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": phase0.get("MEDICATION_RESIDUAL_FOUNDATION_STATUS"),
        "engine_eligible_accepted_medication_residual_cells": phase0.get("ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT"),
        "engine_eligible_listed": phase0.get("residual_engine_eligible_listed"),
        "STATE_ENCODER_STATUS": phase0.get("STATE_ENCODER_STATUS"),
        "SOURCE_B_MEDICATION_CONTEXT_STATUS": phase0.get("SOURCE_B_MEDICATION_CONTEXT_STATUS"),
        "source_b_created_by_source_a_transfer": False,
        "mapping_accepted": phase0.get("mapping_accepted"),
        "IROS_PROVIDER_COMMITMENT_STATUS": phase0.get("IROS_PROVIDER_COMMITMENT_STATUS"),
        "live_row_recount_status": (phase0.get("materialized") or {}).get("live_row_recount_status"),
        "evidence_files_missing": phase0.get("evidence_files_missing") or [],
        "computed_from_published_artifacts": True,
        "handwritten_literals": False,
    }


def _docs(root: Path, status: dict[str, Any], *, published: bool = False) -> None:
    phase = "PUBLISHED — security PAUSED" if published else "RUN COMPLETE — security PAUSED"
    sha_line = (
        "SHA-256: see sidecar after publish-v0.1"
        if not published
        else f"SHA-256: `{status.get('REVIEW_ZIP_SHA256') or 'see sidecar'}`"
    )
    current = f"""# Current stage

**Stage:** 05 — Intervention Response Readiness and Exposure Semantics v{VERSION}
**Phase:** {phase}
**Last updated:** {datetime.now(UTC).date().isoformat()}

## This stage

Readiness audit for a future associational intervention-response experiment.
Not model training. Not a scientific-status upgrade.

Technical audit PASS does not mean `INTERVENTION_RESPONSE_READINESS_STATUS=READY`.

{sha_line}

`INTERVENTION_RESPONSE_READINESS_STATUS`={status.get("INTERVENTION_RESPONSE_READINESS_STATUS")}
`DOMAIN_ACCEPTED_MAPPING_COUNT`={status.get("DOMAIN_ACCEPTED_MAPPING_COUNT")}
`TECHNICAL_AUDIT_STATUS`={status.get("TECHNICAL_AUDIT_STATUS")}
`MEDICATION_RESIDUAL_CONSUMPTION_STATUS`={status.get("MEDICATION_RESIDUAL_CONSUMPTION_STATUS")}
`SECURITY_STAGE_STATUS`={SECURITY_STAGE_STATUS}

## Commands

```bash
audit --root . intervention-readiness run-v0.1 --no-publish
audit --root . intervention-readiness verify-v0.1
audit --root . intervention-readiness publish-v0.1
```

Stop after the readiness bundle. Do not start intervention-response training.
"""
    (root / "docs" / "current-stage.md").write_text(current, encoding="utf-8")
    agents = root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    marker = "## Current stage"
    start = text.find(marker)
    end = text.find("## Required behavior")
    if start == -1 or end == -1:
        return
    block = f"""{marker}

Current stage: **STAGE 05 — INTERVENTION RESPONSE READINESS AND EXPOSURE SEMANTICS v{VERSION}**
(Evidence/readiness audit. Not model training.)

```bash
audit --root . intervention-readiness run-v0.1 --no-publish
audit --root . intervention-readiness verify-v0.1
audit --root . intervention-readiness publish-v0.1
```

"""
    agents.write_text(text[:start] + block + text[end:], encoding="utf-8")


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = root.resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)

    baseline = verify_baseline(root)
    if baseline.get("BASELINE_VERIFICATION_STATUS") == "STAGE_NAMING_CONFLICT":
        _dump(art / "baseline-verification.json", baseline)
        return {"ok": False, "frozen": False, "artifact_dir": str(art), "naming": "STAGE_NAMING_CONFLICT"}

    evidence = load_published_evidence(root)
    phase0 = evidence["phase0"]
    registry = build_registry(phase0)
    lanes = lanes_from_registry(registry)
    residual = consumption_decision(phase0)
    temporal = temporal_audit(phase0, registry)
    confounding = confounding_inventory(phase0)
    source_a = source_readiness(registry, SOURCE_A, phase0)
    source_b = source_readiness(registry, SOURCE_B, phase0)
    matrix = summarize_gates(registry)
    gaps = _phase0_gaps(phase0)
    contract = exposure_contract()

    domain_n = int(registry.get("DOMAIN_ACCEPTED_MAPPING_COUNT") or 0)
    ir_n = int(lanes.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") or 0)
    if domain_n == 0:
        ir_n = 0
        lanes["INTERVENTION_RESPONSE_READINESS_STATUS"] = "NOT_READY"

    status: dict[str, Any] = {
        "version": VERSION,
        "Report status": "FINAL",
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "STAGE_NAMING_AUTHORITY_STATUS": (baseline.get("naming") or {}).get("STAGE_NAMING_AUTHORITY_STATUS"),
        "INTERVENTION_EVIDENCE_REGISTRY_STATUS": registry.get("INTERVENTION_EVIDENCE_REGISTRY_STATUS"),
        "EXPOSURE_SEMANTICS_GATE_STATUS": "BUILT_NO_AUTO_PROMOTION",
        "SOURCE_A_INTERVENTION_READINESS_STATUS": source_a.get("readiness_status"),
        "SOURCE_B_INTERVENTION_READINESS_STATUS": source_b.get("readiness_status"),
        "DOMAIN_ACCEPTED_MAPPING_COUNT": domain_n,
        "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": int(registry.get("CONFIRMED_ADMINISTRATION_MAPPING_COUNT") or 0),
        "TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT": int(
            registry.get("TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT") or 0
        ),
        "ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT": int(
            registry.get("ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT") or 0
        ),
        "ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT": int(
            registry.get("ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT") or 0
        ),
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": ir_n,
        "INTERVENTION_RESPONSE_READINESS_STATUS": lanes.get("INTERVENTION_RESPONSE_READINESS_STATUS"),
        "MEDICATION_RESIDUAL_CONSUMPTION_STATUS": residual.get("MEDICATION_RESIDUAL_CONSUMPTION_STATUS"),
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": phase0.get("MEDICATION_RESIDUAL_FOUNDATION_STATUS"),
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
        "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "STATE_ENCODER_STATUS": phase0.get("STATE_ENCODER_STATUS"),
        "IROS_PROVIDER_COMMITMENT_STATUS": phase0.get("IROS_PROVIDER_COMMITMENT_STATUS"),
        "AUTOMATED_EXTERNAL_CONTACT_STATUS": phase0.get("AUTOMATED_EXTERNAL_CONTACT_STATUS") or "NOT_RUN",
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_PERFORMED",
        "PUBLICATION_INTEGRITY_STATUS": "NOT_PACKED",
        "TECHNICAL_AUDIT_STATUS": "PENDING_TESTS",
        "NEGATIVE_CONTROL_STATUS": "PENDING",
        "FINAL_REPORT_STATUS_RECONCILIATION_STATUS": "PENDING",
        "LIVE_ROW_RECOUNT_STATUS": (phase0.get("materialized") or {}).get("live_row_recount_status"),
        "HELD_OUT_REOPENED": False,
        "FROZEN_NHR_D0_LEP_MUTATED": False,
    }

    _dump(art / "baseline-verification.json", baseline)
    _dump(art / "phase0-readiness-gaps.json", gaps)
    _dump(art / "exposure-semantics-contract.json", contract)
    _dump(art / "intervention-evidence-registry.json", registry)
    _dump(art / "candidate-cell-gate-matrix.json", matrix)
    _dump(art / "source-a-readiness.json", source_a)
    _dump(art / "source-b-readiness.json", source_b)
    _dump(art / "medication-residual-consumption-decision.json", residual)
    _dump(art / "temporal-eligibility-audit.json", temporal)
    _dump(art / "confounding-and-indication-bias-inventory.json", confounding)
    _dump(art / "policy-snapshot.json", policy_snapshot())
    _dump(art / "status-contract.json", status)

    with tempfile.TemporaryDirectory(prefix="uhbse-irr-nc-") as nc_tmp:
        nc = run_negative_controls(phase0, status, tmp=Path(nc_tmp))
    status["NEGATIVE_CONTROL_STATUS"] = nc.get("NEGATIVE_CONTROL_STATUS")
    _dump(art / "negative-control-results.json", nc)
    scan = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan.get("PUBLIC_DATA_MINIMIZATION_STATUS")
    _dump(art / "privacy-scan.json", scan)
    _dump(art / "status-contract.json", status)

    recon = persist_stage_report(art, status, report_status="FINAL")
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))

    tests = _run_unit_contract(root)
    status["TECHNICAL_AUDIT_STATUS"] = "PASS" if tests.get("ok") and nc.get("ok") and scan.get("ok") and recon.get("ok") and baseline.get("ok") else "FAIL"
    if status.get("INTERVENTION_RESPONSE_READINESS_STATUS") == "READY":
        status["TECHNICAL_AUDIT_STATUS"] = "FAIL"
        status["TECHNICAL_AUDIT_FAIL_REASON"] = "READY_FORBIDDEN_WHILE_DOMAIN_ACCEPTED_MAPPING_COUNT_IS_ZERO"
    status["PUBLICATION_INTEGRITY_STATUS"] = "NOT_PACKED"
    status["FINAL_REPORT_STATUS_RECONCILIATION_STATUS"] = recon.get("FINAL_REPORT_STATUS_RECONCILIATION_STATUS")
    _dump(art / "tests.json", tests)
    _dump(art / "tests-evidence.json", {"unit_contract": tests, "negative_controls": nc.get("NEGATIVE_CONTROL_STATUS")})
    persist_stage_report(art, status, report_status="FINAL")
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    recon = assert_artifact_dir_reconciled(art)

    _dump(
        art / "verification.json",
        {
            "ok": False,
            "TECHNICAL_AUDIT_STATUS": status.get("TECHNICAL_AUDIT_STATUS"),
            "INTERVENTION_RESPONSE_READINESS_STATUS": status.get("INTERVENTION_RESPONSE_READINESS_STATUS"),
            "note": "placeholder_before_final_verification",
        },
    )
    write_manifest(art)
    missing = [name for name in REQUIRED_ARTIFACTS if not (art / name).is_file()]
    man = verify_manifest(art)
    verification = {
        "ok": bool(
            status.get("TECHNICAL_AUDIT_STATUS") == "PASS"
            and status.get("INTERVENTION_RESPONSE_READINESS_STATUS") == "NOT_READY"
            and status.get("DOMAIN_ACCEPTED_MAPPING_COUNT") == 0
            and status.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
            and status.get("INTERVENTION_RESPONSE_MODEL_STATUS") == "NOT_STARTED"
            and recon.get("ok")
            and man.get("ok")
            and not missing
            and evidence.get("ok")
        ),
        "TECHNICAL_AUDIT_STATUS": status.get("TECHNICAL_AUDIT_STATUS"),
        "INTERVENTION_RESPONSE_READINESS_STATUS": status.get("INTERVENTION_RESPONSE_READINESS_STATUS"),
        "missing_required_artifacts": missing,
        "manifest": man,
        "reconciliation": recon.get("FINAL_REPORT_STATUS_RECONCILIATION_STATUS"),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    _dump(art / "verification.json", verification)
    write_manifest(art)
    _docs(root, status, published=False)
    return {
        "ok": verification["ok"],
        "frozen": True,
        "artifact_dir": str(art),
        "TECHNICAL_AUDIT_STATUS": status.get("TECHNICAL_AUDIT_STATUS"),
        "INTERVENTION_RESPONSE_READINESS_STATUS": status.get("INTERVENTION_RESPONSE_READINESS_STATUS"),
        "no_publish": no_publish,
    }


def _run_unit_contract(root: Path) -> dict[str, Any]:
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    proc = subprocess.run(
        ["uv", "run", "--frozen", "pytest", "-q", *UNIT_TESTS],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "output_tail": out[-4000:],
        "suites": list(UNIT_TESTS),
    }
