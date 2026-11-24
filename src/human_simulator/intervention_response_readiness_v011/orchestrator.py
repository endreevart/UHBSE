"""Orchestrator — Stage 05 v0.1.1 provenance correction."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import verify_manifest, write_manifest
from human_simulator.intervention_response_readiness_v01.evaluate import (
    build_registry,
    confounding_inventory,
    consumption_decision,
    lanes_from_registry,
    source_readiness,
    summarize_gates,
    temporal_audit,
)
from human_simulator.intervention_response_readiness_v01.exposure import exposure_contract
from human_simulator.intervention_response_readiness_v01.mutations import run_negative_controls
from human_simulator.intervention_response_readiness_v01.privacy import scan_public
from human_simulator.intervention_response_readiness_v01.reconciliation import (
    assert_artifact_dir_reconciled,
    reconcile_final_report,
)
from human_simulator.intervention_response_readiness_v011.baseline import verify_baseline
from human_simulator.intervention_response_readiness_v011.defects import load_recorded_defect, reproduce_v01_defect
from human_simulator.intervention_response_readiness_v011.evidence import gaps_from_phase0, load_published_evidence
from human_simulator.intervention_response_readiness_v011.policy import (
    ARTIFACT_DIR,
    EVIDENCE_CATALOG,
    REQUIRED_ARTIFACTS,
    SECURITY_STAGE_STATUS,
    SOURCE_A,
    SOURCE_B,
    VERSION,
    V01_ZIP,
    policy_snapshot,
)
from human_simulator.intervention_response_readiness_v011.report import render_stage_report
from human_simulator.intervention_response_readiness_v011.snapshots import (
    SnapshotError,
    build_snapshots,
    manifest_path,
    verify_snapshots,
)

UNIT_TESTS = (
    "tests/test_intervention_response_readiness_v011_unit.py",
    "tests/test_intervention_response_readiness_v011_contracts.py",
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
    scan_path = art / "privacy-scan.json"
    if scan_path.is_file():
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
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


def _docs(root: Path, status: dict[str, Any], *, published: bool) -> None:
    phase = "PUBLISHED — security PAUSED" if published else "RUN COMPLETE — security PAUSED"
    sha_line = (
        "SHA-256: see sidecar after publish-v0.1.1"
        if not published
        else f"SHA-256: `{status.get('REVIEW_ZIP_SHA256') or 'see sidecar'}`"
    )
    current = f"""# Current stage

**Stage:** 05 — Intervention Response Readiness and Exposure Semantics v{VERSION}
**Phase:** {phase}
**Last updated:** {datetime.now(UTC).date().isoformat()}

## This stage

Point correction of v0.1 evidence provenance and clean-extraction replay.
Not a new scientific stage. Not model training.

`INTERVENTION_RESPONSE_READINESS_STATUS`={status.get("INTERVENTION_RESPONSE_READINESS_STATUS")}
`TECHNICAL_AUDIT_STATUS`={status.get("TECHNICAL_AUDIT_STATUS")}
`DOMAIN_ACCEPTED_MAPPING_COUNT`={status.get("DOMAIN_ACCEPTED_MAPPING_COUNT")}
`UPSTREAM_EVIDENCE_SNAPSHOT_STATUS`={status.get("UPSTREAM_EVIDENCE_SNAPSHOT_STATUS")}
`CORE_READINESS_REPLAY_STATUS`={status.get("CORE_READINESS_REPLAY_STATUS")}

{sha_line}

## Commands

```bash
audit --root . intervention-readiness run-v0.1 --no-publish
audit --root . intervention-readiness verify-v0.1.1
audit --root . intervention-readiness publish-v0.1.1
```

Stop after the v0.1.1 bundle. Do not start mapping acquisition, cohort construction,
or intervention-response training.
"""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "current-stage.md").write_text(current, encoding="utf-8")
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return
    text = agents.read_text(encoding="utf-8")
    start = text.find("## Current stage")
    end = text.find("## Required behavior")
    if start == -1 or end == -1:
        return
    block = f"""## Current stage

Current stage: **STAGE 05 — INTERVENTION RESPONSE READINESS AND EXPOSURE SEMANTICS v{VERSION}**
(Point correction of v0.1 evidence provenance. Not model training.)

```bash
audit --root . intervention-readiness run-v0.1 --no-publish
audit --root . intervention-readiness verify-v0.1.1
audit --root . intervention-readiness publish-v0.1.1
```

