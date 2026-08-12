"""Tests for runtime-auth alignment v0.1 (no live secrets required for unit suite)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from human_simulator.stage03_alignment import approle_hardening as ah
from human_simulator.stage03_alignment import runtime_auth_baseline as baseline
from human_simulator.stage03_alignment import runtime_auth_smoke as smoke
from human_simulator.stage03_alignment import vault_secret_shape as vss
from human_simulator.stage03_alignment.vault_provider import POSTGRES_LOGIN_PRINCIPAL

REPO = Path(__file__).resolve().parents[1]


def test_repeated_character_key_does_not_prove_entropy() -> None:
    """Regression: 'a'*64 must not be treated as an entropy proof."""
    material = "a" * 64
    decoded = vss.decode_hex_key_material(material)
    assert decoded is not None
    assert len(decoded) == 32
    # Length check may PASS, but we must not claim entropy_ge_256_bits anywhere.
    fields = vss.validate_hmac_secret(
        {"key_version": 1, "algorithm": "HMAC-SHA256", "key_material": material}
    )
    assert "entropy_ge_256_bits" not in fields
    assert fields["decoded_key_length_ge_32_bytes"] == vss.PASS
    # Document that repeated hex is still only a length/format check.
    assert fields["hex_decoding_succeeds"] == vss.PASS


def test_decoded_key_length_validation() -> None:
    short = {"key_version": 1, "algorithm": "HMAC-SHA256", "key_material": "abcd"}
    fields = vss.validate_hmac_secret(short)
    assert fields["hex_decoding_succeeds"] == vss.PASS
    assert fields["decoded_key_length_ge_32_bytes"] == vss.FAIL

    bad_hex = {"key_version": 1, "algorithm": "HMAC-SHA256", "key_material": "zz"}
    fields_bad = vss.validate_hmac_secret(bad_hex)
    assert fields_bad["hex_decoding_succeeds"] == vss.FAIL


def test_exact_approle_policy_constant() -> None:
    assert ah.TOKEN_POLICIES == ("uhbse-canonical-loader",)
    assert ah.APPROLE_POLICY == "uhbse-canonical-loader"
    assert ah.BIND_SECRET_ID is True


def test_secret_id_one_use_configuration() -> None:
    assert ah.SECRET_ID_NUM_USES == 1
    assert ah.EXPECTED_APPROLE_CONFIG["secret_id_num_uses"] == 1


def test_response_wrapping_creation_path() -> None:
    assert (
        ah.SECRET_ID_RESPONSE_WRAPPING_PATH
        == "auth/approle/role/uhbse-canonical-loader/secret-id"
    )
    hcl = (REPO / "ops/vault/agent/vault-agent.hcl").read_text(encoding="utf-8")
    assert ah.SECRET_ID_RESPONSE_WRAPPING_PATH in hcl
    assert "remove_secret_id_file_after_reading = true" in hcl


def test_tmpfs_only_runtime_paths_in_agent_and_compose() -> None:
    hcl = (REPO / "ops/vault/agent/vault-agent.hcl").read_text(encoding="utf-8")
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/run/uhbse-vault" in hcl
    assert "vault-agent:" in compose
    agent = compose.split("vault-agent:")[1].split("\nvolumes:")[0]
    assert "tmpfs:" in agent
    assert "/run/uhbse-vault" in agent


def test_no_command_line_secret_delivery_in_scripts() -> None:
    deliver = (REPO / "ops/vault/scripts/deliver-approle-credentials.sh").read_text(
        encoding="utf-8"
    )
    # Must not pass secrets as vault CLI positional plaintext in echo/printf logs.
    assert "echo \"$ROLE_ID\"" not in deliver
    assert "echo \"$WRAP_TOKEN\"" not in deliver
    assert "printf '%s' \"${ROLE_ID}\"" in deliver


def test_no_secret_environment_in_docker_compose_agent() -> None:
    checks = smoke.inspect_compose_no_secret_env(REPO)
    assert checks["compose_no_secret_env"] == smoke.PASS
    assert checks["compose_agent_tmpfs"] == smoke.PASS


def test_runtime_hmac_determinism_synthetic_fixture() -> None:
    key_hex = hashlib.sha256(b"fixture-only-not-production").hexdigest()
    checks = smoke.hmac_smoke(key_hex, smoke.SYNTHETIC_SUBJECT_ID)
    assert checks["deterministic_repeatability"] == smoke.PASS
    assert checks["output_length_bytes"] == smoke.PASS


def test_raw_identifier_and_digest_absent_from_artifacts_contract() -> None:
    checks = smoke.hmac_smoke("ab" * 32, smoke.SYNTHETIC_SUBJECT_ID)
    assert checks["raw_identifier_absent_from_artifacts"] == smoke.PASS
    assert checks["digest_absent_from_artifacts"] == smoke.PASS
    sample = {
        "hmac": {"algorithm": "HMAC-SHA256", "key_version": 1, "checks": checks},
        "synthetic_subject_label": "SYNTHETIC_RUNTIME_SMOKE",
    }
    blob = json.dumps(sample)
    assert smoke.SYNTHETIC_SUBJECT_ID not in blob



def test_accepted_zips_constants_match_files() -> None:
    external = REPO / "artifacts/external-review"
    for name, expected in (
        (baseline.ACCEPTED_VAULT_STOP_ZIP, baseline.ACCEPTED_VAULT_STOP_SHA256),
        (
            baseline.ACCEPTED_POSTGRES_PRINCIPAL_ZIP,
            baseline.ACCEPTED_POSTGRES_PRINCIPAL_SHA256,
        ),
    ):
        path = external / name
        if not path.is_file():
            pytest.skip(f"accepted zip absent in this tree: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected


def test_accepted_zip_digest_constants_stable() -> None:
    assert len(baseline.ACCEPTED_VAULT_STOP_SHA256) == 64
    assert len(baseline.ACCEPTED_POSTGRES_PRINCIPAL_SHA256) == 64
    assert baseline.ACCEPTED_VAULT_STOP_SHA256 != baseline.ACCEPTED_POSTGRES_PRINCIPAL_SHA256


def test_migrations_unchanged_constants() -> None:
    from human_simulator.canonical.migrations import migration_immutability

    result = migration_immutability(REPO)
    assert result["status"] == "PASS"


def test_root_token_finding_remains_open_in_decision() -> None:
    text = (
        REPO
        / "artifacts/stage-03-alignment-candidate/decision-required-limited-operator.yaml"
    ).read_text(encoding="utf-8")
    assert "initial_root_token_available" in text
    assert "status: OPEN" in text
    assert "revoked_in_this_task: false" in text


def test_custody_model_remains_decision_required() -> None:
    text = (
        REPO
        / "artifacts/stage-03-alignment-candidate/decision-required-vault-key-custody.yaml"
    ).read_text(encoding="utf-8")
    assert "DECISION_REQUIRED" in text
    assert "NOT_ACCEPTABLE_FOR_LIVE_LOAD" in text
    assert "selected_model: null" in text


def test_loader_username_constant() -> None:
    fields = vss.validate_loader_credential(
        {
            "key_version": 1,
            "username": POSTGRES_LOGIN_PRINCIPAL,
            "password": "x" * 32,
        }
    )
    assert fields["username"] == vss.PASS


def test_generation_provenance_uses_secrets_module() -> None:
    prov = vss.generation_provenance(REPO)
    assert prov["status"] == vss.PASS
    assert prov["uses_os_backed_csprng"] is True
    assert prov["generator_source_sha256"]


def test_secret_file_deletion_helper(tmp_path: Path) -> None:
    runtime = tmp_path / "run"
    secrets = runtime / "secrets"
    secrets.mkdir(parents=True)
    (runtime / "role-id").write_text("x", encoding="utf-8")
    (runtime / "wrapped-secret-id").write_text("y", encoding="utf-8")
    (secrets / "hmac-subject-key.json").write_text("{}", encoding="utf-8")
    result = smoke.cleanup_runtime_files(runtime)
    assert result["secret_files_removed"] == smoke.PASS
    assert not (runtime / "role-id").exists()
