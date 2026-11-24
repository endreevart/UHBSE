"""Record the owner attestation. Writes only its own artifact directory."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v021.baseline import sha256_file, stage05_status
from human_simulator.stage05_gate1a_owner_attestation_v01.policy import (
    ANSWER_RECORD,
    ARTIFACT_DIR,
    COMPLETION_RECORDS,
    EXPECTED_ANSWER_RECORD_SHA,
    EXPECTED_COMPLETION_SHA,
    EXPECTED_DECISION_RECORDS_SHA,
    PRIOR_RECORDS,
    SCIENTIFIC_CEILING,
    VERSION,
    policy_snapshot,
)
from human_simulator.stage05_gate1a_owner_attestation_v01.records import build_records
from human_simulator.stage05_gate1a_owner_attestation_v01.report import render

_FROZEN = {
    PRIOR_RECORDS: EXPECTED_DECISION_RECORDS_SHA,
    COMPLETION_RECORDS: EXPECTED_COMPLETION_SHA,
    ANSWER_RECORD: EXPECTED_ANSWER_RECORD_SHA,
}


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _pins(root: Path) -> dict[str, Any]:
    files = []
    ok = True
    for relative, expected in _FROZEN.items():
        actual = sha256_file(root / relative)
        accepted = actual == expected
        ok = ok and accepted
        files.append({"path": relative, "expected_sha256": expected, "actual_sha256": actual, "accepted": accepted})
    return {"ok": ok, "files": files}


def run(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    before = _pins(root)
    stage05 = stage05_status(root)
    if not before["ok"] or stage05["STAGE05_BASELINE_VERIFICATION_STATUS"] != "PASS":
        return {"ok": False, "reason": "FROZEN_PIN"}
    prior = json.loads((root / PRIOR_RECORDS).read_text(encoding="utf-8"))["responses"]
    records = build_records(prior)
    closed = {record["question_id"]: record["closes_question"] for record in records}
    blockers = ("B_IDENTITY", "B_DRUGS", "B_VITAMINS", "B_CHANGE", "B_DECLINE", "B_SHORT")
    route_open = all(closed[question_id] for question_id in blockers)
    status: dict[str, Any] = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "GATE_1A_OWNER_ATTESTATION_STATUS": "PASS" if route_open else "FAIL",
        "GATE_1A_STATUS": "SOURCE_B_ROUTE_ACCEPTED_SOURCE_A_OPEN" if route_open else "PARTIALLY_ATTESTED_OPEN",
        "GATE_1A_SOURCE_B_EXPOSURE_ROUTE_STATUS": "PASS" if route_open else "BLOCKED",
        "GATE_1B_STATUS": "READY_FOR_EXPLICIT_OWNER_OPENING" if route_open else "BLOCKED",
        "GATE_1B_STARTED": False,
        "B_POSITIVE": "DEFERRED_NOT_A_RESPONSE_LABEL",
        "B_TIMING_ROW_LEVEL_ASSIGNMENT_COUNT": 0,
        "B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT": 0,
        "medication_extractor": False,
        "model_training": False,
        "SOURCE_A_OPEN": ["A_RECOMMENDATION_ITEMS", "A_MEDICATION_CODE_SET", "A_DOCUMENT_FINAL"],
        "policy": policy_snapshot(),
        **SCIENTIFIC_CEILING,
    }
    _dump(art / "superseding-decision-records.json", {"version": VERSION, "responses": records})
    _dump(art / "status-contract.json", status)
    (art / "gate-1a-owner-attestation-report.md").write_text(render(status), encoding="utf-8")
    after = _pins(root)
    _dump(art / "baseline-verification.json", {"ok": before == after and after["ok"], "pins": after, "stage05": stage05["STAGE05_BASELINE_VERIFICATION_STATUS"]})
    scan = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    if not scan["ok"] or not after["ok"]:
        status["GATE_1A_OWNER_ATTESTATION_STATUS"] = "FAIL"
    _dump(art / "privacy-scan.json", scan)
    _dump(art / "status-contract.json", status)
    (art / "gate-1a-owner-attestation-report.md").write_text(render(status), encoding="utf-8")
    report = (art / "gate-1a-owner-attestation-report.md").read_text(encoding="utf-8")
    verification = {
        "ok": status["GATE_1A_OWNER_ATTESTATION_STATUS"] == "PASS" and f"`GATE_1B_STATUS`={status['GATE_1B_STATUS']}" in report,
        "GATE_1A_STATUS": status["GATE_1A_STATUS"],
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "GATE_1B_STARTED": False,
        "new_records": len(records),
        "frozen_records_changed": not after["ok"],
    }
    _dump(art / "verification.json", verification)
    files = [
        {"bytes": path.stat().st_size, "path": path.relative_to(art).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(art.rglob("*"))
        if path.is_file() and path.name != "MANIFEST.json"
    ]
    _dump(art / "MANIFEST.json", {"files": files, "version": VERSION})
    return {
        "ok": verification["ok"],
        "GATE_1A_STATUS": status["GATE_1A_STATUS"],
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "records": len(records),
    }


if __name__ == "__main__":
    print(json.dumps(run(Path("."))))