"""
    agents.write_text(text[:start] + block + text[end:], encoding="utf-8")


def _ensure_snapshots(root: Path) -> dict[str, Any]:
    if not manifest_path(root).is_file():
        try:
            build_snapshots(root)
        except SnapshotError as exc:
            return {
                "ok": False,
                "UPSTREAM_EVIDENCE_SNAPSHOT_STATUS": "FAIL",
                "problems": [{"key": "*", "reason": "SNAPSHOT_BUILD_FAILED", "detail": str(exc)}],
                "evidence_files_missing": [spec["canonical_source_path"] for spec in EVIDENCE_CATALOG],
                "snapshot_count": 0,
                "expected_count": 10,
            }
    return verify_snapshots(root)


def _defect(root: Path, art: Path) -> dict[str, Any]:
    if (root / "artifacts" / "external-review" / V01_ZIP).is_file():
        defect = reproduce_v01_defect(root)
        _dump(art / "v01-defect-reproduction.json", defect)
        return defect
    return load_recorded_defect(root)


def _run_unit_contract(root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    project_env = env.get("UV_PROJECT_ENVIRONMENT")
    if project_env and not Path(project_env).is_dir():
        env.pop("UV_PROJECT_ENVIRONMENT", None)
    proc = subprocess.run(
        ["uv", "run", "--frozen", "pytest", "-q", *UNIT_TESTS],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "output_tail": out[-4000:], "suites": list(UNIT_TESTS)}


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    snap = _ensure_snapshots(root)
    _dump(art / "upstream-evidence-verification.json", snap)
    evidence = load_published_evidence(root)
    phase0 = evidence["phase0"]
    gaps = gaps_from_phase0(phase0)
    _dump(art / "phase0-readiness-gaps.json", gaps)
    defect = _defect(root, art)
    baseline = verify_baseline(root)
    _dump(art / "baseline-verification.json", baseline)

    proven = bool(evidence.get("ok"))
    clean_tree = baseline.get("rehash_performed_this_run") is False and baseline.get("ok") is True
    core_status = "PASS" if clean_tree and proven else "NOT_RUN_AWAITING_CLEAN_EXTRACTION"
    if not proven:
        core_status = "NOT_RUN_EVIDENCE_NOT_VERIFIED"

    status: dict[str, Any] = {
        "version": VERSION,
        "Report status": "FINAL",
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "STAGE_NAMING_AUTHORITY_STATUS": (baseline.get("naming") or {}).get("STAGE_NAMING_AUTHORITY_STATUS"),
        "PRIOR_ZIP_PHYSICAL_REHASH_STATUS": baseline.get("PRIOR_ZIP_PHYSICAL_REHASH_STATUS"),
        "PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS": "NOT_RUN_PRIOR_BYTES_NOT_PACKED",
        "UPSTREAM_EVIDENCE_SNAPSHOT_STATUS": snap.get("UPSTREAM_EVIDENCE_SNAPSHOT_STATUS"),
        "V01_CORE_NEGATIVE_READINESS_STATUS": defect.get("V01_CORE_NEGATIVE_READINESS_STATUS"),
        "V01_UPSTREAM_EVIDENCE_PROVENANCE_STATUS": defect.get("V01_UPSTREAM_EVIDENCE_PROVENANCE_STATUS"),
        "V01_CLEAN_REPLAY_STATUS": defect.get("V01_CLEAN_REPLAY_STATUS"),
        "V01_SELF_CONTAINMENT_CLAIM_STATUS": defect.get("V01_SELF_CONTAINMENT_CLAIM_STATUS"),
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
        "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_PERFORMED",
        "HELD_OUT_REOPENED": False,
        "FROZEN_NHR_D0_LEP_MUTATED": False,
        "PUBLICATION_INTEGRITY_STATUS": "NOT_PACKED",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PENDING_CLEAN_REPLAY",
        "CORE_READINESS_REPLAY_STATUS": core_status,
        "CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS": core_status,
        "TECHNICAL_AUDIT_STATUS": "FAIL",
        "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
        "READINESS_CONCLUSION_STATUS": "PROVEN_NOT_READY" if proven else "NOT_PROVEN_BY_THIS_RUN",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "NEGATIVE_CONTROL_STATUS": "NOT_RUN_EVIDENCE_NOT_VERIFIED",
        "FINAL_REPORT_STATUS_RECONCILIATION_STATUS": "PENDING",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": phase0.get("DOMAIN_ACCEPTED_MAPPING_COUNT") if proven else "NOT_ESTABLISHED",
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": 0,
        "TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT": 0,
        "STATE_ENCODER_STATUS": phase0.get("STATE_ENCODER_STATUS"),
        "IROS_PROVIDER_COMMITMENT_STATUS": phase0.get("IROS_PROVIDER_COMMITMENT_STATUS"),
        "AUTOMATED_EXTERNAL_CONTACT_STATUS": phase0.get("AUTOMATED_EXTERNAL_CONTACT_STATUS"),
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": phase0.get("MEDICATION_RESIDUAL_FOUNDATION_STATUS"),
        "MEDICATION_RESIDUAL_CONSUMPTION_STATUS": "NOT_ESTABLISHED",
        "LIVE_ROW_RECOUNT_STATUS": "NOT_RUN_SOURCE_UNAVAILABLE",
        "EXPOSURE_SEMANTICS_GATE_STATUS": "NOT_ESTABLISHED",
        "INTERVENTION_EVIDENCE_REGISTRY_STATUS": "NOT_BUILT_EVIDENCE_NOT_VERIFIED",
        "SOURCE_A_INTERVENTION_READINESS_STATUS": "NOT_READY",
        "SOURCE_B_INTERVENTION_READINESS_STATUS": "NOT_READY",
    }

    if not proven:
        _dump(art / "status-contract.json", status)
        _dump(art / "exposure-semantics-contract.json", exposure_contract())
        _dump(art / "verification.json", {"ok": False, "TECHNICAL_AUDIT_STATUS": "FAIL", "reason": "EVIDENCE_NOT_VERIFIED"})
        _docs(root, status, published=False)
        return {
            "ok": False,
            "TECHNICAL_AUDIT_STATUS": "FAIL",
            "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
            "READINESS_CONCLUSION_STATUS": "NOT_PROVEN_BY_THIS_RUN",
            "artifact_dir": str(art),
            "no_publish": no_publish,
        }

    registry = build_registry(phase0)
    lanes = lanes_from_registry(registry)
    residual = consumption_decision(phase0)
    temporal = temporal_audit(phase0, registry)
    confounding = confounding_inventory(phase0)
    source_a = source_readiness(registry, SOURCE_A, phase0)
    source_b = source_readiness(registry, SOURCE_B, phase0)
    matrix = summarize_gates(registry)
    contract = exposure_contract()
    a_cells = [cell for cell in registry["cells"] if cell.get("source_system") == SOURCE_A and cell.get("inventory_only")]
    b_cells = [cell for cell in registry["cells"] if cell.get("source_system") == SOURCE_B]
    counts_ok = (
        registry.get("n_cells") == 49
        and len(a_cells) == 48
        and len(b_cells) == 1
        and registry.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and registry.get("DOMAIN_ACCEPTED_MAPPING_COUNT") == 0
        and lanes.get("INTERVENTION_RESPONSE_READINESS_STATUS") == "NOT_READY"
        and residual.get("MEDICATION_RESIDUAL_CONSUMPTION_STATUS") == "NOT_CONSUMED"
    )
    status.update(
        {
            "EXPOSURE_SEMANTICS_GATE_STATUS": "BUILT_NO_AUTO_PROMOTION",
            "INTERVENTION_EVIDENCE_REGISTRY_STATUS": registry.get("INTERVENTION_EVIDENCE_REGISTRY_STATUS"),
            "SOURCE_A_INTERVENTION_READINESS_STATUS": source_a.get("readiness_status"),
            "SOURCE_B_INTERVENTION_READINESS_STATUS": source_b.get("readiness_status"),
            "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
            "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": int(registry.get("CONFIRMED_ADMINISTRATION_MAPPING_COUNT") or 0),
            "TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT": int(registry.get("TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT") or 0),
            "ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT": int(registry.get("ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT") or 0),
            "ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT": int(
                registry.get("ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT") or 0
            ),
            "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
            "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
            "MEDICATION_RESIDUAL_CONSUMPTION_STATUS": residual.get("MEDICATION_RESIDUAL_CONSUMPTION_STATUS"),
            "REGISTRY_CELL_COUNT": registry.get("n_cells"),
            "SOURCE_A_INVENTORY_CELL_COUNT": len(a_cells),
            "SOURCE_B_ABSENCE_CELL_COUNT": len(b_cells),
        }
    )
    _dump(art / "exposure-semantics-contract.json", contract)
    _dump(art / "intervention-evidence-registry.json", registry)
    _dump(art / "candidate-cell-gate-matrix.json", matrix)
    _dump(art / "source-a-readiness.json", source_a)
    _dump(art / "source-b-readiness.json", source_b)
    _dump(art / "medication-residual-consumption-decision.json", residual)
    _dump(art / "temporal-eligibility-audit.json", temporal)
    _dump(art / "confounding-and-indication-bias-inventory.json", confounding)
    _dump(art / "policy-snapshot.json", policy_snapshot())
    _dump(art / "lane-summary.json", lanes)
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
    defect_ok = defect.get("measurement_ok") is True or (
        defect.get("executed") is True
        and defect.get("V01_CLEAN_REPLAY_STATUS") == "FAIL"
        and defect.get("V01_CORE_NEGATIVE_READINESS_STATUS") == "PASS"
    )
    # A clean extraction loads the publisher measurement record. measurement_ok stays true.
    if defect.get("executed") is not True:
        defect_ok = False
    technical_ok = all(
        (
            proven,
            counts_ok,
            nc.get("ok") is True and nc.get("n_rejected") == 11 and nc.get("n_cases") == 11,
            scan.get("ok") is True,
            recon.get("ok") is True,
            tests.get("ok") is True,
            baseline.get("ok") is True,
            snap.get("ok") is True,
            gaps.get("computed_from_published_artifacts") is True,
            gaps.get("handwritten_literals") is False,
            gaps.get("evidence_files_missing") == [],
            defect_ok,
            status.get("INTERVENTION_RESPONSE_READINESS_STATUS") == "NOT_READY",
            status.get("DOMAIN_ACCEPTED_MAPPING_COUNT") == 0,
        )
    )
    status["TECHNICAL_AUDIT_STATUS"] = "PASS" if technical_ok else "FAIL"
    if clean_tree and technical_ok:
        status["CORE_READINESS_REPLAY_STATUS"] = "PASS"
        status["CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS"] = "PASS"
    elif not clean_tree:
        status["CORE_READINESS_REPLAY_STATUS"] = "NOT_RUN_AWAITING_CLEAN_EXTRACTION"
        status["CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS"] = "NOT_RUN_AWAITING_CLEAN_EXTRACTION"
    status["PUBLICATION_INTEGRITY_STATUS"] = "NOT_PACKED"
    status["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "PENDING_CLEAN_REPLAY"
    _dump(art / "tests.json", tests)
    _dump(
        art / "tests-evidence.json",
        {"unit_contract": tests, "negative_controls": f"{nc.get('n_rejected')}/{nc.get('n_cases')}"},
    )
    _dump(
        art / "clean-replay-comparison.json",
        {
            "ok": None,
            "CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS": status["CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS"],
            "note": "Filled by publish after the clean-extraction audit replay.",
        },
    )
    persist_stage_report(art, status, report_status="FINAL")
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    recon = assert_artifact_dir_reconciled(art)
    _dump(art / "verification.json", {"ok": False, "note": "placeholder_before_final_verification"})
    write_manifest(art)
    missing = [name for name in REQUIRED_ARTIFACTS if not (art / name).is_file()]
    man = verify_manifest(art)
    verification = {
        "ok": bool(technical_ok and recon.get("ok") and man.get("ok") and not missing),
        "TECHNICAL_AUDIT_STATUS": status.get("TECHNICAL_AUDIT_STATUS"),
        "INTERVENTION_RESPONSE_READINESS_STATUS": status.get("INTERVENTION_RESPONSE_READINESS_STATUS"),
        "READINESS_CONCLUSION_STATUS": status.get("READINESS_CONCLUSION_STATUS"),
        "CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS": status.get("CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS"),
        "missing_required_artifacts": missing,
        "manifest": man,
        "reconciliation": recon.get("FINAL_REPORT_STATUS_RECONCILIATION_STATUS"),
        "registry_cells": registry.get("n_cells"),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    _dump(art / "verification.json", verification)
    write_manifest(art)
    _docs(root, status, published=False)
    return {
        "ok": verification["ok"],
        "TECHNICAL_AUDIT_STATUS": status.get("TECHNICAL_AUDIT_STATUS"),
        "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
        "READINESS_CONCLUSION_STATUS": status.get("READINESS_CONCLUSION_STATUS"),
        "artifact_dir": str(art),
        "no_publish": no_publish,
        "registry_cells": registry.get("n_cells"),
    }
