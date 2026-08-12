"""Stage 02 Maintenance 01 — the diagnosis must be true, and it must change nothing.

Two things are being defended here. The first is that the maintenance run is inert: it reads
``artifacts/stage-02/`` and never writes it, restores nothing, and resolves nothing. The second
is that the reasoning behind the candidate holds — that the drift really is confined to a
timestamp, that the bytes claimed as authoritative really are the published ones, and that the
candidate really does clear the blocker it claims to clear without clearing any other.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
    verify_relationship_manifest,
)
from human_simulator.stage02_maintenance.candidate import build_candidate, load_candidate
from human_simulator.stage02_maintenance.constants import (
    CANDIDATE_DIR,
    EXPECTED_MANIFEST_SHA_AFTER,
    EXPECTED_MANIFEST_SHA_BEFORE,
    MAINTENANCE_DIR,
    STAGE_02_DIR,
    VOLATILE_FIELDS,
)
from human_simulator.stage02_maintenance.drift_diagnosis import (
    collect_published_copies,
    compare_semantics,
    evaluate_drift,
    read_manifest,
    semantic_digest,
    sha256_file,
    timestamp_split,
)
from human_simulator.stage02_maintenance.reproduction import sanitise_query_log
from human_simulator.stage02_maintenance.run_maintenance_01 import (
    contested_artifacts,
    restore_mechanism,
)
from human_simulator.stage03.prior_stage_integrity import ACCEPTED_SHA256

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIFTED = ("subject-root-analysis.json", "identity-linkage-assessment.json")


@pytest.fixture(scope="module")
def drift():
    return {item.name: item for item in evaluate_drift(REPO_ROOT)}


def stage_02_fingerprint(root: Path = REPO_ROOT) -> dict[str, str]:
    directory = root / STAGE_02_DIR
    return {
        name: sha256_file(directory / name)
        for name in (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME)
        if (directory / name).is_file()
    }


# ---------------------------------------------------------------------------------------
# The drift is exactly what the diagnosis says it is
# ---------------------------------------------------------------------------------------


def test_no_manifest_drift_in_the_working_tree_after_repair(drift):
    drifted = [item.name for item in drift.values() if not item.matches_manifest]
    assert drifted == []


def test_all_eight_artifacts_match_the_manifest_after_repair(drift):
    matching = [item.name for item in drift.values() if item.matches_manifest]
    assert len(matching) == 8


def test_the_drifted_set_is_the_intersection_of_the_two_pinning_authorities():
    """The whole diagnosis rests on this. If it stops holding, the explanation is wrong."""
    assert sorted(contested_artifacts()) == sorted(DRIFTED)


def test_the_historical_drift_is_recorded_in_the_hash_matrix():
    matrix_path = REPO_ROOT / MAINTENANCE_DIR / "before-after-hash-matrix.json"
    if not matrix_path.is_file():
        pytest.skip("diagnosis hash matrix not present")
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    promotion = matrix.get("promotion") or {}
    assert sorted(matrix["drifted_artifacts"]) == sorted(DRIFTED)
    assert promotion.get("manifest_sha256_before") == EXPECTED_MANIFEST_SHA_BEFORE
    assert sha256_file(REPO_ROOT / STAGE_02_DIR / MANIFEST_NAME) == EXPECTED_MANIFEST_SHA_AFTER


def test_the_current_bytes_are_the_published_ones(drift):
    for name in DRIFTED:
        assert drift[name].current_bytes_published_in, (
            f"{name}: current bytes appear in no published bundle"
        )


def test_the_current_bytes_are_the_prior_stage_baseline(drift):
    for name in DRIFTED:
        assert drift[name].current_sha256 == ACCEPTED_SHA256[f"artifacts/stage-02/{name}"]


def test_the_named_restore_command_would_produce_exactly_this_state():
    """The explanation is only as good as the mechanism it names, so the mechanism is checked."""
    mechanism = restore_mechanism(REPO_ROOT)
    assert mechanism["source_matches_current_bytes"], (
        "the restore source no longer holds the bytes on disk, so it is not the explanation"
    )
    assert not mechanism["covers_the_relationship_manifest"], (
        "if the restore also rewrote the manifest, it could not leave the two out of step"
    )
    assert sorted(mechanism["relationship_artifacts_it_covers"]) == sorted(DRIFTED)
    assert mechanism["explains_the_observed_state"]


def test_a_markdown_sibling_disagrees_with_its_own_json():
    """The fingerprint of a targeted restore rather than a regeneration."""
    for name in DRIFTED:
        split = timestamp_split(REPO_ROOT, name)
        assert split["siblings_disagree"], (
            f"{name}: json and markdown agree, so a restore is no longer the explanation"
        )


# ---------------------------------------------------------------------------------------
# The difference is a timestamp and nothing else
# ---------------------------------------------------------------------------------------


def test_every_published_copy_says_the_same_thing(drift):
    import zipfile

    for name in DRIFTED:
        current = (REPO_ROOT / STAGE_02_DIR / name).read_bytes()
        for copy in drift[name].published_copies:
            archive = REPO_ROOT / "artifacts" / "external-review" / copy.bundle
            with zipfile.ZipFile(archive) as bundle:
                payload = bundle.read(copy.member)
            comparison = compare_semantics(
                name, current, payload, reference_label="current", other_label=copy.bundle
            )
            assert comparison.semantically_identical, (
                f"{name} differs from {copy.bundle} in {comparison.semantic_differences}"
            )


def test_a_changed_verdict_is_not_mistaken_for_a_timestamp():
    """The comparison must not be so forgiving that it would miss a real change."""
    current = (REPO_ROOT / STAGE_02_DIR / "identity-linkage-assessment.json").read_bytes()
    tampered = json.loads(current)
    tampered["identity_verdict"] = {"verdict": "LINKAGE_PROVEN"}
    comparison = compare_semantics(
        "identity-linkage-assessment.json",
        current,
        json.dumps(tampered).encode(),
        reference_label="current",
        other_label="tampered",
    )
    assert not comparison.semantically_identical
    assert any("identity_verdict" in item for item in comparison.semantic_differences)


def test_a_changed_denominator_is_detected():
    current = (REPO_ROOT / STAGE_02_DIR / "identity-linkage-assessment.json").read_bytes()
    tampered = json.loads(current)
    tampered["source_a_aggregates"] = {"subject_count": -1}
    comparison = compare_semantics(
        "identity-linkage-assessment.json",
        current,
        json.dumps(tampered).encode(),
        reference_label="current",
        other_label="tampered",
    )
    assert not comparison.semantically_identical


def test_a_changed_conflict_definition_is_detected():
    current = (REPO_ROOT / STAGE_02_DIR / "identity-linkage-assessment.json").read_bytes()
    tampered = json.loads(current)
    tampered["conflict_definition"] = "something else entirely"
    comparison = compare_semantics(
        "identity-linkage-assessment.json",
        current,
        json.dumps(tampered).encode(),
        reference_label="current",
        other_label="tampered",
    )
    assert not comparison.semantically_identical


def test_only_the_timestamp_is_treated_as_volatile():
    assert VOLATILE_FIELDS == ("assessed_at",)


def test_the_semantic_digest_ignores_the_timestamp_and_nothing_else():
    original = {"assessed_at": "a", "verdict": "X"}
    moved = {"assessed_at": "b", "verdict": "X"}
    changed = {"assessed_at": "a", "verdict": "Y"}
    assert semantic_digest(json.dumps(original).encode()) == semantic_digest(
        json.dumps(moved).encode()
    )
    assert semantic_digest(json.dumps(original).encode()) != semantic_digest(
        json.dumps(changed).encode()
    )


# ---------------------------------------------------------------------------------------
# No patient data leaves the runtime
# ---------------------------------------------------------------------------------------


def test_the_query_log_projection_drops_anything_unrecognised():
    sanitised = sanitise_query_log(
        [{"operation": "count", "status": "ok", "patient_name": "…", "sql": "SELECT …"}]
    )
    assert sanitised == [{"operation": "count", "status": "ok"}]


def test_the_published_query_log_carries_no_values():
    path = REPO_ROOT / MAINTENANCE_DIR / "sanitised-query-log.json"
    if not path.is_file():
        pytest.skip("diagnosis has not been run in this workspace")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["contains_row_values"] is False
    for entry in document["operations"]:
        assert set(entry) <= {
            "operation",
            "status",
            "relation",
            "schema",
            "source",
            "duration_ms",
            "row_count",
        }


def test_no_maintenance_artifact_contains_an_hmac_key_or_a_subject_identifier():
    directory = REPO_ROOT / MAINTENANCE_DIR
    if not directory.is_dir():
        pytest.skip("diagnosis has not been run in this workspace")
    forbidden = ("LINKAGE_HMAC_KEY", "hmac_key_value", "password", "postgresql://")
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{path.name} contains {token}"


# ---------------------------------------------------------------------------------------
# The candidate
# ---------------------------------------------------------------------------------------


def test_the_candidate_carries_all_eight_artifacts():
    candidate = load_candidate(REPO_ROOT)
    if candidate is None:
        pytest.skip("candidate has not been built in this workspace")
    assert sorted(candidate.artifact_sha256) == sorted(RELATIONSHIP_MANIFEST_ARTIFACTS)


def test_the_candidate_regenerates_nothing():
    """Every candidate artifact must be byte-identical to the accepted one it came from."""
    candidate = load_candidate(REPO_ROOT)
    if candidate is None:
        pytest.skip("candidate has not been built in this workspace")
    for name in RELATIONSHIP_MANIFEST_ARTIFACTS:
        assert sha256_file(REPO_ROOT / CANDIDATE_DIR / name) == sha256_file(
            REPO_ROOT / STAGE_02_DIR / name
        )


def test_the_candidate_manifest_verifies_against_the_candidate_artifacts():
    if not (REPO_ROOT / CANDIDATE_DIR / MANIFEST_NAME).is_file():
        pytest.skip("candidate has not been built in this workspace")
    verified, detail = verify_relationship_manifest(REPO_ROOT / CANDIDATE_DIR)
    assert verified, detail


def test_the_candidate_manifest_matches_the_working_manifest_after_repair():
    if not (REPO_ROOT / CANDIDATE_DIR / MANIFEST_NAME).is_file():
        pytest.skip("candidate has not been built in this workspace")
    assert sha256_file(REPO_ROOT / STAGE_02_DIR / MANIFEST_NAME) == sha256_file(
        REPO_ROOT / CANDIDATE_DIR / MANIFEST_NAME
    )


def test_building_the_candidate_does_not_touch_stage_02(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / STAGE_02_DIR).mkdir(parents=True)
    for name in (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME):
        shutil.copy2(REPO_ROOT / STAGE_02_DIR / name, workspace / STAGE_02_DIR / name)

    before = stage_02_fingerprint(workspace)
    build_candidate(workspace)
    assert stage_02_fingerprint(workspace) == before


def test_the_working_manifest_verifies_after_repair():
    verified, detail = verify_relationship_manifest(REPO_ROOT / STAGE_02_DIR)
    assert verified, detail


# ---------------------------------------------------------------------------------------
# The real workspace is untouched
# ---------------------------------------------------------------------------------------


def test_the_diagnosis_reads_stage_02_without_writing_it():
    before = stage_02_fingerprint()
    evaluate_drift(REPO_ROOT)
    collect_published_copies(REPO_ROOT)
    for name in DRIFTED:
        timestamp_split(REPO_ROOT, name)
    assert stage_02_fingerprint() == before


def test_the_decision_records_that_nothing_was_applied():
    path = REPO_ROOT / MAINTENANCE_DIR / "maintenance-decision.json"
    if not path.is_file():
        pytest.skip("diagnosis has not been run in this workspace")
    decision = json.loads(path.read_text(encoding="utf-8"))
    assert decision["proposed_repair"]["applied"] is False
    assert decision["status"] == "DIAGNOSED_REPAIR_PREPARED_NOT_APPLIED"


def test_the_isolated_validation_clears_one_blocker_and_no_others():
    path = REPO_ROOT / MAINTENANCE_DIR / "isolated-validation.json"
    if not path.is_file():
        pytest.skip("diagnosis has not been run in this workspace")
    validation = json.loads(path.read_text(encoding="utf-8"))
    assert validation["manifest_drift_blocker_cleared"] is True
    assert validation["pre_live_load_gate_status"] == "FAIL"
    assert len(validation["pre_live_load_gate_failed_checks"]) == 4
    assert validation["working_stage_02_unchanged"] is True
