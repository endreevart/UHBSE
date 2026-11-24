"""Open Gate 1B and run the candidate extractor. Writes only its own directory."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.db import QueryLog, connect_b, schema_fingerprint
from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v021.baseline import sha256_file, stage05_status
from human_simulator.stage05_gate1a_owner_attestation_v01.records import reviewer_digest
from human_simulator.stage05_gate1b_extractor_pilot_v01.controls import controls_pass, run_controls
from human_simulator.stage05_gate1b_extractor_pilot_v01.extract import accumulate
from human_simulator.stage05_gate1b_extractor_pilot_v01.policy import (
    ARTIFACT_DIR,
    FIELDS,
    FROZEN,
    OPENED_AT,
    OPENING_INSTRUCTION,
    SCIENTIFIC_CEILING,
    VERSION,
    policy_snapshot,
)
from human_simulator.stage05_gate1b_extractor_pilot_v01.report import render

_SQL = "SELECT drugs, vitamins, change_drugs, decline_drugs, drugs_first FROM public.feedback"
_COLUMNS = """
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'feedback'
  AND column_name IN ('drugs', 'vitamins', 'change_drugs', 'decline_drugs', 'drugs_first')
ORDER BY column_name
"""


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _pins(root: Path) -> dict[str, Any]:
    files = []
    ok = True
    for relative, expected in FROZEN.items():
        actual = sha256_file(root / relative)
        accepted = actual == expected
        ok = ok and accepted
        files.append({"path": relative, "expected_sha256": expected, "actual_sha256": actual, "accepted": accepted})
    return {"ok": ok, "files": files}


def _stream(conn: Any, log: QueryLog) -> dict[str, Any]:
    columns = log.run(conn, "b_feedback_extract_columns", "kgz_raw", _COLUMNS)
    if len(columns) != len(FIELDS):
        raise RuntimeError("COLUMN_SET")
    started = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    clock = time.monotonic()
    seen = 0

    def _rows() -> Any:
        nonlocal seen
        with conn.cursor(name="b_gate1b_extract") as cur:
            cur.itersize = 5000
            cur.execute(_SQL)
            for row in cur:
                seen += 1
                yield row

    summary = accumulate(_rows())
    conn.commit()
    log.note_stream("b_feedback_extract_stream", "kgz_raw", _SQL, seen, started, clock)
    return summary


def run(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    before = _pins(root)
    stage05 = stage05_status(root)
    status: dict[str, Any] = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "GATE_1B_STATUS": "OPEN",
        "GATE_1B_PILOT_STATUS": "NOT_EXECUTED",
        "GATE_1B_ACCEPTED": False,
        "PRECISION_RECALL_STATUS": "NOT_MEASURED",
        "PRIVATE_LABEL_SET_STATUS": "ABSENT",
        "GATE_2_STATUS": "CLOSED",
        "GATE_3_STATUS": "CLOSED",
        "B_POSITIVE": "DEFERRED_NOT_EXTRACTED",
        "SOURCE_A_OPEN": ["A_RECOMMENDATION_ITEMS", "A_MEDICATION_CODE_SET", "A_DOCUMENT_FINAL"],
        "stream_error_class": None,
        "policy": policy_snapshot(),
        **SCIENTIFIC_CEILING,
    }
    controls = run_controls(status)
    if not before["ok"] or stage05["STAGE05_BASELINE_VERIFICATION_STATUS"] != "PASS" or not controls_pass(controls):
        return {"ok": False, "reason": "FROZEN_PIN_OR_CONTROL"}
    log = QueryLog("gate1b")
    summary: dict[str, Any] | None = None
    error_class = None
    try:
        conn = connect_b(root)
        try:
            log.schema_fingerprint = schema_fingerprint(conn, [("public", "feedback")])
            summary = _stream(conn, log)
        finally:
            conn.close()
    except Exception as exc:
        error_class = type(exc).__name__
    pilot = "EXECUTED_PRECISION_RECALL_NOT_MEASURED" if summary and summary["rows"] > 0 else "NOT_EXECUTED"
    status["GATE_1B_PILOT_STATUS"] = pilot
    status["stream_error_class"] = error_class
    opening = {
        "gate": "GATE_1B",
        "decision": "OPENED",
        "instruction": OPENING_INSTRUCTION,
        "decided_at": OPENED_AT,
        "role": "system_architect",
        "reviewer_digest": reviewer_digest(),
        "precision_recall_authorized": False,
        "model_training_authorized": False,
    }
    _dump(art / "gate-opening.json", opening)
    _dump(art / "negative-control-results.json", {"cases": controls, "passed": controls_pass(controls)})
    _dump(art / "extraction-summary.json", summary or {"rows": 0, "source_text_retained": False})
    _dump(art / "query-log.json", {"entries": log.entries})
    after = _pins(root)
    _dump(art / "baseline-verification.json", {
        "ok": before == after and after["ok"] and stage05["STAGE05_BASELINE_VERIFICATION_STATUS"] == "PASS",
        "pins": after,
        "stage05": stage05["STAGE05_BASELINE_VERIFICATION_STATUS"],
    })
    if not after["ok"] or pilot != "EXECUTED_PRECISION_RECALL_NOT_MEASURED":
        status["GATE_1B_PILOT_STATUS"] = "FAIL" if pilot == "EXECUTED_PRECISION_RECALL_NOT_MEASURED" else pilot
    _dump(art / "status-contract.json", status)
    (art / "gate-1b-extractor-pilot-report.md").write_text(render(status), encoding="utf-8")
    scan = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    if not scan["ok"]:
        status["GATE_1B_PILOT_STATUS"] = "FAIL"
    _dump(art / "status-contract.json", status)
    (art / "gate-1b-extractor-pilot-report.md").write_text(render(status), encoding="utf-8")
    scan = scan_public(art)
    if not scan["ok"]:
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        status["GATE_1B_PILOT_STATUS"] = "FAIL"
        _dump(art / "status-contract.json", status)
        (art / "gate-1b-extractor-pilot-report.md").write_text(render(status), encoding="utf-8")
    _dump(art / "privacy-scan.json", scan)
    verification = {
        "ok": status["GATE_1B_STATUS"] == "OPEN"
        and status["GATE_1B_PILOT_STATUS"] == "EXECUTED_PRECISION_RECALL_NOT_MEASURED"
        and status["PRECISION_RECALL_STATUS"] == "NOT_MEASURED"
        and status["GATE_2_STATUS"] == "CLOSED"
        and status["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
        and status["DOMAIN_ACCEPTED_MAPPING_COUNT"] == 0,
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "GATE_1B_PILOT_STATUS": status["GATE_1B_PILOT_STATUS"],
        "rows": 0 if summary is None else summary["rows"],
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
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "GATE_1B_PILOT_STATUS": status["GATE_1B_PILOT_STATUS"],
        "rows": verification["rows"],
        "error_class": error_class,
    }


if __name__ == "__main__":
    print(json.dumps(run(Path("."))))
