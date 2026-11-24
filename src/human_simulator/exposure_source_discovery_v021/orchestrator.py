"""Run the v0.2.1 accounting correction. Does not write v0.1, v0.2, or a review ZIP."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.db import QueryLog, connect_b, schema_fingerprint
from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v021.accounting import collect
from human_simulator.exposure_source_discovery_v021.baseline import compare, snapshot
from human_simulator.exposure_source_discovery_v021.defect import attach_live_composition, reproduce_frozen
from human_simulator.exposure_source_discovery_v021.mutations import run_negative_controls
from human_simulator.exposure_source_discovery_v021.policy import (
    ARTIFACT_DIR,
    REQUIRED_ARTIFACTS,
    SCIENTIFIC_CEILING,
    VERSION,
    policy_snapshot,
)
from human_simulator.exposure_source_discovery_v021.report import count_tokens, render, tokens_match

B_TABLES = [("public", "feedback"), ("public", "consultations")]


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _manifest(art: Path) -> None:
    files = []
    for path in sorted(art.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.json":
            files.append({
                "path": path.relative_to(art).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            })
    _dump(art / "MANIFEST.json", {"version": VERSION, "files": files})


def _technical(ledger: dict[str, Any], report: str, tokens: dict[str, int], controls_ok: bool, queries_ok: bool) -> bool:
    exclusive = ledger["exclusive"]
    targets = ledger["targets"]
    subjects = ledger["subjects"]
    return bool(
        exclusive["FEEDBACK_TEMPORAL_EXCLUSIVE_ACCOUNTING_STATUS"] == "PASS"
        and exclusive["unclassified_count"] == 0
        and exclusive["overlap_count"] == 0
        and exclusive["sum_exclusive_categories"] == exclusive["FEEDBACK_TOTAL_COUNT"]
        and targets["CONSULTATION_TARGET_ACCOUNTING_STATUS"] == "PASS"
        and subjects["SUBJECT_KEY_COMPARISON_ACCOUNTING_STATUS"] == "PASS"
        and ledger["route"]["exclusive_funnel_sums_to_denominator"]
        and ledger["route"]["denominator"] == exclusive["FEEDBACK_TOTAL_COUNT"]
        and tokens_match(report, tokens)
        and controls_ok
        and queries_ok
        and ledger["subjects"]["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"] == "NOT_ESTABLISHED"
        and ledger["temporal_contract"]["SOURCE_B_TIMEZONE_SEMANTICS_STATUS"] == "UNKNOWN_SOURCE_TIMEZONE"
    )


def run(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    before = snapshot(root)
    baselines_ok = (
        before["stage05"]["STAGE05_BASELINE_VERIFICATION_STATUS"] == "PASS"
        and bool(before["v01_artifacts"])
        and bool(before["v02_artifacts"])
    )
    if not baselines_ok:
        compared = compare(before, snapshot(root))
        _dump(art / "baseline-verification.json", compared)
        return {"ok": False, "stopped": True, "STAGE05_BASELINE_VERIFICATION_STATUS": "FAIL"}
    defect = reproduce_frozen(root)
    conn = connect_b(root)
    try:
        fingerprint = schema_fingerprint(conn, B_TABLES)
        log = QueryLog(fingerprint)
        ledger = collect(conn, log, fingerprint)
        entries = log.entries
    finally:
        conn.close()
    temporal_counts = {name: item["count"] for name, item in ledger["exclusive"]["categories"].items()}
    defect = attach_live_composition(defect, temporal_counts)
    with tempfile.TemporaryDirectory(prefix="uhbse-v021-nc-") as tmp:
        controls = run_negative_controls(Path(tmp))
    queries_ok = all(item.get("success") and item.get("read_only_verified") for item in entries)
    tokens = count_tokens(ledger)
    status = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "V01_BASELINE_VERIFICATION_STATUS": "PENDING_AFTER",
        "V02_BASELINE_VERIFICATION_STATUS": "PENDING_AFTER",
        "STAGE05_BASELINE_VERIFICATION_STATUS": before["stage05"]["STAGE05_BASELINE_VERIFICATION_STATUS"],
        "V02_CORE_TEMPORAL_COMPUTATION_STATUS": defect["V02_CORE_TEMPORAL_COMPUTATION_STATUS"],
        "V02_TEMPORAL_ACCOUNTING_STATUS": defect["V02_TEMPORAL_ACCOUNTING_STATUS"],
        "V02_FINAL_REPORT_ACCOUNTING_STATUS": defect["V02_FINAL_REPORT_ACCOUNTING_STATUS"],
        "FEEDBACK_TEMPORAL_EXCLUSIVE_ACCOUNTING_STATUS": ledger["exclusive"]["FEEDBACK_TEMPORAL_EXCLUSIVE_ACCOUNTING_STATUS"],
        "CONSULTATION_TARGET_ACCOUNTING_STATUS": ledger["targets"]["CONSULTATION_TARGET_ACCOUNTING_STATUS"],
        "SUBJECT_KEY_COMPARISON_ACCOUNTING_STATUS": ledger["subjects"]["SUBJECT_KEY_COMPARISON_ACCOUNTING_STATUS"],
        "SOURCE_B_TIMEZONE_SEMANTICS_STATUS": ledger["temporal_contract"]["SOURCE_B_TIMEZONE_SEMANTICS_STATUS"],
        "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": ledger["route"]["SOURCE_B_TEMPORAL_SEQUENCE_STATUS"],
        "TECHNICAL_DISCOVERY_STATUS": "PENDING",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "counts": tokens,
        "policy": policy_snapshot(),
        **SCIENTIFIC_CEILING,
    }
    report = render(ledger, defect, status)
    status["TECHNICAL_DISCOVERY_STATUS"] = "PASS" if _technical(ledger, report, tokens, controls["ok"], queries_ok) else "FAIL"
    report = render(ledger, defect, status)
    if not tokens_match(report, tokens) or status["counts"] != tokens:
        status["TECHNICAL_DISCOVERY_STATUS"] = "FAIL"
    _dump(art / "v02-temporal-accounting-defect-reproduction.json", defect)
    _dump(art / "feedback-exclusive-classification.json", ledger["exclusive"])
    _dump(art / "consultation-target-accounting.json", ledger["targets"])
    _dump(art / "subject-key-comparison-accounting.json", ledger["subjects"])
    _dump(art / "source-b-temporal-sequence-audit.json", {
        "temporal_contract": ledger["temporal_contract"],
        "route": ledger["route"],
        "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": ledger["route"]["SOURCE_B_TEMPORAL_SEQUENCE_STATUS"],
    })
    _dump(art / "temporal-accounting-reconciliation.json", {
        "counts": tokens,
        "equations_hold": status["TECHNICAL_DISCOVERY_STATUS"] == "PASS",
        "v02_residual_outside_four_reported_buckets": defect["residual_outside_four_reported_buckets"],
        "live_composition": defect["live_composition_of_rows_outside_the_four_buckets"],
        "phrase": "NUMERIC_KEY_AGREEMENT_OBSERVED_NOT_IDENTITY_PROOF",
    })
    _dump(art / "negative-control-results.json", controls)
    _dump(art / "query-log.json", {"version": VERSION, "queries": entries})
    (art / "discovery-report.md").write_text(report, encoding="utf-8")
    _dump(art / "status-contract.json", status)
    after = compare(before, snapshot(root))
    if after["V01_BASELINE_VERIFICATION_STATUS"] != "PASS" or after["V02_BASELINE_VERIFICATION_STATUS"] != "PASS":
        status["TECHNICAL_DISCOVERY_STATUS"] = "FAIL"
    status["V01_BASELINE_VERIFICATION_STATUS"] = after["V01_BASELINE_VERIFICATION_STATUS"]
    status["V02_BASELINE_VERIFICATION_STATUS"] = after["V02_BASELINE_VERIFICATION_STATUS"]
    status["STAGE05_BASELINE_VERIFICATION_STATUS"] = after["STAGE05_BASELINE_VERIFICATION_STATUS"]
    _dump(art / "status-contract.json", status)
    _dump(art / "baseline-verification.json", after)
    report = render(ledger, defect, status)
    (art / "discovery-report.md").write_text(report, encoding="utf-8")
    scan = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    if not scan["ok"]:
        status["TECHNICAL_DISCOVERY_STATUS"] = "FAIL"
    _dump(art / "status-contract.json", status)
    _dump(art / "privacy-scan.json", scan)
    missing = [name for name in REQUIRED_ARTIFACTS if name not in {"verification.json", "MANIFEST.json"} and not (art / name).is_file()]
    verification = {
        "ok": bool(
            status["TECHNICAL_DISCOVERY_STATUS"] == "PASS"
            and scan["ok"]
            and not missing
            and after["V01_BASELINE_VERIFICATION_STATUS"] == "PASS"
            and after["V02_BASELINE_VERIFICATION_STATUS"] == "PASS"
            and after["STAGE05_BASELINE_VERIFICATION_STATUS"] == "PASS"
            and tokens_match((art / "discovery-report.md").read_text(encoding="utf-8"), tokens)
            and json.loads((art / "status-contract.json").read_text(encoding="utf-8"))["counts"] == tokens
        ),
        "TECHNICAL_DISCOVERY_STATUS": status["TECHNICAL_DISCOVERY_STATUS"],
        "PUBLIC_DATA_MINIMIZATION_STATUS": scan["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "V01_BASELINE_VERIFICATION_STATUS": after["V01_BASELINE_VERIFICATION_STATUS"],
        "V02_BASELINE_VERIFICATION_STATUS": after["V02_BASELINE_VERIFICATION_STATUS"],
        "STAGE05_BASELINE_VERIFICATION_STATUS": after["STAGE05_BASELINE_VERIFICATION_STATUS"],
        "missing_artifacts": missing,
        "external_review_zip_created": False,
        "stage_05_bundle_modified": after["STAGE05_BASELINE_VERIFICATION_STATUS"] != "PASS",
    }
    _dump(art / "verification.json", verification)
    _manifest(art)
    listed = {item["path"] for item in json.loads((art / "MANIFEST.json").read_text(encoding="utf-8"))["files"]}
    expected = {path.relative_to(art).as_posix() for path in art.rglob("*") if path.is_file() and path.name != "MANIFEST.json"}
    if listed != expected:
        verification["ok"] = False
        verification["manifest_mismatch"] = True
        _dump(art / "verification.json", verification)
        _manifest(art)
    final_scan = scan_public(art)
    if not final_scan["ok"]:
        verification["ok"] = False
        verification["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        status["TECHNICAL_DISCOVERY_STATUS"] = "FAIL"
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        _dump(art / "privacy-scan.json", final_scan)
        _dump(art / "status-contract.json", status)
        _dump(art / "verification.json", verification)
        _manifest(art)
    return {
        "ok": verification["ok"],
        "TECHNICAL_DISCOVERY_STATUS": status["TECHNICAL_DISCOVERY_STATUS"],
        "PUBLIC_DATA_MINIMIZATION_STATUS": status["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "feedback_total": tokens["feedback_total"],
        "identity": status["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"],
    }


if __name__ == "__main__":
    print(json.dumps(run(Path("."))))
