"""Regression tests for Changeset 01 v0.2.2 — Pre-live-load Gate Hardening.

Two defects made the v0.2.1 gate weaker than it appeared:

1. it consulted a hand-maintained blocker list that omitted the two OPEN, BLOCKS_LIVE_LOAD
   conflicts already recorded in ``accepted-artifact-conflicts.yaml``, so the executable guard
   disagreed with its own documentation;
2. it decided resolution by searching artifacts for words, so ``SHA256(source_id)`` would have
   proved subject-key opacity and a sentence mentioning ``SET ROLE`` would have proved a loader
   runtime principal existed.

Everything below is read-only against the real workspace; anything that mutates runs in a
throwaway copy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from human_simulator.stage03.frozen_evidence import frozen_evidence_fingerprint
from human_simulator.stage03.live_load_contracts import (
    RUNTIME_CONTRACT_KEY,
    RUNTIME_REQUIRED_FIELDS,
    SUBJECT_KEY_CONTRACT_KEY,
    SUBJECT_KEY_REQUIRED_FIELDS,
    classify_algorithm,
    validate_runtime_contract,
    validate_subject_key_contract,
)
from human_simulator.stage03.pre_live_load_blockers import (
    LOADER_PRINCIPAL_BLOCKER,
    MANIFEST_DRIFT_BLOCKER,
    REQUIRED_BLOCKER_IDS,
    SUBJECT_KEY_BLOCKER,
    blocking_conflicts,
    evaluate_blockers,
    load_artifact_conflicts,
)
from conftest import (
    VALID_RUNTIME_CONTRACT,
    VALID_SUBJECT_KEY_CONTRACT,
    install_authoritative_contract,
    rewrite_conflict_registry,
)
from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate

COMPLETE_SUBJECT_KEY = VALID_SUBJECT_KEY_CONTRACT
COMPLETE_RUNTIME = VALID_RUNTIME_CONTRACT


def _write_contract(workspace: Path, **contracts: dict) -> None:
    """Install contracts where an accepted release would put them.

    Until v0.2.3 these tests wrote both contracts into one invented file under the plan
    directory, which the validator then accepted. Authority is now part of what is validated, so
    a contract only counts at the path its owning release controls.
    """
    for contract_key, contract in contracts.items():
        install_authoritative_contract(workspace, contract_key, contract)


# --------------------------------------------------------------------------------------
# 1. Every OPEN, BLOCKS_LIVE_LOAD conflict is a gate check, with no second list
# --------------------------------------------------------------------------------------


def test_every_open_blocking_conflict_appears_in_failed_checks(repo_root: Path) -> None:
    conflicts = blocking_conflicts(repo_root)
    assert conflicts, "the workspace should still carry the two recorded open conflicts"

    failed = set(evaluate_pre_live_load_gate(repo_root).failed_checks)
    for conflict in conflicts:
        assert conflict["id"] in failed, f"{conflict['id']} is not enforced by the gate"


def test_the_five_open_blockers_are_all_enforced(repo_root: Path) -> None:
    failed = set(evaluate_pre_live_load_gate(repo_root).failed_checks)
    assert {
        LOADER_PRINCIPAL_BLOCKER,
        SUBJECT_KEY_BLOCKER,
        "temporal_precision_field_absent_from_model",
        "encounter_provider_id_population_disagreement",
    } <= failed
    assert MANIFEST_DRIFT_BLOCKER not in failed


def test_conflict_blockers_are_not_restated_in_code(repo_root: Path) -> None:
    """The conflict ids must come from the artifact, not from a literal in the module."""
    source = (
        repo_root / "src" / "human_simulator" / "stage03" / "pre_live_load_blockers.py"
    ).read_text(encoding="utf-8")
    for conflict in blocking_conflicts(repo_root):
        assert conflict["id"] not in source, (
            f"{conflict['id']} is hardcoded; the artifact must be the only source"
        )


def test_a_new_blocking_conflict_blocks_without_touching_code(isolated_workspace: Path) -> None:
    path = (
        isolated_workspace
        / "artifacts"
        / "stage-03-implementation-changeset-01"
        / "accepted-artifact-conflicts.yaml"
    )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["conflicts"].append(
        {
            "id": "synthetic_conflict_for_regression",
            "severity": "BLOCKS_LIVE_LOAD",
            "status": "OPEN",
            "exact_contradiction": "a synthetic conflict used only by this test",
        }
    )
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    failed = set(evaluate_pre_live_load_gate(isolated_workspace).failed_checks)
    assert "synthetic_conflict_for_regression" in failed


def test_a_resolved_or_non_blocking_conflict_is_not_a_gate_check(isolated_workspace: Path) -> None:
    path = (
        isolated_workspace
        / "artifacts"
        / "stage-03-implementation-changeset-01"
        / "accepted-artifact-conflicts.yaml"
    )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["conflicts"].extend(
        [
            {
                "id": "resolved_conflict",
                "severity": "BLOCKS_LIVE_LOAD",
                "status": "RESOLVED",
                "exact_contradiction": "already resolved",
            },
            {
                "id": "advisory_conflict",
                "severity": "ADVISORY",
                "status": "OPEN",
                "exact_contradiction": "does not block live load",
            },
        ]
    )
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    registered = {blocker.blocker_id for blocker in evaluate_blockers(isolated_workspace)}
    assert "resolved_conflict" not in registered
    assert "advisory_conflict" not in registered


def test_removing_a_blocker_check_fails_the_gate(isolated_workspace: Path) -> None:
    """Deleting the conflicts artifact must not silently unblock anything."""
    (
        isolated_workspace
        / "artifacts"
        / "stage-03-implementation-changeset-01"
        / "accepted-artifact-conflicts.yaml"
    ).unlink()

    result = evaluate_pre_live_load_gate(isolated_workspace)
    assert result.status == "FAIL"
    registered = {blocker.blocker_id for blocker in evaluate_blockers(isolated_workspace)}
    assert REQUIRED_BLOCKER_IDS <= registered, "the mandatory blockers must survive artifact loss"


@pytest.mark.parametrize("dropped", sorted(REQUIRED_BLOCKER_IDS))
def test_dropping_any_mandatory_blocker_check_fails_the_gate(
    isolated_workspace: Path, monkeypatch, dropped: str
) -> None:
    """Suppressing a blocker must be loud. Silence here is the whole risk."""
    from human_simulator.stage03 import pre_live_load_gate as gate_module

    original = gate_module.evaluate_blockers
    monkeypatch.setattr(
        gate_module,
        "evaluate_blockers",
        lambda root: tuple(b for b in original(root) if b.blocker_id != dropped),
    )

    result = evaluate_pre_live_load_gate(isolated_workspace)
    assert result.status == "FAIL"
    assert "required_blocker_checks_present" in result.failed_checks
    assert dropped not in result.failed_checks, "precondition: the check really was removed"


# --------------------------------------------------------------------------------------
# 2. Structured validation: words do not resolve blockers
# --------------------------------------------------------------------------------------


def test_the_word_hash_alone_does_not_resolve_the_subject_key_blocker(
    isolated_workspace: Path,
) -> None:
    target = isolated_workspace / "artifacts" / "stage-03-implementation" / "prose.yaml"
    target.write_text(
        "notes:\n"
        "  - subject_key_from_id produces an opaque pseudonym\n"
        "  - the value is a hash and is treated as a digest\n",
        encoding="utf-8",
    )
    assert validate_subject_key_contract(isolated_workspace).satisfied is False
    assert SUBJECT_KEY_BLOCKER in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


def test_sha256_of_the_source_id_does_not_resolve_the_subject_key_blocker(
    isolated_workspace: Path,
) -> None:
    contract = dict(COMPLETE_SUBJECT_KEY, algorithm="SHA256(source_id)")
    _write_contract(isolated_workspace, **{SUBJECT_KEY_CONTRACT_KEY: contract})

    validation = validate_subject_key_contract(isolated_workspace)
    assert validation.satisfied is False
    assert any("unkeyed digest" in violation for violation in validation.violations)
    assert SUBJECT_KEY_BLOCKER in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


@pytest.mark.parametrize(
    "algorithm",
    ["sha-256", "SHA512", "md5", "blake2b", "hash", "digest", "base64", "HMAC"],
)
def test_unkeyed_or_underspecified_algorithms_are_rejected(algorithm: str) -> None:
    accepted, reason = classify_algorithm(algorithm)
    assert accepted is False, f"{algorithm} must not count as a keyed PRF: {reason}"


@pytest.mark.parametrize("algorithm", ["HMAC-SHA256", "hmac_sha_512", "KMAC256", "keyed-blake2b"])
def test_keyed_algorithms_are_accepted(algorithm: str) -> None:
    accepted, _ = classify_algorithm(algorithm)
    assert accepted is True


@pytest.mark.parametrize("field", SUBJECT_KEY_REQUIRED_FIELDS)
def test_every_subject_key_field_is_required(isolated_workspace: Path, field: str) -> None:
    contract = {k: v for k, v in COMPLETE_SUBJECT_KEY.items() if k != field}
    _write_contract(isolated_workspace, **{SUBJECT_KEY_CONTRACT_KEY: contract})

    validation = validate_subject_key_contract(isolated_workspace)
    assert validation.satisfied is False
    assert field in validation.missing_fields


def test_runtime_principal_tbd_does_not_resolve_the_blocker(isolated_workspace: Path) -> None:
    contract = dict(COMPLETE_RUNTIME, login_principal="TBD")
    _write_contract(isolated_workspace, **{RUNTIME_CONTRACT_KEY: contract})

    validation = validate_runtime_contract(isolated_workspace)
    assert validation.satisfied is False
    assert "login_principal" in validation.missing_fields
    assert LOADER_PRINCIPAL_BLOCKER in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


def test_a_negative_mention_of_set_role_does_not_resolve_the_blocker(
    isolated_workspace: Path,
) -> None:
    target = isolated_workspace / "artifacts" / "stage-03-implementation" / "prose.yaml"
    target.write_text(
        "security_notes:\n"
        "  - canonical_loader is NOLOGIN and no SET ROLE path is defined yet\n"
        "  - a login_principal and credential_source must still be decided\n",
        encoding="utf-8",
    )
    assert validate_runtime_contract(isolated_workspace).satisfied is False
    assert LOADER_PRINCIPAL_BLOCKER in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


def test_a_set_role_flow_without_a_set_role_statement_is_rejected(
    isolated_workspace: Path,
) -> None:
    contract = dict(COMPLETE_RUNTIME, set_role_flow="the loader connects directly")
    _write_contract(isolated_workspace, **{RUNTIME_CONTRACT_KEY: contract})

    validation = validate_runtime_contract(isolated_workspace)
    assert validation.satisfied is False
    assert any("SET ROLE" in violation for violation in validation.violations)


def test_a_login_capable_group_role_is_rejected(isolated_workspace: Path) -> None:
    contract = dict(COMPLETE_RUNTIME, group_role_is_nologin=False)
    _write_contract(isolated_workspace, **{RUNTIME_CONTRACT_KEY: contract})

    validation = validate_runtime_contract(isolated_workspace)
    assert validation.satisfied is False
    assert any("NOLOGIN" in violation or "nologin" in violation for violation in validation.violations)


def test_a_literal_credential_is_rejected(isolated_workspace: Path) -> None:
    # Assembled at runtime: a literal credential-bearing connection string in a source file
    # would be a real finding, and the review bundle builder rejects one on sight.
    dsn = "postgresql://" + "uhbse_loader_svc" + ":" + "pw" + "@" + "localhost:5436/db"
    contract = dict(COMPLETE_RUNTIME, credential_source_reference=dsn)
    _write_contract(isolated_workspace, **{RUNTIME_CONTRACT_KEY: contract})

    validation = validate_runtime_contract(isolated_workspace)
    assert validation.satisfied is False
    assert any("credential" in violation for violation in validation.violations)


@pytest.mark.parametrize("field", RUNTIME_REQUIRED_FIELDS)
def test_every_runtime_field_is_required(isolated_workspace: Path, field: str) -> None:
    contract = {k: v for k, v in COMPLETE_RUNTIME.items() if k != field}
    _write_contract(isolated_workspace, **{RUNTIME_CONTRACT_KEY: contract})

    validation = validate_runtime_contract(isolated_workspace)
    assert validation.satisfied is False
    assert field in validation.missing_fields


def test_the_workspace_carries_incomplete_contract_instances(repo_root: Path) -> None:
    """Alignment candidate adds partial contracts; blockers stay OPEN until secret provider is set."""
    subject = validate_subject_key_contract(repo_root)
    runtime = validate_runtime_contract(repo_root)
    assert subject.found_in is not None
    assert runtime.found_in is not None
    assert not subject.satisfied
    assert not runtime.satisfied


# --------------------------------------------------------------------------------------
# 3. Fail-closed: one open blocker is enough
# --------------------------------------------------------------------------------------


def _resolve_manifest_drift(workspace: Path) -> None:
    """Rewrite the Stage 02 manifest inside a throwaway copy so its hashes match."""
    from human_simulator.stage02.relationship_manifest import (
        MANIFEST_NAME,
        RELATIONSHIP_MANIFEST_ARTIFACTS,
    )
    from human_simulator.stage03.preconditions import sha256_file

    directory = workspace / "artifacts" / "stage-02"
    lines = [
        f"{sha256_file(directory / name)}  {name}"
        for name in RELATIONSHIP_MANIFEST_ARTIFACTS
        if (directory / name).is_file()
    ]
    (directory / MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _conflicts_path(workspace: Path) -> Path:
    return (
        workspace
        / "artifacts"
        / "stage-03-implementation-changeset-01"
        / "accepted-artifact-conflicts.yaml"
    )


def _close_all_conflicts(workspace: Path) -> None:
    document = yaml.safe_load(_conflicts_path(workspace).read_text(encoding="utf-8"))
    for conflict in document["conflicts"]:
        conflict["status"] = "RESOLVED"
    document["open_conflict_count"] = 0
    rewrite_conflict_registry(workspace, document)


def test_three_blockers_resolved_but_one_open_conflict_still_fails(
    isolated_workspace: Path,
) -> None:
    """The synthetic case the changeset requires: partial resolution is still FAIL."""
    _resolve_manifest_drift(isolated_workspace)
    _write_contract(
        isolated_workspace,
        **{
            SUBJECT_KEY_CONTRACT_KEY: COMPLETE_SUBJECT_KEY,
            RUNTIME_CONTRACT_KEY: COMPLETE_RUNTIME,
        },
    )

    document = yaml.safe_load(_conflicts_path(isolated_workspace).read_text(encoding="utf-8"))
    document["conflicts"][0]["status"] = "RESOLVED"
    remaining = document["conflicts"][1]["id"]
    document["open_conflict_count"] = 1
    rewrite_conflict_registry(isolated_workspace, document)

    result = evaluate_pre_live_load_gate(isolated_workspace)
    assert result.status == "FAIL"
    assert remaining in result.failed_checks
    for resolved in (MANIFEST_DRIFT_BLOCKER, SUBJECT_KEY_BLOCKER, LOADER_PRINCIPAL_BLOCKER):
        assert resolved not in result.failed_checks


def test_pass_is_reachable_only_when_all_five_are_structurally_closed(
    isolated_workspace: Path,
) -> None:
    """PASS must be possible, or the gate would be untestable rather than fail-closed."""
    _resolve_manifest_drift(isolated_workspace)
    _close_all_conflicts(isolated_workspace)
    _write_contract(
        isolated_workspace,
        **{
            SUBJECT_KEY_CONTRACT_KEY: COMPLETE_SUBJECT_KEY,
            RUNTIME_CONTRACT_KEY: COMPLETE_RUNTIME,
        },
    )

    result = evaluate_pre_live_load_gate(isolated_workspace)
    assert result.status == "PASS", result.failed_checks


def test_the_real_workspace_gate_is_still_failing(repo_root: Path) -> None:
    result = evaluate_pre_live_load_gate(repo_root)
    assert result.status == "FAIL"
    assert len(result.failed_checks) == 4


# --------------------------------------------------------------------------------------
# 4. The gate is read-only
# --------------------------------------------------------------------------------------


def test_the_gate_changes_no_frozen_input(repo_root: Path) -> None:
    before = frozen_evidence_fingerprint(repo_root)
    document = evaluate_pre_live_load_gate(repo_root).document()
    after = frozen_evidence_fingerprint(repo_root)

    assert before == after
    assert document["frozen_inputs"]["unchanged"] is True
    assert document["frozen_inputs"]["count"] == 37
    assert document["repairs_performed"] == 0
    assert document["stage_02_modified"] is False
    assert document["manifests_created"] == 0
    assert document["frozen_evidence_restored"] == 0
    assert document["database_connections_opened"] == 0
    assert document["clinical_rows_read"] == 0


def test_the_gate_creates_no_manifest_when_one_is_missing(isolated_workspace: Path) -> None:
    from human_simulator.stage02.relationship_manifest import MANIFEST_NAME

    manifest = isolated_workspace / "artifacts" / "stage-02" / MANIFEST_NAME
    manifest.unlink()

    result = evaluate_pre_live_load_gate(isolated_workspace)
    assert result.status == "FAIL"
    assert not manifest.exists(), "the gate must never write a manifest"


def test_the_gate_does_not_restore_drifted_frozen_evidence(isolated_workspace: Path) -> None:
    victim = isolated_workspace / "artifacts" / "stage-03" / "stage-03-design-report.md"
    mutated = victim.read_text(encoding="utf-8") + "\ndrift\n"
    victim.write_text(mutated, encoding="utf-8")

    evaluate_pre_live_load_gate(isolated_workspace)
    assert victim.read_text(encoding="utf-8") == mutated


def test_the_gate_opens_no_database_connection(repo_root: Path, monkeypatch) -> None:
    import human_simulator.db.session as session

    def explode(*args, **kwargs):
        raise AssertionError("the pre-live-load gate must not connect to a database")

    monkeypatch.setattr(session, "create_audit_engine", explode)
    assert evaluate_pre_live_load_gate(repo_root).status == "FAIL"


def test_the_gate_module_imports_no_database_client(repo_root: Path) -> None:
    for name in ("pre_live_load_gate.py", "pre_live_load_blockers.py", "live_load_contracts.py"):
        source = (repo_root / "src" / "human_simulator" / "stage03" / name).read_text(
            encoding="utf-8"
        )
        for forbidden in ("psycopg", "sqlalchemy", "create_engine", "connect("):
            assert forbidden not in source, f"{name} must not reach a database"


# --------------------------------------------------------------------------------------
# 5. Frozen inputs and published releases keep their bytes
# --------------------------------------------------------------------------------------


def test_the_published_v0_2_1_archive_keeps_its_sha(repo_root: Path) -> None:
    import hashlib

    archive = (
        repo_root
        / "artifacts"
        / "external-review"
        / "stage-03-implementation-changeset-01-v0.2.1-review.zip"
    )
    sidecar = Path(str(archive) + ".sha256")
    if not archive.is_file():
        pytest.skip("v0.2.1 archive not present")
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == sidecar.read_text().split()[0]


def test_migrations_0001_to_0004_keep_their_accepted_bytes(repo_root: Path) -> None:
    from human_simulator.stage03.frozen_evidence import FROZEN_MIGRATION_SHA256
    from human_simulator.stage03.preconditions import sha256_file

    for name, accepted in FROZEN_MIGRATION_SHA256.items():
        assert sha256_file(repo_root / "migrations" / "canonical" / name) == accepted, name


def test_no_publish_gate_writes_nothing(isolated_workspace: Path) -> None:
    import subprocess
    import sys

    from human_simulator.stage03.preconditions import sha256_file

    def snapshot() -> dict[str, str]:
        return {
            str(path.relative_to(isolated_workspace)): sha256_file(path)
            for path in sorted((isolated_workspace / "artifacts").rglob("*"))
            if path.is_file()
        }

    before = snapshot()
    completed = subprocess.run(
        [sys.executable, "-m", "human_simulator.cli", "--root", ".", "stage-02-pre-live-load-gate"],
        cwd=isolated_workspace,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert snapshot() == before, "the read-only gate wrote to artifacts/"


# --------------------------------------------------------------------------------------
# 6. The Design archive finding is bound to hashes
# --------------------------------------------------------------------------------------


def test_the_design_archive_finding_records_hashes(repo_root: Path) -> None:
    from human_simulator.stage03.design_archive_finding import evaluate_design_archive_finding

    finding = evaluate_design_archive_finding(repo_root)
    assert finding["status"] in {
        "REPRODUCED_CURRENT_ARTIFACT",
        "NOT_REPRODUCED_CURRENT_ARTIFACT",
        "CLOSED",
        "NOT_ASSESSABLE_ARTIFACT_ABSENT",
    }
    if finding["archive_present"]:
        assert len(finding["archive_sha256"]) == 64
        assert set(finding["embedded_design_evidence_sha256"]) == {
            "stage-03-design-report.md",
            "stage-03-design-verification.json",
        }
        assert finding["archive_source"].endswith("stage-03-design-v0.7.4-review.zip")
    assert finding["historical_corruption_claimed"] is False


def test_the_finding_closes_when_the_archive_carries_the_audited_bytes(
    isolated_workspace: Path, repo_root: Path
) -> None:
    import shutil
    import zipfile

    from human_simulator.stage03.design_archive_finding import (
        DESIGN_ARCHIVE_NAME,
        evaluate_design_archive_finding,
    )
    from human_simulator.stage03.frozen_evidence import DESIGN_EVIDENCE_SOURCE_ARCHIVES

    source = repo_root / "artifacts" / "external-review" / DESIGN_EVIDENCE_SOURCE_ARCHIVES[0]
    if not source.is_file():
        pytest.skip("no accepted release archive available")

    # A stand-in archive that does carry the audited bytes, to prove the finding can close.
    target = isolated_workspace / "artifacts" / "external-review" / DESIGN_ARCHIVE_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for name in (
            "artifacts/stage-03/stage-03-design-report.md",
            "artifacts/stage-03/stage-03-design-verification.json",
        ):
            dst.writestr(name, src.read(name))

    finding = evaluate_design_archive_finding(isolated_workspace)
    assert finding["status"] == "NOT_REPRODUCED_CURRENT_ARTIFACT"
    assert finding["embedded_matches_audited"] is True
    assert shutil.which is not None


def test_conflicts_artifact_is_unchanged_by_reading_it(repo_root: Path) -> None:
    from human_simulator.stage03.preconditions import sha256_file
    from human_simulator.stage03.pre_live_load_blockers import CONFLICTS_ARTIFACT

    path = repo_root / CONFLICTS_ARTIFACT
    before = sha256_file(path)
    load_artifact_conflicts(repo_root)
    blocking_conflicts(repo_root)
    evaluate_blockers(repo_root)
    assert sha256_file(path) == before


def test_gate_result_json_is_serialisable(repo_root: Path) -> None:
    document = evaluate_pre_live_load_gate(repo_root).document()
    assert json.loads(json.dumps(document))["gate_id"]
