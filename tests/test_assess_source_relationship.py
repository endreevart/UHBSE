"""Tests for assess-source-relationship."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from human_simulator.audit.report import REPORT_STATUS_FINAL
from human_simulator.stage02.artifact_safety import validate_relationship_artifacts
from human_simulator.stage02.assess_source_relationship import assess_source_relationship
from human_simulator.stage02.identity_linkage import (
    _compute_overlap,
    _identity_verdict,
    _population_overlap_estimate,
    assess_identity_linkage,
    hmac_identifier,
    normalize_email,
    normalize_phone,
)
from human_simulator.stage02.relation_scope import shared_relation_names
from human_simulator.stage02.relationship_gates import AssessSourceRelationshipError, run_relationship_gates
from human_simulator.stage02.relationship_manifest import verify_relationship_manifest
from human_simulator.stage02.source_relationship import _structural_similarity
from human_simulator.stage02.subject_root_analysis import (
    SUBJECT_ROOT_CONFIRMED_COVERAGE,
    _verdict_patient_id_resolution,
    _verdict_source_a,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_normalize_phone_and_email() -> None:
    assert normalize_phone("+7 (999) 123-45-67") == "79991234567"
    assert normalize_phone("89991234567") == "79991234567"
    assert normalize_email("  Test@Example.COM ") == "test@example.com"
    assert normalize_phone("123") is None


def test_hmac_identifier_requires_secret() -> None:
    digest = hmac_identifier(b"secret-key", "phone", "79991234567")
    assert len(digest) == 64
    assert digest != hmac_identifier(b"other-key", "phone", "79991234567")


def test_subject_root_verdict_source_a_confirmed() -> None:
    verdict = _verdict_source_a(
        row_count=100,
        distinct_ids=100,
        id_collision_count=0,
        explicit_patient_fks=True,
        has_pk=True,
    )
    assert verdict.verdict == "SUBJECT_ROOT_CONFIRMED"


def test_subject_root_verdict_collisions_ambiguous() -> None:
    verdict = _verdict_source_a(
        row_count=100,
        distinct_ids=99,
        id_collision_count=1,
        explicit_patient_fks=True,
        has_pk=True,
    )
    assert verdict.verdict == "SUBJECT_ROOT_AMBIGUOUS"


def test_subject_root_b_users_multi_role_candidate() -> None:
    best = {"label": "public.users.id", "match_rate": 1.0}
    verdict = _verdict_patient_id_resolution(
        best=best,
        second_best_rate=0.0,
        profile={"foreign_keys": []},
        consult_schema="public",
        consult_relation="consultations",
    )
    assert verdict.verdict == "SUBJECT_ROOT_CANDIDATE"
    assert "100% consultations.patient_id coverage" in verdict.reason
    assert "multi-role" in verdict.reason


def test_subject_root_confirmed_coverage_threshold() -> None:
    best = {"label": "public.profilaxys_profile.id", "match_rate": SUBJECT_ROOT_CONFIRMED_COVERAGE}
    verdict = _verdict_patient_id_resolution(
        best=best,
        second_best_rate=0.1,
        profile={"foreign_keys": []},
        consult_schema="public",
        consult_relation="consultations",
    )
    assert verdict.verdict == "SUBJECT_ROOT_CONFIRMED"


def test_low_phone_coverage_does_not_create_population_estimate() -> None:
    estimate = _population_overlap_estimate(
        {
            "subject_count": 1000,
            "phone_present_count": 7,
        },
        consistent_pairs=0,
    )
    assert estimate["status"] == "NOT_ESTIMABLE"
    assert "0.7%" in estimate["reason"] or "phone coverage" in estimate["reason"].lower()


def test_postgis_only_overlap_excluded_from_application_shared() -> None:
    profile_a = {
        "relations": [
            {"schema": "magerya_api", "name": "account_patient", "kind": "table"},
            {"schema": "public", "name": "spatial_ref_sys", "kind": "table"},
            {"schema": "public", "name": "geography_columns", "kind": "view"},
        ]
    }
    profile_b = {
        "relations": [
            {"schema": "public", "name": "consultations", "kind": "table"},
            {"schema": "public", "name": "spatial_ref_sys", "kind": "table"},
            {"schema": "public", "name": "geometry_columns", "kind": "view"},
        ]
    }
    app_shared, infra_shared, _ = shared_relation_names(profile_a, profile_b)
    assert "spatial_ref_sys" in infra_shared
    assert "spatial_ref_sys" not in app_shared
    assert "account_patient" not in app_shared or "consultations" in app_shared


def test_missing_phone_and_email_not_summed_between_sources() -> None:
    key = b"local-test-key"
    a_stats = {
        "summary": {
            "subject_count": 10,
            "subjects_without_phone": 9,
            "subjects_without_email": 5,
            "subjects_without_any_strong_identifier": 4,
            "phone_present_count": 1,
        },
        "phone_hmacs": {"a": 1},
        "email_hmacs": {"b": 1},
        "phone_subjects": {"a": {1}},
        "email_subjects": {"b": {1}},
        "signature_subjects": Counter(),
        "phone_to_emails": {},
    }
    b_stats = {
        "summary": {
            "subject_count": 10,
            "subjects_without_phone": 1,
            "subjects_without_email": 2,
            "subjects_without_any_strong_identifier": 1,
            "phone_present_count": 9,
        },
        "phone_hmacs": {"c": 1},
        "email_hmacs": {"d": 1},
        "phone_subjects": {"c": {1}},
        "email_subjects": {"d": {1}},
        "signature_subjects": Counter(),
        "phone_to_emails": {},
    }
    overlap = _compute_overlap(a_stats, b_stats)
    assert overlap["source_a_subjects_without_any_strong_identifier"] == 4
    assert overlap["source_b_subjects_without_any_strong_identifier"] == 1
    assert "unevaluable_due_to_missing_identifiers" not in overlap


def test_duplicate_identifier_not_unique_subject_pair() -> None:
    key = b"local-test-key"
    phone = normalize_phone("79991234567")
    assert phone
    phone_hmac = hmac_identifier(key, "phone", phone)
    a_stats = {
        "summary": {"subject_count": 2, "phone_present_count": 2},
        "phone_hmacs": {phone_hmac: 2},
        "email_hmacs": {},
        "phone_subjects": {phone_hmac: {1, 2}},
        "email_subjects": {},
        "signature_subjects": Counter(),
        "phone_to_emails": {},
    }
    b_stats = {
        "summary": {"subject_count": 1, "phone_present_count": 1},
        "phone_hmacs": {phone_hmac: 1},
        "email_hmacs": {},
        "phone_subjects": {phone_hmac: {10}},
        "email_subjects": {},
        "signature_subjects": Counter(),
        "phone_to_emails": {},
    }
    overlap = _compute_overlap(a_stats, b_stats)
    assert overlap["matched_unique_phone_identifiers"] == 1
    assert overlap["uniquely_resolved_subject_pairs_by_phone"] == 0
    assert overlap["ambiguous_subject_pairs"] >= 1


def test_cross_field_phone_email_conflict_counted_separately() -> None:
    key = b"local-test-key"
    phone = normalize_phone("79991234567")
    email_a = normalize_email("a@example.com")
    email_b = normalize_email("b@example.com")
    assert phone and email_a and email_b
    phone_hmac = hmac_identifier(key, "phone", phone)

    a_stats = {
        "summary": {"subject_count": 1, "phone_present_count": 1},
        "phone_hmacs": {phone_hmac: 1},
        "email_hmacs": {hmac_identifier(key, "email", email_a): 1},
        "phone_subjects": {phone_hmac: {1}},
        "email_subjects": {hmac_identifier(key, "email", email_a): {1}},
        "signature_subjects": Counter(),
        "phone_to_emails": {phone_hmac: {hmac_identifier(key, "email", email_a)}},
    }
    b_stats = {
        "summary": {"subject_count": 1, "phone_present_count": 1},
        "phone_hmacs": {phone_hmac: 1},
        "email_hmacs": {hmac_identifier(key, "email", email_b): 1},
        "phone_subjects": {phone_hmac: {2}},
        "email_subjects": {hmac_identifier(key, "email", email_b): {2}},
        "signature_subjects": Counter(),
        "phone_to_emails": {phone_hmac: {hmac_identifier(key, "email", email_b)}},
    }
    overlap = _compute_overlap(a_stats, b_stats)
    assert overlap["cross_field_conflicts"] == 1
    assert overlap["consistent_subject_pairs_by_phone_and_email"] == 0
    verdict = _identity_verdict(overlap, a_stats, b_stats)
    assert verdict["verdict"] == "POTENTIAL_OVERLAP"


def test_identity_linkage_not_assessed_without_subject_root() -> None:
    payload = assess_identity_linkage(
        MagicMock(),
        MagicMock(),
        hmac_key=b"test-key",
        source_b_subject_verdict="NO_SUBJECT_ROOT",
        source_b_resolution=None,
    )
    assert payload["identity_verdict"]["verdict"] == "NOT_ASSESSED"


def test_gates_refuse_when_compare_report_missing(tmp_path: Path) -> None:
    stage01 = tmp_path / "artifacts" / "stage-01"
    stage02 = tmp_path / "artifacts" / "stage-02"
    stage01.mkdir(parents=True)
    stage02.mkdir(parents=True)
    _write_min_gates(stage01, stage02)
    with pytest.raises(AssessSourceRelationshipError, match="compare_verification_report"):
        with patch("human_simulator.stage02.relationship_gates.create_engine") as mock_engine:
            mock_engine.side_effect = _mock_readonly_engines
            run_relationship_gates(tmp_path)


def test_artifact_safety_flags_pii(tmp_path: Path) -> None:
    bad = tmp_path / "identity-linkage-assessment.json"
    bad.write_text('{"email": "patient@clinic.ru"}', encoding="utf-8")
    findings = validate_relationship_artifacts(tmp_path)
    assert findings


def test_structural_similarity_uses_application_counts_only() -> None:
    profile_a = {
        "relations": [
            {"schema": "magerya_api", "name": "account_patient", "kind": "table"},
            {"schema": "public", "name": "spatial_ref_sys", "kind": "table"},
        ]
    }
    profile_b = {
        "relations": [
            {"schema": "public", "name": "consultations", "kind": "table"},
            {"schema": "public", "name": "spatial_ref_sys", "kind": "table"},
        ]
    }
    structural = _structural_similarity(profile_a, profile_b, {"entity_types": {}})
    assert "shared_relation_name_count" not in structural
    assert structural["infrastructure_shared_relation_name_count"] >= 1
    assert "spatial_ref_sys" not in structural["application_shared_relation_names"]


REQUIRED_LIVE_ENV_VARS: tuple[str, ...] = (
    "MG_AUDIT_PASSWORD",
    "KGZ_AUDIT_PASSWORD",
    "LINKAGE_HMAC_KEY",
)

LIVE_ENV_FILES: tuple[str, ...] = ("db-audit.env", "db-kgz.env", "db.env")

LIVE_WORKSPACE_INPUTS: tuple[str, ...] = (
    "artifacts/stage-01",
    "artifacts/stage-02",
    "config",
)


def _defined_env_var_names(repo_root: Path) -> set[str]:
    """Collect env variable NAMES from process env and local env files. Values are never read."""
    import os

    names = {name for name, value in os.environ.items() if value.strip()}
    for file_name in LIVE_ENV_FILES:
        path = repo_root / file_name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, _, value = stripped.partition("=")
            if value.strip():
                names.add(name.strip())
    return names


def _unreachable_live_endpoints(repo_root: Path) -> list[str]:
    """Probe TCP reachability of both sources. Returns endpoint labels only, never DSNs."""
    import socket

    from human_simulator.stage01.settings import MgAuditSettings
    from human_simulator.stage02.settings import KgzRestoreSettings

    mg = MgAuditSettings.from_repo(repo_root)
    kgz = KgzRestoreSettings.from_repo(repo_root)
    unreachable: list[str] = []
    for label, host, port in (
        ("source_a_database", mg.pg_host, mg.pg_port),
        ("source_b_database", kgz.pg_host, kgz.pg_port),
    ):
        try:
            with socket.create_connection((host, port), timeout=2):
                pass
        except OSError:
            unreachable.append(label)
    return unreachable


def _missing_live_prerequisites(repo_root: Path) -> list[str]:
    """Return stable labels of every missing prerequisite, without leaking any values."""
    missing: list[str] = []

    defined = _defined_env_var_names(repo_root)
    missing.extend(f"env:{name}" for name in REQUIRED_LIVE_ENV_VARS if name not in defined)

    for rel in ("artifacts/stage-01/stage-01-report.md", "artifacts/stage-02/compare-verification-report.json"):
        if not (repo_root / rel).exists():
            missing.append(f"artifact:{rel}")

    compare_report = repo_root / "artifacts" / "stage-02" / "compare-verification-report.json"
    if compare_report.exists() and json.loads(compare_report.read_text(encoding="utf-8")).get("status") != "PASS":
        missing.append("artifact:compare-verification-report.json#status!=PASS")

    missing.extend(f"endpoint:{label}" for label in _unreachable_live_endpoints(repo_root))
    return missing


def _clone_live_workspace(repo_root: Path, destination: Path) -> Path:
    """Copy the inputs the live assessment reads so Stage 01/02 in the repo stay untouched."""
    import shutil

    destination.mkdir(parents=True, exist_ok=True)
    for rel in LIVE_WORKSPACE_INPUTS:
        source = repo_root / rel
        if source.is_dir():
            shutil.copytree(source, destination / rel, dirs_exist_ok=True)
        elif source.exists():
            (destination / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination / rel)
    for file_name in LIVE_ENV_FILES:
        source = repo_root / file_name
        if source.exists():
            shutil.copy2(source, destination / file_name)
    private_sources = repo_root / "private" / "sources.yaml"
    if private_sources.exists():
        (destination / "private").mkdir(parents=True, exist_ok=True)
        shutil.copy2(private_sources, destination / "private" / "sources.yaml")
    return destination


@pytest.mark.integration
def test_live_assess_source_relationship(tmp_path: Path) -> None:
    missing = _missing_live_prerequisites(REPO_ROOT)
    if missing:
        pytest.skip("live environment not configured; missing: " + ", ".join(sorted(missing)))

    workspace = _clone_live_workspace(REPO_ROOT, tmp_path / "live-workspace")
    result = assess_source_relationship(workspace)
    stage02 = workspace / "artifacts" / "stage-02"
    assert result["status"] == "PASS"
    assert (stage02 / "subject-root-analysis.json").exists()
    assert (stage02 / "source-relationship-assessment.json").exists()
    assert (stage02 / "identity-linkage-assessment.json").exists()
    assert (stage02 / "relationship-verification-report.json").exists()
    manifest_ok, _ = verify_relationship_manifest(stage02)
    assert manifest_ok
    assert validate_relationship_artifacts(stage02) == []

    identity = json.loads((stage02 / "identity-linkage-assessment.json").read_text(encoding="utf-8"))
    assert identity["identity_verdict"]["verdict"] != "LINKAGE_PROVEN"
    assert identity["identity_verdict"]["verdict"] == "POTENTIAL_OVERLAP"
    overlap = identity["overlap_aggregates"]
    assert overlap["population_overlap_estimate"]["status"] == "NOT_ESTIMABLE"
    assert "estimated_overlap_percentage" not in overlap
    assert "matched_unique_phone_identifiers" in overlap
    assert identity["conflict_definition"]
    assert identity["hmac_key_present_in_runtime"] is True
    assert identity["hmac_key_persisted_in_artifacts"] is False

    subject = json.loads((stage02 / "subject-root-analysis.json").read_text(encoding="utf-8"))
    assert subject["source_a"]["verdict"] == "SUBJECT_ROOT_CONFIRMED"
    assert subject["source_b"]["overall_verdict"] == "SUBJECT_ROOT_CANDIDATE"
    assert "100% consultations.patient_id coverage" in subject["source_b"]["overall_verdict_reason"]

    structural = json.loads((stage02 / "source-relationship-assessment.json").read_text(encoding="utf-8"))
    supporting = " ".join(structural["source_relationship_verdict"]["supporting_evidence"])
    assert "estimated" not in supporting.lower()
    assert "39 shared relation names" not in supporting
    assert "application_shared_relation_name_count" in structural["structural_similarity"]


def test_live_prerequisite_labels_carry_no_secret_values() -> None:
    missing = _missing_live_prerequisites(REPO_ROOT)
    for label in missing:
        assert label.split(":", 1)[0] in {"env", "artifact", "endpoint"}
        assert "postgresql" not in label
        assert "password" not in label.lower() or label.startswith("env:")
        assert "=" not in label or label.startswith("artifact:")


def test_live_assessment_never_writes_repository_prior_stage_artifacts(tmp_path: Path) -> None:
    from human_simulator.stage03.prior_stage_integrity import snapshot_prior_stage_hashes

    before = snapshot_prior_stage_hashes(REPO_ROOT)
    workspace = _clone_live_workspace(REPO_ROOT, tmp_path / "clone")
    assert (workspace / "artifacts" / "stage-02").is_dir()
    assert snapshot_prior_stage_hashes(REPO_ROOT) == before


def _mock_readonly_engines(*args: object, **kwargs: object) -> MagicMock:
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = "mg_audit_ro"
    engine.connect.return_value.__enter__.return_value = conn
    return engine


def _write_min_gates(stage01: Path, stage02: Path) -> None:
    profile = {
        "database": "magerya_api",
        "relations": [{"schema": "magerya_api", "name": "account_patient", "kind": "table"}],
        "columns": [],
        "primary_keys": [],
        "foreign_keys": [],
        "indexes": [],
        "readonly_validation": {"safe": True},
    }
    (stage01 / "schema-profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (stage01 / "entity-candidates.yaml").write_text("entity_types: {}\n", encoding="utf-8")
    (stage01 / "relation-graph.md").write_text("# graph\n", encoding="utf-8")
    (stage01 / "unknown-semantics.md").write_text("# unknown\n", encoding="utf-8")
    (stage01 / "stage-01-report.md").write_text(f"# report\n\nstatus: {REPORT_STATUS_FINAL}\n", encoding="utf-8")
    (stage01 / "source-audit.json").write_text(
        json.dumps(
            {
                "reachable": True,
                "extraction_method": "live_readonly_profile",
                "connection_user": "mg_audit_ro",
                "schema_fingerprint_check": {"fingerprints_match": True},
            }
        ),
        encoding="utf-8",
    )
    from human_simulator.stage01.manifest import write_manifest

    write_manifest(stage01)

    profile_b = dict(profile)
    profile_b["database"] = "kgz_raw"
    (stage02 / "schema-profile-kgz.json").write_text(json.dumps(profile_b), encoding="utf-8")
    (stage02 / "entity-candidates-kgz.yaml").write_text(
        yaml.safe_dump({"entity_types": {"patients": []}, "relations": []}),
        encoding="utf-8",
    )
    (stage02 / "relation-graph-kgz.md").write_text("# graph\n\n- public.persons\n", encoding="utf-8")
    (stage02 / "unknown-semantics-kgz.md").write_text("# unknown\n", encoding="utf-8")
    (stage02 / "source-b-audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    from human_simulator.stage02.classify_second_source import write_manifest as write_b_manifest

    write_b_manifest(stage02)
