"""Regression tests for conflict resolution gate semantics."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from human_simulator.stage03.conflict_resolution import (
    RESOLUTION_STATUS_RESOLVED,
    evaluate_resolution_gate,
)
from human_simulator.stage03.frozen_evidence import DESIGN_REPORT_NAME, DESIGN_VERIFICATION_NAME
from human_simulator.stage03.pre_live_load_blockers import evaluate_blockers
from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate
from conftest import reseal_manifest


def test_draft_release_with_correct_manifest_does_not_close_conflict_blocker(
    isolated_workspace: Path,
) -> None:
    """A DRAFT design release must not close conflict blockers even when artifacts align."""
    resolutions = isolated_workspace / "artifacts/stage-03/artifact-conflict-resolutions.yaml"
    document = yaml.safe_load(resolutions.read_text(encoding="utf-8"))
    for entry in document["resolutions"]:
        entry["resolution_status"] = RESOLUTION_STATUS_RESOLVED
    resolutions.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    reseal_manifest(isolated_workspace / "artifacts/stage-03/design-content-manifest.sha256")

    report = isolated_workspace / "artifacts/stage-03" / DESIGN_REPORT_NAME
    report.write_text(report.read_text(encoding="utf-8").replace("DRAFT", "DRAFT"), encoding="utf-8")

    verification = isolated_workspace / "artifacts/stage-03" / DESIGN_VERIFICATION_NAME
    payload = json.loads(verification.read_text(encoding="utf-8"))
    payload["status"] = "PASS"
    verification.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    gate = evaluate_resolution_gate(isolated_workspace, "temporal_precision_field_absent_from_model")
    assert not gate.effective
    assert not gate.report_final

    open_ids = {blocker.blocker_id for blocker in evaluate_blockers(isolated_workspace) if blocker.status == "OPEN"}
    assert "temporal_precision_field_absent_from_model" in open_ids
    assert "encounter_provider_id_population_disagreement" in open_ids

    failed = set(evaluate_pre_live_load_gate(isolated_workspace).failed_checks)
    assert "temporal_precision_field_absent_from_model" in failed
