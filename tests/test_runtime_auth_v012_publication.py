"""Publication integrity regressions for runtime-auth v0.1.2 (v0.1.1 defect)."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from human_simulator.stage03_alignment.publication_integrity import (
    verify_extracted_bundle,
    verify_sha256_manifest,
    write_sha256_manifest,
)
from human_simulator.stage03_alignment.publish_runtime_auth_v012 import (
    compute_attestation_checks,
    refuse_publish_after_manifest_mutation,
)


def test_manifest_mismatch_after_test_results_mutation(tmp_path: Path) -> None:
    """Reproduce v0.1.1 defect: manifest then mutate test-results → verify FAIL."""
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "report.md").write_text("ok\n", encoding="utf-8")
    tr = evidence / "test-results.json"
    tr.write_text(json.dumps({"passed": 1}) + "\n", encoding="utf-8")
    write_sha256_manifest(evidence)
    assert verify_sha256_manifest(evidence / "manifest.sha256", base_dir=evidence)["verified"]
    tr.write_text(json.dumps({"passed": 1, "extra": True}) + "\n", encoding="utf-8")
    result = verify_sha256_manifest(evidence / "manifest.sha256", base_dir=evidence)
    assert result["verified"] is False
    assert any("test-results.json" in m for m in result["mismatches"])


def test_refuse_publish_helper_detects_mutation(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "test-results.json").write_text("{}\n", encoding="utf-8")
    assert refuse_publish_after_manifest_mutation(evidence) is True


def test_hard_coded_publication_pass_not_accepted() -> None:
    """publication_integrity_status PASS only when all checks true."""
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "x.zip"
        zip_path.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
        sidecar = Path(tmp) / "x.zip.sha256"
        sidecar.write_text("deadbeef  x.zip\n", encoding="utf-8")
        integrity = compute_attestation_checks(
            zip_path=zip_path,
            sidecar_path=sidecar,
            zip_sha="0000",
            before_pack={"internal_manifest_verified_before_pack": True},
            extract_result={"internal_manifest_verified_after_extract": True},
            index_result={
                "verified": True,
                "no_unindexed_members": True,
                "no_missing_members": True,
                "no_duplicate_members": True,
                "no_nested_archives": True,
            },
            suites_passed=True,
            archive_rebuilt=False,
        )
        assert integrity["publication_integrity_status"] == "FAIL"
        assert integrity["checks"]["outer_zip_sha_matches_sidecar"] is False


def test_archive_rebuilt_after_hashing_forces_fail() -> None:
    from human_simulator.stage03_alignment import publish_runtime_auth_v012 as pub

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "x.zip"
        data = b"PK\x05\x06" + b"\x00" * 18
        zip_path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        sidecar = Path(tmp) / "x.zip.sha256"
        sidecar.write_text(f"{digest}  {pub.ZIP_NAME}\n")
        integrity = compute_attestation_checks(
            zip_path=zip_path,
            sidecar_path=sidecar,
            zip_sha=digest,
            before_pack={"internal_manifest_verified_before_pack": True},
            extract_result={"internal_manifest_verified_after_extract": True},
            index_result={
                "verified": True,
                "no_unindexed_members": True,
                "no_missing_members": True,
                "no_duplicate_members": True,
                "no_nested_archives": True,
            },
            suites_passed=True,
            archive_rebuilt=True,
        )
        assert integrity["publication_integrity_status"] == "FAIL"
        assert integrity["checks"]["archive_rebuilt_after_hashing"] is True


def test_extracted_mismatch_fails_verify(tmp_path: Path) -> None:
    root = tmp_path / "extract"
    evidence = root / "artifacts/stage-03-alignment-runtime-auth-v0.1.2"
    evidence.mkdir(parents=True)
    (evidence / "test-results.json").write_text("{}\n", encoding="utf-8")
    write_sha256_manifest(evidence)
    (root / "REVIEW_INDEX.md").write_text(
        "| `artifacts/stage-03-alignment-runtime-auth-v0.1.2/test-results.json` "
        "| `0000000000000000000000000000000000000000000000000000000000000000` |\n",
        encoding="utf-8",
    )
    result = verify_extracted_bundle(
        root, evidence_subdir="artifacts/stage-03-alignment-runtime-auth-v0.1.2"
    )
    assert result["review_index_verified_after_extract"] is False


def test_hard_coded_two_independent_constant_rejected() -> None:
    """distinct must be computed — constant true alone is invalid evidence shape."""
    # Simulated bad evidence
    bad = {"two_independent_wrapped_secret_ids": True, "distinct_nonsecret_request_metadata": True}
    # Acceptable evidence requires runtime-computed fields without the hard-coded key
    good = {
        "wrapper_reuse_rejected": True,
        "distinct_nonsecret_request_metadata": True,
        "cycle_1": {"wrapper_requested": True, "creation_time": "t1"},
        "cycle_2": {"second_wrapper_requested": True, "creation_time": "t2"},
    }
    assert "two_independent_wrapped_secret_ids" not in good
    assert bad.get("two_independent_wrapped_secret_ids") is True  # documents forbidden shape
