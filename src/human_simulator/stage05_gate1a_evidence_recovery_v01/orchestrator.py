"""Run primary evidence recovery. Writes only its own artifact directory."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v021.baseline import hash_tree, sha256_file, stage05_status
from human_simulator.stage05_gate1a_evidence_recovery_v01.adjudicate import closes, gate_outcome
from human_simulator.stage05_gate1a_evidence_recovery_v01.catalog import (
    _run,
    document_evidence,
    form_evidence,
    identity_evidence,
    section_evidence,
)
from human_simulator.stage05_gate1a_evidence_recovery_v01.limitations import reproduce
from human_simulator.stage05_gate1a_evidence_recovery_v01.mutations import run_negative_controls
from human_simulator.stage05_gate1a_evidence_recovery_v01.pins import verify_files
from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import (
    ARTIFACT_DIR,
    BASELINE_TREES,
    DECISION_RECORDS,
    FORBIDDEN_ABSENCE_CLAIM,
    REQUIRED_ARTIFACTS,
    SCIENTIFIC_CEILING,
    SUPERSEDING_RECORDS,
    TEMPORAL_LEDGER,
    VERSION,
    policy_snapshot,
)
from human_simulator.stage05_gate1a_evidence_recovery_v01.probes import source_a_code_evidence
from human_simulator.stage05_gate1a_evidence_recovery_v01.report import render
from human_simulator.stage05_gate1a_evidence_recovery_v01.resolve import resolve, row_assignments
from human_simulator.stage05_gate1a_evidence_recovery_v01.search import coverage, inventory

_STAGE_ZIPS = (
    "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1-review.zip",
    "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1-review.zip",
    "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.2-review.zip",
    "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.3-review.zip",
    "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.4-review.zip",
    "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.5-review.zip",
    "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6-review.zip",
    "artifacts/external-review/stage-05-intervention-response-readiness-and-exposure-semantics-v0.1-review.zip",
    "artifacts/external-review/stage-05-intervention-response-readiness-and-exposure-semantics-v0.1.1-review.zip",
)


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _digest(entries: list[dict[str, Any]]) -> str:
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _snapshot(root: Path) -> dict[str, Any]:
    trees = []
    for relative in BASELINE_TREES:
        entries = hash_tree(root, relative)
        trees.append({"path": relative, "files": len(entries), "sha256": _digest(entries), "complete": all(item.get("sha256") for item in entries)})
    zips = []
    for relative in _STAGE_ZIPS:
        path = root / relative
        zips.append({"path": relative, "sha256": sha256_file(path) if path.is_file() else None})
    return {"trees": trees, "zips": zips, "pins": verify_files(root), "stage05": stage05_status(root)}


def _same(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return before["trees"] == after["trees"] and before["zips"] == after["zips"] and before["stage05"] == after["stage05"]


def _manifest(art: Path) -> None:
    files = [
        {"path": path.relative_to(art).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
        for path in sorted(art.rglob("*"))
        if path.is_file() and path.name != "MANIFEST.json"
    ]
    _dump(art / "MANIFEST.json", {"version": VERSION, "files": files})


def _questions(identity: dict[str, Any], form: dict[str, Any], items: dict[str, Any], sections: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [{
        "question_id": "B_IDENTITY",
        "attestation": "insufficient",
        "closes_question": closes("B_IDENTITY", identity),
        "level": identity["level"],
        "reason": "no subject-key relation contract",
    }]
    for field in form["fields"]:
        if field["question_id"] == "B_DRUGS_FIRST":
            continue
        rows.append({
            "question_id": field["question_id"],
            "attestation": "insufficient",
            "closes_question": closes(field["question_id"], field),
            "level": field["level"],
            "reason": "no user-facing form binding",
        })
    for evidence, reason in (
        (items, "structure only; description is unconstrained"),
        (sections, "registry lists more than the accepted medicines code"),
        (document, "no delivery or finalization evidence"),
    ):
        rows.append({
            "question_id": evidence["question_id"],
            "attestation": "insufficient",
            "closes_question": closes(evidence["question_id"], evidence),
            "level": evidence["level"],
            "reason": reason,
        })
    return rows


def run(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    before = _snapshot(root)
    if not before["pins"]["ok"] or before["stage05"]["STAGE05_BASELINE_VERIFICATION_STATUS"] != "PASS":
        _dump(art / "baseline-verification.json", {"ok": False, "before": before})
        return {"ok": False, "stopped": True, "reason": "BASELINE_PIN"}
    limitations = reproduce(root)
    repos = inventory(root)
    searched = coverage(root)
    source_b, source_a, queries = _run(root)
    identity = identity_evidence(source_b)
    code = source_a_code_evidence()
    form = form_evidence(source_b, repos["SOURCE_B_APPLICATION_CODE_ACCESS_STATUS"])
    form["magerya_doctor_feedback"] = code["doctor_feedback"]
    sections = section_evidence(source_a)
    document = document_evidence(source_a)
    items = code["recommendation_items"]
    prior = json.loads((root / DECISION_RECORDS).read_text(encoding="utf-8"))["responses"]
    superseding = json.loads((root / SUPERSEDING_RECORDS).read_text(encoding="utf-8"))["responses"]
    resolved = resolve(prior, superseding)
    ledger = json.loads((root / TEMPORAL_LEDGER).read_text(encoding="utf-8"))
    assignments = row_assignments(ledger)
    questions = _questions(identity, form, items, sections, document)
    closed = {row["question_id"]: row["closes_question"] for row in questions}
    outcome = gate_outcome(closed)
    new_records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="uhbse-gate1a-evidence-") as tmp:
        controls = run_negative_controls(Path(tmp), prior, superseding)
    queries_ok = bool(queries) and all(item.get("success") and item.get("read_only_verified") for item in queries)
    status: dict[str, Any] = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "accepted_decisions": 4,
        "insufficient_decisions": 10,
        "NEW_SUPERSEDING_RECORD_COUNT": len(new_records),
        "SOURCE_B_APPLICATION_CODE_ACCESS_STATUS": repos["SOURCE_B_APPLICATION_CODE_ACCESS_STATUS"],
        "SOURCE_B_FORM_SEMANTICS_STATUS": form["SOURCE_B_FORM_SEMANTICS_STATUS"],
        "PRIOR_EVIDENCE_RECOVERY_LIMITATIONS_STATUS": limitations["PRIOR_EVIDENCE_RECOVERY_LIMITATIONS_STATUS"],
        "SUPERSESSION_RESOLUTION_STATUS": resolved["SUPERSESSION_RESOLUTION_STATUS"],
        "EFFECTIVE_B_TIMING_CLOSES_QUESTION": resolved["EFFECTIVE_B_TIMING_CLOSES_QUESTION"],
        "EFFECTIVE_B_PERIOD_CLOSES_QUESTION": resolved["EFFECTIVE_B_PERIOD_CLOSES_QUESTION"],
        **assignments,
        **outcome,
        **SCIENTIFIC_CEILING,
        "medication_extractor": False,
        "model_training": False,
        "database_access": "read_only_catalog",
        "queries_read_only": queries_ok,
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "GATE_1A_EVIDENCE_RECOVERY_STATUS": "PENDING",
        "policy": policy_snapshot(),
    }
    execution = bool(
        limitations["PRIOR_EVIDENCE_RECOVERY_LIMITATIONS_STATUS"] == "REPRODUCED"
        and controls["ok"]
        and queries_ok
        and resolved["SUPERSESSION_RESOLUTION_STATUS"] == "PASS"
        and status["EFFECTIVE_B_TIMING_CLOSES_QUESTION"] is False
        and status["EFFECTIVE_B_PERIOD_CLOSES_QUESTION"] is False
        and status["B_TIMING_ROW_LEVEL_ASSIGNMENT_COUNT"] == 0
        and status["B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT"] == 0
        and status["workflow_applied_row_count"] == 0
        and status["observed_row_count"] == 41407
        and not new_records
        and not any(row["closes_question"] for row in questions)
        and status["GATE_1A_STATUS"] == "PARTIALLY_ATTESTED_OPEN"
        and status["GATE_1B_STATUS"] == "BLOCKED"
        and FORBIDDEN_ABSENCE_CLAIM not in json.dumps(form)
        and identity["relation_contract"] == "NOT_FOUND"
        and code["doctor_feedback"]["is_source_b_feedback"] is False
    )
    _dump(art / "prior-evidence-recovery-limitations.json", limitations)
    _dump(art / "repository-inventory.json", repos)
    _dump(art / "search-coverage.json", {
        "repositories": searched["repositories"],
        "combined_counts": searched["combined_counts"],
        "coverage_gaps": searched["coverage_gaps"],
        "hit_count": len(searched["hits"]),
        "hits": searched["hits"],
    })
    _dump(art / "source-b-identity-evidence.json", {**identity, "queries": [{"query": item["query"], "sql_sha256": item["sql_sha256"], "success": item["success"], "read_only_verified": item["read_only_verified"]} for item in queries if item["source_system"] == "kgz_raw"]})
    _dump(art / "source-b-form-evidence.json", form)
    _dump(art / "source-a-recommendation-items-evidence.json", {"code": code["recommendation_items"], "probes": code["probes"]})
    _dump(art / "source-a-section-code-evidence.json", {**sections, "activity_fixture_rejected": code["activity_fixture_rejected"]})
    _dump(art / "source-a-document-lifecycle-evidence.json", {**document, "code": code["document_lifecycle_code"]})
    _dump(art / "effective-decision-resolution.json", {**resolved, **assignments})
    _dump(art / "new-superseding-decision-records.json", {"version": VERSION, "responses": new_records})
    _dump(art / "blocking-question-status.json", {"questions": questions, "source_b_positive_changes_is_response_label": False})
    _dump(art / "negative-control-results.json", controls)
    after = _snapshot(root)
    baselines_ok = _same(before, after) and after["pins"]["ok"]
    execution = execution and baselines_ok
    status["GATE_1A_EVIDENCE_RECOVERY_STATUS"] = "PASS" if execution else "FAIL"
    _dump(art / "baseline-verification.json", {
        "ok": baselines_ok,
        "rejected_concatenated_pin_accepted": before["pins"]["rejected_concatenated_pin_accepted"],
        "pins": after["pins"],
        "before": {"trees": before["trees"], "zips": before["zips"], "stage05": before["stage05"]["STAGE05_BASELINE_VERIFICATION_STATUS"]},
        "after": {"trees": after["trees"], "zips": after["zips"], "stage05": after["stage05"]["STAGE05_BASELINE_VERIFICATION_STATUS"]},
    })
    _dump(art / "status-contract.json", status)
    (art / "gate-1a-evidence-recovery-report.md").write_text(render(status), encoding="utf-8")
    scan = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    if not scan["ok"] or FORBIDDEN_ABSENCE_CLAIM in (art / "gate-1a-evidence-recovery-report.md").read_text(encoding="utf-8"):
        status["GATE_1A_EVIDENCE_RECOVERY_STATUS"] = "FAIL"
    _dump(art / "privacy-scan.json", scan)
    _dump(art / "status-contract.json", status)
    (art / "gate-1a-evidence-recovery-report.md").write_text(render(status), encoding="utf-8")
    missing = [name for name in REQUIRED_ARTIFACTS if name not in {"verification.json", "MANIFEST.json"} and not (art / name).is_file()]
    report = (art / "gate-1a-evidence-recovery-report.md").read_text(encoding="utf-8")
    reconciled = all(f"`{key}`={status[key]}" in report for key in ("GATE_1A_STATUS", "GATE_1B_STATUS", "INTERVENTION_RESPONSE_READINESS_STATUS"))
    verification = {
        "ok": status["GATE_1A_EVIDENCE_RECOVERY_STATUS"] == "PASS" and scan["ok"] and not missing and reconciled,
        "GATE_1A_EVIDENCE_RECOVERY_STATUS": status["GATE_1A_EVIDENCE_RECOVERY_STATUS"],
        "GATE_1A_STATUS": status["GATE_1A_STATUS"],
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "INTERVENTION_RESPONSE_READINESS_STATUS": status["INTERVENTION_RESPONSE_READINESS_STATUS"],
        "report_reconciled": reconciled,
        "missing_artifacts": missing,
        "new_superseding_records": len(new_records),
        "external_review_zip_created": False,
        "medication_extractor": False,
        "model_training": False,
    }
    _dump(art / "verification.json", verification)
    _manifest(art)
    final_scan = scan_public(art)
    if not final_scan["ok"]:
        verification["ok"] = False
        verification["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        status["GATE_1A_EVIDENCE_RECOVERY_STATUS"] = "FAIL"
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        _dump(art / "privacy-scan.json", final_scan)
        _dump(art / "status-contract.json", status)
        _dump(art / "verification.json", verification)
        _manifest(art)
    return {
        "ok": verification["ok"],
        "GATE_1A_EVIDENCE_RECOVERY_STATUS": status["GATE_1A_EVIDENCE_RECOVERY_STATUS"],
        "GATE_1A_STATUS": status["GATE_1A_STATUS"],
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "INTERVENTION_RESPONSE_READINESS_STATUS": status["INTERVENTION_RESPONSE_READINESS_STATUS"],
        "new_records": len(new_records),
        "identity": identity["relation_contract"],
        "source_b_code": repos["SOURCE_B_APPLICATION_CODE_ACCESS_STATUS"],
    }


if __name__ == "__main__":
    print(json.dumps(run(Path("."))))
