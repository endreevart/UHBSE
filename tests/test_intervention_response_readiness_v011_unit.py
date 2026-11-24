"""Unit tests — Stage 05 v0.1.1 evidence provenance correction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from human_simulator.intervention_response_readiness_v01.hashes import sha256_bytes
from human_simulator.intervention_response_readiness_v01.policy import EVIDENCE_PATHS
from human_simulator.intervention_response_readiness_v011.evidence import (
    NOT_ESTABLISHED,
    handwritten_literals,
    load_published_evidence,
)
from human_simulator.intervention_response_readiness_v011.policy import (
    ARTIFACT_DIR,
    EVIDENCE_CATALOG,
    FORBIDDEN_TRAINING_MARKERS,
    REVIEW_ZIP,
    V01_SHA256,
    V01_ZIP,
)
from human_simulator.intervention_response_readiness_v011.publish import PublicationError, publish
from human_simulator.intervention_response_readiness_v011.replay import compare_artifact_dirs
from human_simulator.intervention_response_readiness_v011.snapshots import verify_snapshots

_TOY = {
    "key": "toy",
    "canonical_source_path": "fixtures/toy.json",
    "originating_bundle_name": "not-packed.zip",
    "originating_bundle_sha256": "abc",
    "evidence_role": "toy_role",
    "privacy_classification": "AGGREGATE_STATUS_ONLY",
}


def _manifest(root: Path, payload: bytes, *, canonical: str | None = None) -> None:
    art = root / ARTIFACT_DIR
    snap = art / "upstream-evidence"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "toy.json").write_bytes(payload)
    digest = sha256_bytes(payload)
    document = {
        "snapshots": [
            {
                "key": "toy",
                "canonical_source_path": canonical or _TOY["canonical_source_path"],
                "source_sha256": digest,
                "originating_bundle_name": _TOY["originating_bundle_name"],
                "originating_bundle_sha256": _TOY["originating_bundle_sha256"],
                "evidence_role": _TOY["evidence_role"],
                "privacy_classification": _TOY["privacy_classification"],
                "snapshot_relpath": "upstream-evidence/toy.json",
                "snapshot_sha256": digest,
                "source_bytes_equal_snapshot": True,
            }
        ]
    }
    (art / "upstream-evidence-manifest.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_handwritten_literals_follow_provenance() -> None:
    assert handwritten_literals([{"origin": "evidence"}, {"origin": "derived_from_evidence"}]) is False
    assert handwritten_literals([{"origin": "code_literal"}]) is True
    source = Path("src/human_simulator/intervention_response_readiness_v011/evidence.py").read_text(encoding="utf-8")
    assert "handwritten_literals(provenance)" in source
    assert 'appointment_date_not_administration", True' not in source


def test_missing_evidence_fails_closed(tmp_path: Path) -> None:
    loaded = load_published_evidence(tmp_path)
    phase0 = loaded["phase0"]
    assert loaded["ok"] is False
    assert phase0["computed_from_published_artifacts"] is False
    assert phase0["handwritten_literals"] is False
    assert phase0["appointment_date_not_administration"] == NOT_ESTABLISHED
    assert phase0["appointment_date_not_administration"] is not True
    assert phase0["source_a_record_class"] == NOT_ESTABLISHED
    assert phase0["mapping_accepted"] == NOT_ESTABLISHED
    assert phase0["MEDICATION_TIMESTAMP_SEMANTICS_STATUS"] == NOT_ESTABLISHED
    assert phase0["MEDICATION_RESIDUAL_FOUNDATION_STATUS"] == NOT_ESTABLISHED
    assert phase0["not_prescription"] == NOT_ESTABLISHED
    assert phase0["not_administration"] == NOT_ESTABLISHED
    assert phase0["dose_value_confirmed"] is not True
    assert phase0["route_confirmed"] is not True
    assert len(phase0["evidence_files_missing"]) == len(EVIDENCE_PATHS) == 10
    assert set(phase0["evidence_files_missing"]) == set(EVIDENCE_PATHS.values())


def test_modified_deleted_and_substituted_snapshots_fail(tmp_path: Path) -> None:
    payload = b'{"ok": true}\n'
    _manifest(tmp_path, payload)
    ok = verify_snapshots(tmp_path, catalog=(_TOY,))
    assert ok["ok"] is True
    assert ok["UPSTREAM_EVIDENCE_SNAPSHOT_STATUS"] == "PASS"

    snap = tmp_path / ARTIFACT_DIR / "upstream-evidence" / "toy.json"
    snap.write_bytes(b'{"ok": false}\n')
    modified = verify_snapshots(tmp_path, catalog=(_TOY,))
    assert modified["ok"] is False
    assert any(item["reason"] == "SNAPSHOT_HASH_MISMATCH" for item in modified["problems"])

    snap.unlink()
    deleted = verify_snapshots(tmp_path, catalog=(_TOY,))
    assert any(item["reason"] == "SNAPSHOT_DELETED" for item in deleted["problems"])

    _manifest(tmp_path, payload, canonical="fixtures/other.json")
    substituted = verify_snapshots(tmp_path, catalog=(_TOY,))
    assert substituted["ok"] is False
    assert any(item["reason"] == "SUBSTITUTED_EVIDENCE_PATH" for item in substituted["problems"])


def test_normalized_compare_ignores_generated_at_only(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    common = {
        "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
        "cells": [{"cell_id": "b", "n": 1}, {"cell_id": "a", "n": 2}],
    }
    for folder, stamp in ((left, "t1"), (right, "t2")):
        for name in (
            "phase0-readiness-gaps.json",
            "exposure-semantics-contract.json",
            "intervention-evidence-registry.json",
            "candidate-cell-gate-matrix.json",
            "source-a-readiness.json",
            "source-b-readiness.json",
            "medication-residual-consumption-decision.json",
            "negative-control-results.json",
        ):
            (folder / name).write_text(json.dumps({**common, "generated_at": stamp}), encoding="utf-8")
        (folder / "status-contract.json").write_text(
            json.dumps(
                {
                    **common,
                    "generated_at": stamp,
                    "CORE_READINESS_REPLAY_STATUS": "NOT_RUN_AWAITING_CLEAN_EXTRACTION" if folder is left else "PASS",
                    "PUBLICATION_INTEGRITY_STATUS": "NOT_PACKED",
                }
            ),
            encoding="utf-8",
        )
    assert compare_artifact_dirs(left, right)["ok"] is True
    changed = json.loads((right / "phase0-readiness-gaps.json").read_text(encoding="utf-8"))
    changed["INTERVENTION_RESPONSE_READINESS_STATUS"] = "READY"
    (right / "phase0-readiness-gaps.json").write_text(json.dumps(changed), encoding="utf-8")
    mismatch = compare_artifact_dirs(left, right)
    assert mismatch["ok"] is False
    assert mismatch["mismatches"][0]["file"] == "phase0-readiness-gaps.json"


def test_v011_sources_have_no_training_path() -> None:
    root = Path("src/human_simulator/intervention_response_readiness_v011")
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name == "policy.py":
            assert "import sklearn" not in text
            assert "def train_model" not in text
            continue
        for marker in FORBIDDEN_TRAINING_MARKERS:
            assert marker not in text, path.name


def test_publish_refuses_overwrite_and_does_not_write_v01(tmp_path: Path) -> None:
    external = tmp_path / "artifacts" / "external-review"
    external.mkdir(parents=True)
    frozen = b"frozen-v01"
    (external / V01_ZIP).write_bytes(frozen)
    (external / REVIEW_ZIP).write_bytes(b"already")
    with pytest.raises(PublicationError, match="refuse overwrite"):
        publish(tmp_path)
    assert (external / V01_ZIP).read_bytes() == frozen
    assert V01_SHA256 == "6605a4b643ea68ae893d6b52d0a0a196e1e2ad2ec505adad5691a41df70cf992"


def test_publish_does_not_create_zip_when_baseline_is_absent(tmp_path: Path) -> None:
    with pytest.raises(PublicationError):
        publish(tmp_path)
    assert not (tmp_path / "artifacts" / "external-review" / REVIEW_ZIP).exists()
    assert list(EVIDENCE_CATALOG)  # catalog is the packed evidence set
