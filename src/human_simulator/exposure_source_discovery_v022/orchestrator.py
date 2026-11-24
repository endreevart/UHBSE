"""Run v0.2.2 decision ingestion. Does not write v0.1, v0.2, v0.2.1, or a review ZIP."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.db import QueryLog, connect_a, schema_fingerprint
from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v021.baseline import compare, hash_tree, snapshot
from human_simulator.exposure_source_discovery_v022 import evidence as source_a
from human_simulator.exposure_source_discovery_v022.contract import field_statuses, stage_statuses, violations
from human_simulator.exposure_source_discovery_v022.decisions import answer_record, build_decisions, validate_all
from human_simulator.exposure_source_discovery_v022.mutations import run_negative_controls
from human_simulator.exposure_source_discovery_v022.policy import (
    ANSWERS,
    ARTIFACT_DIR,
    DECISION_SCHEMA,
    REQUIRED_ARTIFACTS,
    V021_DIR,
    V021_SOURCE,
    V021_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.exposure_source_discovery_v022.report import render

A_TABLES = [
    ("magerya_api", "document_recommendation"),
    ("magerya_api", "document_recommendationtemplatecategory"),
    ("magerya_api", "diagnosis_recommendationcategory"),
    ("magerya_api", "diagnosis_medicines"),
    ("magerya_api", "diagnosis_medicineappointments"),
    ("magerya_api", "document_appointmentanalysisresult"),
    ("magerya_api", "django_content_type"),
    ("magerya_api", "document_analysis"),
    ("magerya_api", "document_analysisitem"),
]


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _manifest(art: Path) -> None:
    files = [
        {
            "path": path.relative_to(art).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in sorted(art.rglob("*"))
        if path.is_file() and path.name != "MANIFEST.json"
    ]
    _dump(art / "MANIFEST.json", {"version": VERSION, "files": files})


def _snapshot(root: Path) -> dict[str, Any]:
    return {**snapshot(root), "v021_artifacts": hash_tree(root, V021_DIR), "v021_source": hash_tree(root, V021_SOURCE)}


def _compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result = compare(before, after)
    v021_ok = (
        all(item.get("sha256") for item in before["v021_artifacts"])
        and before["v021_artifacts"] == after["v021_artifacts"]
        and before["v021_source"] == after["v021_source"]
    )
    result["V021_BASELINE_VERIFICATION_STATUS"] = "PASS" if v021_ok else "FAIL"
    result["writes_into_v021"] = False
    return result


def _baselines_pass(compared: dict[str, Any]) -> bool:
    return all(
        compared[key] == "PASS"
        for key in (
            "V01_BASELINE_VERIFICATION_STATUS",
            "V02_BASELINE_VERIFICATION_STATUS",
            "V021_BASELINE_VERIFICATION_STATUS",
            "STAGE05_BASELINE_VERIFICATION_STATUS",
        )
    )


def run(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    before = _snapshot(root)
    if before["stage05"]["STAGE05_BASELINE_VERIFICATION_STATUS"] != "PASS":
        _dump(art / "baseline-verification.json", _compare(before, _snapshot(root)))
        return {"ok": False, "stopped": True, "STAGE05_BASELINE_VERIFICATION_STATUS": "FAIL"}
    schema = json.loads((root / DECISION_SCHEMA).read_text(encoding="utf-8"))
    v021 = json.loads((root / V021_STATUS).read_text(encoding="utf-8"))

    record = answer_record(ANSWERS)
    decisions = build_decisions(record)
    validation = validate_all(decisions, record, schema)
    code = source_a.code_references()

    conn = connect_a(root)
    try:
        log = QueryLog(schema_fingerprint(conn, A_TABLES))
        evidence = source_a.collect(conn, log)
        entries = log.entries
    finally:
        conn.close()
    queries_ok = bool(entries) and all(item.get("success") and item.get("read_only_verified") for item in entries)

    fields = field_statuses(record, evidence, code)
    with tempfile.TemporaryDirectory(prefix="uhbse-v022-nc-") as tmp:
        controls = run_negative_controls(Path(tmp), schema)
    status: dict[str, Any] = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "DECISION_SCHEMA_VALIDATION_STATUS": validation["DECISION_SCHEMA_VALIDATION_STATUS"],
        "SOURCE_A_CODE_EVIDENCE_STATUS": code["SOURCE_A_CODE_EVIDENCE_STATUS"],
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "TECHNICAL_DISCOVERY_STATUS": "PENDING",
        "policy": policy_snapshot(),
        **stage_statuses(record, evidence, v021),
    }
    contract_violations = violations(status, decisions, record, fields)
    status["CONTRACT_VIOLATIONS"] = contract_violations
    technical = validation["ok"] and controls["ok"] and queries_ok and not contract_violations

    _dump(art / "owner-answer-record.json", {
        "version": VERSION,
        "automatic_contact": False,
        "reviewer_role": "system_architect",
        "answers": record,
    })
    _dump(art / "owner-decisions.json", {"version": VERSION, "schema": DECISION_SCHEMA, "responses": decisions})
    _dump(art / "decision-validation.json", validation)
    _dump(art / "source-a-code-and-catalog-evidence.json", {"code": code, "catalog": evidence})
    _dump(art / "field-semantic-status.json", {"version": VERSION, "fields": fields})
    _dump(art / "negative-control-results.json", controls)
    _dump(art / "query-log.json", {"version": VERSION, "queries": entries})

    after = _compare(before, _snapshot(root))
    technical = technical and _baselines_pass(after)
    status.update({
        key: after[key]
        for key in (
            "V01_BASELINE_VERIFICATION_STATUS",
            "V02_BASELINE_VERIFICATION_STATUS",
            "V021_BASELINE_VERIFICATION_STATUS",
            "STAGE05_BASELINE_VERIFICATION_STATUS",
        )
    })
    _dump(art / "baseline-verification.json", after)
    status["TECHNICAL_DISCOVERY_STATUS"] = "PASS" if technical else "FAIL"
    _dump(art / "status-contract.json", status)
    (art / "discovery-report.md").write_text(render(status, fields, evidence, validation), encoding="utf-8")

    scan = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    if not scan["ok"]:
        status["TECHNICAL_DISCOVERY_STATUS"] = "FAIL"
    _dump(art / "privacy-scan.json", scan)
    _dump(art / "status-contract.json", status)
    (art / "discovery-report.md").write_text(render(status, fields, evidence, validation), encoding="utf-8")

    missing = [n for n in REQUIRED_ARTIFACTS if n not in {"verification.json", "MANIFEST.json"} and not (art / n).is_file()]
    verification = {
        "ok": status["TECHNICAL_DISCOVERY_STATUS"] == "PASS" and scan["ok"] and not missing,
        "TECHNICAL_DISCOVERY_STATUS": status["TECHNICAL_DISCOVERY_STATUS"],
        "DECISION_SCHEMA_VALIDATION_STATUS": validation["DECISION_SCHEMA_VALIDATION_STATUS"],
        "PUBLIC_DATA_MINIMIZATION_STATUS": scan["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "queries_read_only": queries_ok,
        "contract_violations": contract_violations,
        "missing_artifacts": missing,
        "external_review_zip_created": False,
        **{k: status[k] for k in status if k.endswith("BASELINE_VERIFICATION_STATUS")},
    }
    _dump(art / "verification.json", verification)
    _manifest(art)
    final_scan = scan_public(art)
    if not final_scan["ok"]:
        verification["ok"] = False
        verification["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        _dump(art / "privacy-scan.json", final_scan)
        _dump(art / "verification.json", verification)
        _manifest(art)
    return {
        "ok": verification["ok"],
        "TECHNICAL_DISCOVERY_STATUS": status["TECHNICAL_DISCOVERY_STATUS"],
        "DECISION_SCHEMA_VALIDATION_STATUS": validation["DECISION_SCHEMA_VALIDATION_STATUS"],
        "PUBLIC_DATA_MINIMIZATION_STATUS": verification["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "decisions": validation["decision_count"],
        "identity": status["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"],
        "violations": contract_violations,
    }


if __name__ == "__main__":
    print(json.dumps(run(Path("."))))
