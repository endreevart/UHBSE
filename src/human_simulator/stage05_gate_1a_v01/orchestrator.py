"""Run Gate 1A from frozen v0.2.2 answers. Does not query a database or write earlier artifacts."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v021.baseline import compare, hash_tree, snapshot
from human_simulator.exposure_source_discovery_v022.policy import V021_DIR, V021_SOURCE
from human_simulator.stage05_gate_1a_v01.attest import (
    binding,
    build_records,
    load_answers,
    load_reviewer,
    outside_gate,
    validate_records,
)
from human_simulator.stage05_gate_1a_v01.contract import derive, violations
from human_simulator.stage05_gate_1a_v01.mutations import run_negative_controls
from human_simulator.stage05_gate_1a_v01.policy import (
    ANSWER_RECORD,
    ARTIFACT_DIR,
    DECISION_SCHEMA,
    OWNER_DECISIONS,
    REQUIRED_ARTIFACTS,
    V022_DIR,
    V022_SOURCE,
    VERSION,
    policy_snapshot,
)
from human_simulator.stage05_gate_1a_v01.report import render


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
    base = snapshot(root)
    base["v021_artifacts"] = hash_tree(root, V021_DIR)
    base["v021_source"] = hash_tree(root, V021_SOURCE)
    base["v022_artifacts"] = hash_tree(root, V022_DIR)
    base["v022_source"] = hash_tree(root, V022_SOURCE)
    return base


def _compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result = compare(before, after)

    def _unchanged(name: str) -> bool:
        return (
            all(item.get("sha256") for item in before[name + "_artifacts"])
            and before[name + "_artifacts"] == after[name + "_artifacts"]
            and before[name + "_source"] == after[name + "_source"]
        )

    result["V021_BASELINE_VERIFICATION_STATUS"] = "PASS" if _unchanged("v021") else "FAIL"
    result["V022_BASELINE_VERIFICATION_STATUS"] = "PASS" if _unchanged("v022") else "FAIL"
    result["writes_into_v022"] = False
    result["database_access"] = "NOT_PERFORMED"
    return result


def _baselines_pass(compared: dict[str, Any]) -> bool:
    return all(
        compared[key] == "PASS"
        for key in (
            "V01_BASELINE_VERIFICATION_STATUS",
            "V02_BASELINE_VERIFICATION_STATUS",
            "V021_BASELINE_VERIFICATION_STATUS",
            "V022_BASELINE_VERIFICATION_STATUS",
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

    answers = load_answers(root)
    reviewer = load_reviewer(root)
    evidence = binding(answers)
    evidence["answer_record_sha256"] = hashlib.sha256((root / ANSWER_RECORD).read_bytes()).hexdigest()
    evidence["owner_decisions_sha256"] = hashlib.sha256((root / OWNER_DECISIONS).read_bytes()).hexdigest()
    records = build_records(answers, reviewer)
    validation = validate_records(records, DECISION_SCHEMA)
    outside = outside_gate(answers)
    with tempfile.TemporaryDirectory(prefix="uhbse-gate1a-nc-") as tmp:
        controls = run_negative_controls(root, Path(tmp))

    status: dict[str, Any] = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "DECISION_SCHEMA_VALIDATION_STATUS": validation["DECISION_SCHEMA_VALIDATION_STATUS"],
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "GATE_1A_EXECUTION_STATUS": "PENDING",
        "database_access": "NOT_PERFORMED",
        "policy": policy_snapshot(),
        **derive(records),
    }
    contract_violations = violations(status, records, answers)
    execution = validation["ok"] and evidence["ok"] and controls["ok"] and not contract_violations

    _dump(art / "decision-record.schema.json", DECISION_SCHEMA)
    _dump(art / "decision-records.json", {"version": VERSION, "responses": records})
    _dump(art / "evidence-binding.json", evidence)
    _dump(art / "attestation-summary.json", {
        "version": VERSION,
        "accepted": [record["question_id"] for record in records if record["attestation"] == "accepted"],
        "insufficient": [record["question_id"] for record in records if record["attestation"] == "insufficient"],
        "rejected": [record["question_id"] for record in records if record["attestation"] == "rejected"],
        "outside_gate": outside,
    })
    _dump(art / "negative-control-results.json", controls)

    after = _compare(before, _snapshot(root))
    execution = execution and _baselines_pass(after)
    status.update({key: after[key] for key in after if key.endswith("BASELINE_VERIFICATION_STATUS")})
    status["CONTRACT_VIOLATIONS"] = contract_violations
    status["GATE_1A_EXECUTION_STATUS"] = "PASS" if execution else "FAIL"
    _dump(art / "baseline-verification.json", after)
    _dump(art / "status-contract.json", status)
    (art / "gate-1a-report.md").write_text(render(status, records, outside, validation), encoding="utf-8")

    scan = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    if not scan["ok"]:
        status["GATE_1A_EXECUTION_STATUS"] = "FAIL"
    _dump(art / "privacy-scan.json", scan)
    _dump(art / "status-contract.json", status)
    (art / "gate-1a-report.md").write_text(render(status, records, outside, validation), encoding="utf-8")

    missing = [name for name in REQUIRED_ARTIFACTS if name not in {"verification.json", "MANIFEST.json"} and not (art / name).is_file()]
    verification = {
        "ok": status["GATE_1A_EXECUTION_STATUS"] == "PASS" and scan["ok"] and not missing,
        "GATE_1A_EXECUTION_STATUS": status["GATE_1A_EXECUTION_STATUS"],
        "GATE_1A_ATTESTATION_STATUS": status["GATE_1A_ATTESTATION_STATUS"],
        "DECISION_SCHEMA_VALIDATION_STATUS": validation["DECISION_SCHEMA_VALIDATION_STATUS"],
        "PUBLIC_DATA_MINIMIZATION_STATUS": scan["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "contract_violations": contract_violations,
        "missing_artifacts": missing,
        "database_access": "NOT_PERFORMED",
        "external_review_zip_created": False,
        "model_training": False,
        **{key: status[key] for key in status if key.endswith("BASELINE_VERIFICATION_STATUS")},
    }
    _dump(art / "verification.json", verification)
    _manifest(art)
    final_scan = scan_public(art)
    if not final_scan["ok"]:
        verification["ok"] = False
        verification["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        status["GATE_1A_EXECUTION_STATUS"] = "FAIL"
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        _dump(art / "privacy-scan.json", final_scan)
        _dump(art / "status-contract.json", status)
        _dump(art / "verification.json", verification)
        _manifest(art)
    return {
        "ok": verification["ok"],
        "GATE_1A_EXECUTION_STATUS": status["GATE_1A_EXECUTION_STATUS"],
        "GATE_1A_ATTESTATION_STATUS": status["GATE_1A_ATTESTATION_STATUS"],
        "SOURCE_B_FEEDBACK_SEMANTICS_STATUS": status["SOURCE_B_FEEDBACK_SEMANTICS_STATUS"],
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS": status["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"],
        "PATIENT_REPORTED_INTAKE_TIER_STATUS": status["PATIENT_REPORTED_INTAKE_TIER_STATUS"],
        "INTERVENTION_RESPONSE_READINESS_STATUS": status["INTERVENTION_RESPONSE_READINESS_STATUS"],
        "eligible_cells": status["INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT"],
        "accepted": len([record for record in records if record["attestation"] == "accepted"]),
        "records": len(records),
        "violations": contract_violations,
    }


if __name__ == "__main__":
    print(json.dumps(run(Path("."))))
