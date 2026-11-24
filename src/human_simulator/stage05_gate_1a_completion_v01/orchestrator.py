"""Run the Gate 1A scope correction. Does not write Gate 1A v0.1 or query a database."""

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
from human_simulator.stage05_gate_1a_completion_v01.contract import derive, violations
from human_simulator.stage05_gate_1a_completion_v01.mutations import run_negative_controls
from human_simulator.stage05_gate_1a_completion_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_DIR,
    PRIOR_SOURCE,
    REQUIRED_ARTIFACTS,
    SUPERSEDING_SCHEMA,
    VERSION,
    policy_snapshot,
)
from human_simulator.stage05_gate_1a_completion_v01.prior import load_prior, temporal_scope, verify_answer_binding
from human_simulator.stage05_gate_1a_completion_v01.recovery import search_form_schema
from human_simulator.stage05_gate_1a_completion_v01.report import render
from human_simulator.stage05_gate_1a_completion_v01.supersede import build_superseding
from human_simulator.stage05_gate_1a_v01.policy import V022_DIR, V022_SOURCE


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
    base["gate1a_artifacts"] = hash_tree(root, PRIOR_DIR)
    base["gate1a_source"] = hash_tree(root, PRIOR_SOURCE)
    return base


def _unchanged(before: dict[str, Any], after: dict[str, Any], name: str) -> bool:
    return (
        all(item.get("sha256") for item in before[name])
        and before[name] == after[name]
    )


def _compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result = compare(before, after)
    result["V021_BASELINE_VERIFICATION_STATUS"] = "PASS" if _unchanged(before, after, "v021_artifacts") and _unchanged(before, after, "v021_source") else "FAIL"
    result["V022_BASELINE_VERIFICATION_STATUS"] = "PASS" if _unchanged(before, after, "v022_artifacts") and _unchanged(before, after, "v022_source") else "FAIL"
    result["GATE_1A_V01_BASELINE_VERIFICATION_STATUS"] = "PASS" if _unchanged(before, after, "gate1a_artifacts") and _unchanged(before, after, "gate1a_source") else "FAIL"
    result["prior_decision_records_rewritten"] = False
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
            "GATE_1A_V01_BASELINE_VERIFICATION_STATUS",
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

    prior = load_prior(root)
    binding = verify_answer_binding(root, prior)
    temporal = temporal_scope(root)
    recovery = search_form_schema()
    superseding = build_superseding(prior, temporal) if binding["ok"] else []
    with tempfile.TemporaryDirectory(prefix="uhbse-gate1a-completion-") as tmp:
        controls = run_negative_controls(root, Path(tmp))
    status: dict[str, Any] = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "GATE_1A_COMPLETION_STATUS": "PENDING",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "database_access": "NOT_PERFORMED",
        "policy": policy_snapshot(),
        **derive(prior, superseding, recovery),
    }
    contract_violations = violations(status, prior, superseding, binding["ok"], recovery)
    execution = binding["ok"] and controls["ok"] and not contract_violations and bool(superseding)

    _dump(art / "superseding-decision-record.schema.json", SUPERSEDING_SCHEMA)
    _dump(art / "superseding-decision-records.json", {"version": VERSION, "responses": superseding})
    _dump(art / "answer-evidence-binding.json", binding)
    _dump(art / "workflow-scope.json", temporal)
    _dump(art / "evidence-recovery.json", recovery)
    _dump(art / "gate-1b-blockers.json", {
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "blockers": status["GATE_1B_BLOCKERS"],
        "still_open": status["GATE_1B_BLOCKERS_STILL_OPEN"],
        "exposure_extractor_deferred": status["EXPOSURE_EXTRACTOR_DEFERRED_QUESTIONS"],
        "source_a_open": status["SOURCE_A_OPEN_QUESTIONS"],
    })
    _dump(art / "negative-control-results.json", controls)
    after = _compare(before, _snapshot(root))
    execution = execution and _baselines_pass(after)
    status.update({key: after[key] for key in after if key.endswith("BASELINE_VERIFICATION_STATUS")})
    status["CONTRACT_VIOLATIONS"] = contract_violations
    status["GATE_1A_COMPLETION_STATUS"] = "PASS" if execution else "FAIL"
    _dump(art / "baseline-verification.json", after)
    _dump(art / "status-contract.json", status)
    (art / "gate-1a-completion-report.md").write_text(render(status, superseding, binding, temporal), encoding="utf-8")
    scan = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    if not scan["ok"]:
        status["GATE_1A_COMPLETION_STATUS"] = "FAIL"
    _dump(art / "privacy-scan.json", scan)
    _dump(art / "status-contract.json", status)
    (art / "gate-1a-completion-report.md").write_text(render(status, superseding, binding, temporal), encoding="utf-8")
    missing = [name for name in REQUIRED_ARTIFACTS if name not in {"verification.json", "MANIFEST.json"} and not (art / name).is_file()]
    verification = {
        "ok": status["GATE_1A_COMPLETION_STATUS"] == "PASS" and scan["ok"] and not missing,
        "GATE_1A_COMPLETION_STATUS": status["GATE_1A_COMPLETION_STATUS"],
        "GATE_1A_STATUS": status["GATE_1A_STATUS"],
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "INTERVENTION_RESPONSE_READINESS_STATUS": status["INTERVENTION_RESPONSE_READINESS_STATUS"],
        "answer_binding_ok": binding["ok"],
        "contract_violations": contract_violations,
        "missing_artifacts": missing,
        "prior_decision_records_rewritten": False,
        "database_access": "NOT_PERFORMED",
        "external_review_zip_created": False,
    }
    _dump(art / "verification.json", verification)
    _manifest(art)
    final_scan = scan_public(art)
    if not final_scan["ok"]:
        verification["ok"] = False
        verification["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        status["GATE_1A_COMPLETION_STATUS"] = "FAIL"
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        _dump(art / "privacy-scan.json", final_scan)
        _dump(art / "status-contract.json", status)
        _dump(art / "verification.json", verification)
        _manifest(art)
    return {
        "ok": verification["ok"],
        "GATE_1A_COMPLETION_STATUS": status["GATE_1A_COMPLETION_STATUS"],
        "GATE_1A_STATUS": status["GATE_1A_STATUS"],
        "GATE_1B_STATUS": status["GATE_1B_STATUS"],
        "INTERVENTION_RESPONSE_READINESS_STATUS": status["INTERVENTION_RESPONSE_READINESS_STATUS"],
        "superseding": len(superseding),
        "answer_binding_ok": binding["ok"],
        "recovery": recovery["SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS"],
        "violations": contract_violations,
    }


if __name__ == "__main__":
    print(json.dumps(run(Path("."))))
