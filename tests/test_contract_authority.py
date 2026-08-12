"""Regression tests for Changeset 01 v0.2.3 — Contract Authority and Semantic Validation.

v0.2.2 required a complete structured contract before a blocker could close, which was a real
improvement over word search. It left two ways to obtain a false PASS:

* **authority** — a contract was accepted from any YAML file under the Stage 03 directories,
  including the changeset's own. A changeset could have written the contract that unblocked it.
* **meaning** — fields were checked for presence and shape, not for what they said.
  ``classify_algorithm`` matched by substring, so ``not-hmac-sha256`` and ``hmac-sha256-unkeyed``
  both read as keyed PRFs, and any ``SET ROLE`` satisfied the loader flow, including
  ``SET ROLE postgres``.

Every mutation below runs against a throwaway copy of the workspace. Nothing here resolves a
blocker in the real one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import install_authoritative_contract, rewrite_conflict_registry
from human_simulator.stage03.conflict_registry import (
    CONFLICTS_ARTIFACT,
    validate_conflict_registry,
)
from human_simulator.stage03.live_load_contracts import (
    CONTRACT_AUTHORITIES,
    FORBIDDEN_CONTRACT_DIRS,
    RUNTIME_CONTRACT_KEY,
    SUBJECT_KEY_CONTRACT_KEY,
    classify_algorithm,
    validate_runtime_contract,
    validate_subject_key_contract,
)
from human_simulator.stage03.pre_live_load_blockers import (
    LOADER_PRINCIPAL_BLOCKER,
    SUBJECT_KEY_BLOCKER,
)
from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate

REGISTRY_CHECK = "accepted_artifact_conflict_registry_valid"
AMBIGUITY_CHECK = "contract_definitions_are_unambiguous"


def _registry_path(workspace: Path) -> Path:
    return workspace / CONFLICTS_ARTIFACT


def _rewrite_registry(workspace: Path, document: object) -> None:
    """Write the registry and re-seal the changeset manifest, as a real edit would."""
    rewrite_conflict_registry(workspace, document)


# ---------------------------------------------------------------------------------------
# Authority: where a contract may come from
# ---------------------------------------------------------------------------------------


def test_the_changeset_directory_can_never_authorise_a_contract(
    isolated_workspace: Path, valid_subject_key_contract: dict, valid_runtime_contract: dict
) -> None:
    """A changeset writing the contract that unblocks the changeset is self-authorisation."""
    target = isolated_workspace / FORBIDDEN_CONTRACT_DIRS[0] / "loader-contracts.yaml"
    target.write_text(
        yaml.safe_dump(
            {
                SUBJECT_KEY_CONTRACT_KEY: valid_subject_key_contract,
                RUNTIME_CONTRACT_KEY: valid_runtime_contract,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    subject_key = validate_subject_key_contract(isolated_workspace)
    runtime = validate_runtime_contract(isolated_workspace)
    assert subject_key.satisfied is False
    assert runtime.satisfied is False
    for validation in (subject_key, runtime):
        assert any("changeset directory" in reason for reason in validation.authority_failures)

    failed = set(evaluate_pre_live_load_gate(isolated_workspace).failed_checks)
    assert {SUBJECT_KEY_BLOCKER, LOADER_PRINCIPAL_BLOCKER} <= failed


@pytest.mark.parametrize(
    ("contract_key", "validator"),
    [
        (SUBJECT_KEY_CONTRACT_KEY, validate_subject_key_contract),
        (RUNTIME_CONTRACT_KEY, validate_runtime_contract),
    ],
)
def test_a_contract_outside_the_authoritative_path_is_refused(
    isolated_workspace: Path,
    contract_key: str,
    validator,
    valid_subject_key_contract: dict,
    valid_runtime_contract: dict,
) -> None:
    contract = (
        valid_subject_key_contract
        if contract_key == SUBJECT_KEY_CONTRACT_KEY
        else valid_runtime_contract
    )
    stray = isolated_workspace / "artifacts" / "stage-03-implementation" / "stray-contract.yaml"
    stray.write_text(yaml.safe_dump({contract_key: contract}, sort_keys=False), encoding="utf-8")

    validation = validator(isolated_workspace)
    assert validation.satisfied is False
    assert any("authoritative path" in reason for reason in validation.authority_failures)


def test_a_contract_absent_from_the_accepted_manifest_is_refused(
    isolated_workspace: Path, valid_runtime_contract: dict
) -> None:
    """Placement is not enough: the owning release must actually cover the file."""
    authority = CONTRACT_AUTHORITIES[RUNTIME_CONTRACT_KEY]
    install_authoritative_contract(
        isolated_workspace, RUNTIME_CONTRACT_KEY, valid_runtime_contract
    )
    manifest = isolated_workspace / authority.manifest_path
    kept = [
        line
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().endswith(authority.manifest_entry)
    ]
    manifest.write_text("\n".join(kept) + "\n", encoding="utf-8")

    validation = validate_runtime_contract(isolated_workspace)
    assert validation.satisfied is False
    assert any("not listed in" in reason for reason in validation.authority_failures)


def test_a_contract_whose_release_manifest_does_not_verify_is_refused(
    isolated_workspace: Path, valid_runtime_contract: dict
) -> None:
    authority = CONTRACT_AUTHORITIES[RUNTIME_CONTRACT_KEY]
    install_authoritative_contract(
        isolated_workspace, RUNTIME_CONTRACT_KEY, valid_runtime_contract
    )
    # Re-sealing covers the contract file; damaging a sibling breaks the release seal.
    sibling = isolated_workspace / authority.manifest_path.parent / "pilot-slice.yaml"
    sibling.write_text(sibling.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    validation = validate_runtime_contract(isolated_workspace)
    assert validation.satisfied is False
    assert validation.manifest_verified is False


def test_two_definitions_of_one_contract_are_ambiguous(
    isolated_workspace: Path, valid_subject_key_contract: dict
) -> None:
    install_authoritative_contract(
        isolated_workspace, SUBJECT_KEY_CONTRACT_KEY, valid_subject_key_contract
    )
    duplicate = isolated_workspace / "artifacts" / "stage-03" / "second-definition.yaml"
    duplicate.write_text(
        yaml.safe_dump({SUBJECT_KEY_CONTRACT_KEY: valid_subject_key_contract}, sort_keys=False),
        encoding="utf-8",
    )

    validation = validate_subject_key_contract(isolated_workspace)
    assert validation.ambiguous is True
    assert validation.definition_count == 2
    assert validation.satisfied is False

    result = evaluate_pre_live_load_gate(isolated_workspace)
    assert AMBIGUITY_CHECK in result.failed_checks
    assert SUBJECT_KEY_BLOCKER in result.failed_checks


def test_zero_definitions_is_open_not_ambiguous(repo_root: Path) -> None:
    for validation in (
        validate_subject_key_contract(repo_root),
        validate_runtime_contract(repo_root),
    ):
        assert validation.definition_count == 0
        assert validation.ambiguous is False
        assert validation.satisfied is False
    assert AMBIGUITY_CHECK not in evaluate_pre_live_load_gate(repo_root).failed_checks


def test_the_authoritative_paths_are_release_owned(repo_root: Path) -> None:
    for authority in CONTRACT_AUTHORITIES.values():
        assert (repo_root / authority.authoritative_path).is_file()
        listed = (repo_root / authority.manifest_path).read_text(encoding="utf-8")
        assert authority.manifest_entry in listed
        assert not str(authority.authoritative_path).startswith(
            str(FORBIDDEN_CONTRACT_DIRS[0])
        )


def test_recursive_discovery_is_gone(repo_root: Path) -> None:
    """Authority must never be inferred from a search hit."""
    source = (
        repo_root / "src" / "human_simulator" / "stage03" / "live_load_contracts.py"
    ).read_text(encoding="utf-8")
    assert "CONTRACT_AUTHORITIES" in source
    assert "authoritative_path" in source
    # The scope is still walked, but only to detect strays; authority comes from equality.
    assert "relative == authority.authoritative_path" in source


# ---------------------------------------------------------------------------------------
# Subject key semantics
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "algorithm",
    [
        "not-hmac-sha256",
        "not-hmac-sha256-unkeyed",
        "fake-hmac-sha256",
        "hmac-sha256-unkeyed",
        "hmac-sha256-like",
        "definitely-not-hmac-sha512",
        "HMAC",
        "hmac",
        "sha256",
        "sha-256",
        "sha512",
        "md5",
        "hash",
        "digest",
        "base64",
        "",
        "TBD",
    ],
)
def test_algorithm_names_that_are_not_canonical_identifiers_fail(algorithm: str) -> None:
    accepted, reason = classify_algorithm(algorithm)
    assert accepted is False, f"{algorithm!r} must not read as a keyed PRF: {reason}"


@pytest.mark.parametrize(
    "algorithm", ["HMAC-SHA256", "hmac_sha_512", "KMAC256", "keyed-blake2b", "hmac-sha3-256"]
)
def test_canonical_keyed_identifiers_are_accepted(algorithm: str) -> None:
    accepted, _ = classify_algorithm(algorithm)
    assert accepted is True


def _subject_key_violations(workspace: Path, contract: dict) -> tuple[str, ...]:
    install_authoritative_contract(workspace, SUBJECT_KEY_CONTRACT_KEY, contract)
    validation = validate_subject_key_contract(workspace)
    assert validation.satisfied is False
    return validation.violations + validation.missing_fields


def test_an_unkeyed_algorithm_keeps_the_blocker_open(
    isolated_workspace: Path, valid_subject_key_contract: dict
) -> None:
    contract = dict(valid_subject_key_contract, algorithm="not-hmac-sha256-unkeyed")
    violations = _subject_key_violations(isolated_workspace, contract)
    assert any("canonical keyed-PRF" in item for item in violations)
    assert SUBJECT_KEY_BLOCKER in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


def test_a_wrong_transformation_id_is_rejected(
    isolated_workspace: Path, valid_subject_key_contract: dict
) -> None:
    contract = dict(valid_subject_key_contract, transformation_id="some_other_transform")
    violations = _subject_key_violations(isolated_workspace, contract)
    assert any("transformation_id" in item for item in violations)


@pytest.mark.parametrize(
    "key_reference",
    ["hunter2", "the key is in the deployment notes", "0123456789abcdef" * 4, "s3cr3t-value"],
)
def test_a_literal_key_reference_is_rejected(
    isolated_workspace: Path, valid_subject_key_contract: dict, key_reference: str
) -> None:
    contract = dict(valid_subject_key_contract, key_reference=key_reference)
    violations = _subject_key_violations(isolated_workspace, contract)
    assert any("key_reference" in item for item in violations)


@pytest.mark.parametrize("collision", ["ignore", "continue", "overwrite", "log-and-continue"])
def test_collision_handling_that_lets_the_load_continue_is_rejected(
    isolated_workspace: Path, valid_subject_key_contract: dict, collision: str
) -> None:
    contract = dict(valid_subject_key_contract, collision_handling=collision)
    violations = _subject_key_violations(isolated_workspace, contract)
    assert any("collision_handling" in item for item in violations)


@pytest.mark.parametrize("key_version", ["latest", "current", "the newest one"])
def test_an_uncomparable_key_version_is_rejected(
    isolated_workspace: Path, valid_subject_key_contract: dict, key_version: str
) -> None:
    contract = dict(valid_subject_key_contract, key_version=key_version)
    violations = _subject_key_violations(isolated_workspace, contract)
    assert any("key_version" in item for item in violations)


def test_prose_input_encoding_is_rejected(
    isolated_workspace: Path, valid_subject_key_contract: dict
) -> None:
    contract = dict(
        valid_subject_key_contract, input_encoding="the utf-8 decimal string of the patient id"
    )
    violations = _subject_key_violations(isolated_workspace, contract)
    assert any("input_encoding" in item for item in violations)


def test_free_text_rotation_policy_is_rejected(
    isolated_workspace: Path, valid_subject_key_contract: dict
) -> None:
    contract = dict(valid_subject_key_contract, rotation_policy="rotate annually")
    violations = _subject_key_violations(isolated_workspace, contract)
    assert any("rotation_policy" in item for item in violations)


def test_the_valid_subject_key_contract_is_accepted(
    isolated_workspace: Path, valid_subject_key_contract: dict
) -> None:
    """The negatives above would be meaningless if nothing could pass."""
    install_authoritative_contract(
        isolated_workspace, SUBJECT_KEY_CONTRACT_KEY, valid_subject_key_contract
    )
    validation = validate_subject_key_contract(isolated_workspace)
    assert validation.satisfied is True, validation.summary
    assert SUBJECT_KEY_BLOCKER not in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


# ---------------------------------------------------------------------------------------
# Runtime principal semantics
# ---------------------------------------------------------------------------------------


def _runtime_violations(workspace: Path, contract: dict) -> tuple[str, ...]:
    install_authoritative_contract(workspace, RUNTIME_CONTRACT_KEY, contract)
    validation = validate_runtime_contract(workspace)
    assert validation.satisfied is False
    return validation.violations + validation.missing_fields


def test_the_login_principal_may_not_be_the_group_role(
    isolated_workspace: Path, valid_runtime_contract: dict
) -> None:
    contract = dict(valid_runtime_contract, login_principal="canonical_loader")
    violations = _runtime_violations(isolated_workspace, contract)
    assert any("login_principal" in item for item in violations)
    assert LOADER_PRINCIPAL_BLOCKER in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


@pytest.mark.parametrize("group_role", ["postgres", "canonical_owner", "public"])
def test_a_group_role_other_than_canonical_loader_is_rejected(
    isolated_workspace: Path, valid_runtime_contract: dict, group_role: str
) -> None:
    contract = dict(valid_runtime_contract, group_role=group_role)
    violations = _runtime_violations(isolated_workspace, contract)
    assert any("group_role" in item for item in violations)


@pytest.mark.parametrize(
    "flow",
    [
        "connect as uhbse_loader_svc, then SET ROLE postgres",
        "SET ROLE canonical_owner before loading",
        "the operator will SET ROLE as appropriate",
        "no SET ROLE path is defined yet",
    ],
)
def test_a_set_role_flow_naming_another_role_is_rejected(
    isolated_workspace: Path, valid_runtime_contract: dict, flow: str
) -> None:
    contract = dict(valid_runtime_contract, set_role_flow=flow)
    violations = _runtime_violations(isolated_workspace, contract)
    assert any("set_role_flow" in item for item in violations)


def test_a_literal_credential_is_rejected(
    isolated_workspace: Path, valid_runtime_contract: dict
) -> None:
    contract = dict(valid_runtime_contract, credential_source_reference="hunter2")
    violations = _runtime_violations(isolated_workspace, contract)
    assert any("credential_source_reference" in item for item in violations)


@pytest.mark.parametrize(
    "grants",
    [
        ["SUPERUSER"],
        ["ALL"],
        ["SELECT", "INSERT", "SUPERUSER"],
        ["ALL PRIVILEGES"],
        ["SELECT", "DELETE"],
        ["CREATEROLE"],
        ["BYPASSRLS"],
        ["CREATEDB"],
    ],
)
def test_excessive_grants_are_rejected(
    isolated_workspace: Path, valid_runtime_contract: dict, grants: list[str]
) -> None:
    contract = dict(valid_runtime_contract, minimal_grants=grants)
    violations = _runtime_violations(isolated_workspace, contract)
    assert any("minimal_grants" in item for item in violations)


def test_a_login_capable_group_role_is_rejected(
    isolated_workspace: Path, valid_runtime_contract: dict
) -> None:
    contract = dict(valid_runtime_contract, group_role_is_nologin=False)
    violations = _runtime_violations(isolated_workspace, contract)
    assert any("nologin" in item.lower() for item in violations)


def test_audit_identity_must_tie_session_user_to_the_principal(
    isolated_workspace: Path, valid_runtime_contract: dict
) -> None:
    contract = dict(valid_runtime_contract, audit_identity="the loader role is recorded")
    violations = _runtime_violations(isolated_workspace, contract)
    assert any("audit_identity" in item for item in violations)


def test_a_revocation_procedure_without_a_revoking_action_is_rejected(
    isolated_workspace: Path, valid_runtime_contract: dict
) -> None:
    contract = dict(
        valid_runtime_contract,
        rotation_and_revocation_procedure={
            "rotation": "quarterly",
            "revocation": "the security team will be informed",
        },
    )
    violations = _runtime_violations(isolated_workspace, contract)
    assert any("revocation" in item for item in violations)


def test_the_valid_runtime_contract_is_accepted(
    isolated_workspace: Path, valid_runtime_contract: dict
) -> None:
    install_authoritative_contract(
        isolated_workspace, RUNTIME_CONTRACT_KEY, valid_runtime_contract
    )
    validation = validate_runtime_contract(isolated_workspace)
    assert validation.satisfied is True, validation.summary
    assert (
        LOADER_PRINCIPAL_BLOCKER
        not in evaluate_pre_live_load_gate(isolated_workspace).failed_checks
    )


# ---------------------------------------------------------------------------------------
# Conflict registry validity
# ---------------------------------------------------------------------------------------


def test_the_real_registry_is_valid(repo_root: Path) -> None:
    validation = validate_conflict_registry(repo_root)
    assert validation.valid is True, validation.problems
    assert validation.manifest_match is True
    assert REGISTRY_CHECK not in evaluate_pre_live_load_gate(repo_root).failed_checks


def test_a_missing_registry_adds_a_failure_rather_than_removing_checks(
    isolated_workspace: Path,
) -> None:
    """The v0.2.2 hole: deleting the file removed two checks and left the gate looking better."""
    before = evaluate_pre_live_load_gate(isolated_workspace)
    _registry_path(isolated_workspace).unlink()
    after = evaluate_pre_live_load_gate(isolated_workspace)

    assert REGISTRY_CHECK in after.failed_checks
    assert "required_blocker_checks_present" not in after.failed_checks
    assert after.status == "FAIL"
    # Losing the registry must never make the gate report a smaller problem.
    assert len(after.failed_checks) >= len(before.failed_checks) - 2 + 1


def test_a_corrupt_yaml_registry_fails(isolated_workspace: Path) -> None:
    _rewrite_registry(isolated_workspace, "conflicts: [\n  - id: broken\n   severity: ??? : :\n")
    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert any("valid YAML" in problem for problem in validation.problems)
    assert REGISTRY_CHECK in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


def test_an_empty_conflicts_list_fails(isolated_workspace: Path) -> None:
    document = yaml.safe_load(_registry_path(isolated_workspace).read_text(encoding="utf-8"))
    document["conflicts"] = []
    document["open_conflict_count"] = 0
    _rewrite_registry(isolated_workspace, document)

    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert any("empty" in problem for problem in validation.problems)
    assert REGISTRY_CHECK in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


def test_a_missing_conflicts_key_fails(isolated_workspace: Path) -> None:
    document = yaml.safe_load(_registry_path(isolated_workspace).read_text(encoding="utf-8"))
    document.pop("conflicts")
    _rewrite_registry(isolated_workspace, document)

    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert any("conflicts key is absent" in problem for problem in validation.problems)


def test_a_conflicts_value_of_the_wrong_type_fails(isolated_workspace: Path) -> None:
    document = yaml.safe_load(_registry_path(isolated_workspace).read_text(encoding="utf-8"))
    document["conflicts"] = {"id": "not-a-list"}
    _rewrite_registry(isolated_workspace, document)

    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert any("not a list" in problem for problem in validation.problems)


@pytest.mark.parametrize("field", ["id", "severity", "status"])
def test_a_conflict_missing_a_required_field_fails(isolated_workspace: Path, field: str) -> None:
    document = yaml.safe_load(_registry_path(isolated_workspace).read_text(encoding="utf-8"))
    document["conflicts"][0].pop(field)
    _rewrite_registry(isolated_workspace, document)

    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert any(field in problem for problem in validation.problems)


def test_a_duplicate_conflict_id_fails(isolated_workspace: Path) -> None:
    document = yaml.safe_load(_registry_path(isolated_workspace).read_text(encoding="utf-8"))
    document["conflicts"].append(dict(document["conflicts"][0]))
    document["open_conflict_count"] = 3
    _rewrite_registry(isolated_workspace, document)

    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert any("duplicate" in problem for problem in validation.problems)


@pytest.mark.parametrize(
    ("field", "value"),
    [("severity", "MEDIUM"), ("severity", "blocks-live-load!"), ("status", "MAYBE"), ("status", "IN_PROGRESS")],
)
def test_an_unknown_severity_or_status_fails(
    isolated_workspace: Path, field: str, value: str
) -> None:
    document = yaml.safe_load(_registry_path(isolated_workspace).read_text(encoding="utf-8"))
    document["conflicts"][0][field] = value
    _rewrite_registry(isolated_workspace, document)

    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert any(f"unknown {field}" in problem for problem in validation.problems)
    assert REGISTRY_CHECK in evaluate_pre_live_load_gate(isolated_workspace).failed_checks


@pytest.mark.parametrize("recorded", [0, 1, 5, "two"])
def test_a_wrong_open_conflict_count_fails(isolated_workspace: Path, recorded: object) -> None:
    document = yaml.safe_load(_registry_path(isolated_workspace).read_text(encoding="utf-8"))
    document["open_conflict_count"] = recorded
    _rewrite_registry(isolated_workspace, document)

    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert any("open_conflict_count" in problem for problem in validation.problems)


def test_a_registry_that_does_not_match_the_changeset_manifest_fails(
    isolated_workspace: Path,
) -> None:
    path = _registry_path(isolated_workspace)
    path.write_text(path.read_text(encoding="utf-8") + "\n# edited without re-sealing\n", encoding="utf-8")

    validation = validate_conflict_registry(isolated_workspace)
    assert validation.valid is False
    assert validation.manifest_match is False
    assert any("manifest" in problem.lower() for problem in validation.problems)


def test_no_conflict_identifier_is_hardcoded_in_python(repo_root: Path) -> None:
    stage03 = repo_root / "src" / "human_simulator" / "stage03"
    identifiers = {entry["id"] for entry in validate_conflict_registry(repo_root).conflicts}
    assert identifiers
    for module in ("pre_live_load_blockers.py", "pre_live_load_gate.py", "conflict_registry.py"):
        source = (stage03 / module).read_text(encoding="utf-8")
        for identifier in identifiers:
            assert identifier not in source, f"{identifier} is hardcoded in {module}"


# ---------------------------------------------------------------------------------------
# The whole gate: PASS only when everything is genuinely resolved
# ---------------------------------------------------------------------------------------


def _reseal_stage_02_manifest(workspace: Path) -> None:
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


def _resolve_all_conflicts(workspace: Path) -> None:
    document = yaml.safe_load(_registry_path(workspace).read_text(encoding="utf-8"))
    for conflict in document["conflicts"]:
        conflict["status"] = "RESOLVED"
        conflict["resolved_by"] = "synthetic test release"
    document["open_conflict_count"] = 0
    _rewrite_registry(workspace, document)


def _fully_resolve(
    workspace: Path, subject_key: dict, runtime: dict
) -> None:
    _reseal_stage_02_manifest(workspace)
    install_authoritative_contract(workspace, SUBJECT_KEY_CONTRACT_KEY, subject_key)
    install_authoritative_contract(workspace, RUNTIME_CONTRACT_KEY, runtime)
    _resolve_all_conflicts(workspace)


def test_the_gate_passes_only_when_every_defect_is_genuinely_resolved(
    isolated_workspace: Path, valid_subject_key_contract: dict, valid_runtime_contract: dict
) -> None:
    _fully_resolve(isolated_workspace, valid_subject_key_contract, valid_runtime_contract)

    result = evaluate_pre_live_load_gate(isolated_workspace)
    assert result.status == "PASS", result.failed_checks


@pytest.mark.parametrize(
    "defect",
    [
        "stage_02_manifest",
        "subject_key_contract",
        "runtime_contract",
        "artifact_conflict",
        "conflict_registry",
        "contract_authority",
    ],
)
def test_any_single_remaining_defect_keeps_the_gate_failing(
    isolated_workspace: Path,
    valid_subject_key_contract: dict,
    valid_runtime_contract: dict,
    defect: str,
) -> None:
    """One flaw is enough. Each case starts from the fully resolved state and breaks one thing."""
    _fully_resolve(isolated_workspace, valid_subject_key_contract, valid_runtime_contract)
    assert evaluate_pre_live_load_gate(isolated_workspace).status == "PASS"

    if defect == "stage_02_manifest":
        victim = isolated_workspace / "artifacts" / "stage-02" / "subject-root-analysis.json"
        victim.write_text(victim.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif defect == "subject_key_contract":
        install_authoritative_contract(
            isolated_workspace,
            SUBJECT_KEY_CONTRACT_KEY,
            dict(valid_subject_key_contract, algorithm="not-hmac-sha256"),
        )
    elif defect == "runtime_contract":
        install_authoritative_contract(
            isolated_workspace,
            RUNTIME_CONTRACT_KEY,
            dict(valid_runtime_contract, set_role_flow="SET ROLE postgres"),
        )
    elif defect == "artifact_conflict":
        document = yaml.safe_load(_registry_path(isolated_workspace).read_text(encoding="utf-8"))
        document["conflicts"][0]["status"] = "OPEN"
        document["open_conflict_count"] = 1
        _rewrite_registry(isolated_workspace, document)
    elif defect == "conflict_registry":
        _registry_path(isolated_workspace).unlink()
    elif defect == "contract_authority":
        duplicate = isolated_workspace / "artifacts" / "stage-03" / "duplicate-contract.yaml"
        duplicate.write_text(
            yaml.safe_dump(
                {SUBJECT_KEY_CONTRACT_KEY: valid_subject_key_contract}, sort_keys=False
            ),
            encoding="utf-8",
        )

    result = evaluate_pre_live_load_gate(isolated_workspace)
    assert result.status == "FAIL", f"{defect} did not keep the gate closed"


def test_the_real_workspace_resolves_nothing(repo_root: Path) -> None:
    """v0.2.3 hardens the mechanism; Maintenance 01 resolved manifest drift only."""
    result = evaluate_pre_live_load_gate(repo_root)
    assert result.status == "FAIL"
    assert {
        SUBJECT_KEY_BLOCKER,
        LOADER_PRINCIPAL_BLOCKER,
    } <= set(result.failed_checks)
    assert "stage02_relationship_manifest_drift" not in result.failed_checks
    assert len(result.blockers["open_blocker_ids"]) == 4
