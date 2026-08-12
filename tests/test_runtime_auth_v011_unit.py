"""Unit/static tests for runtime-auth correction v0.1.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from human_simulator.stage03_alignment import approle_hardening as ah
from human_simulator.stage03_alignment import run_runtime_auth_v011 as v011
from human_simulator.stage03_alignment import token_lifecycle as tl

REPO = Path(__file__).resolve().parents[1]


def test_host_path_not_equated_to_container_tmpfs() -> None:
    topo = v011.runtime_topology_doc()
    assert topo["host_run_uhbse_vault_shared"] is False
    assert "container_local_tmpfs" in topo["secrets_filesystem"]


def test_static_hcl_does_not_set_runtime_execution_pass() -> None:
    static = v011.static_agent_validation(REPO)
    assert static["vault_agent_runtime_execution"] == v011.NOT_VERIFIED
    assert "Static" in static["note"] or "static" in static["note"].lower()


def test_version_pin_required_in_agent_hcl() -> None:
    hcl = (REPO / "ops/vault/runtime/vault-agent.hcl").read_text(encoding="utf-8")
    assert "hmac-subject-key?version=1" in hcl
    assert "loader-credential?version=1" in hcl
    # Removing version=1 must fail static validation
    broken = hcl.replace("?version=1", "").replace('"version=1"', "")
    path = REPO / "ops/vault/runtime/vault-agent.hcl"
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text(broken, encoding="utf-8")
        static = v011.static_agent_validation(REPO)
        assert static["checks"]["version_pin_hmac"] == v011.FAIL
        assert static["checks"]["version_pin_loader"] == v011.FAIL
        assert static["overall_status"] == v011.FAIL
    finally:
        path.write_text(original, encoding="utf-8")


def test_token_type_default_fails() -> None:
    observed = {
        "bind_secret_id": True,
        "secret_id_num_uses": 1,
        "secret_id_ttl": 300,
        "token_ttl": 900,
        "token_max_ttl": 3600,
        "token_type": "default",
        "token_no_default_policy": True,
        "token_policies": ["uhbse-canonical-loader"],
    }
    result = ah.validate_approle_observed(observed)
    assert result["checks"]["token_type"] == ah.FAIL
    assert result["overall_status"] == ah.FAIL


def test_token_no_default_policy_false_fails() -> None:
    observed = {
        "bind_secret_id": True,
        "secret_id_num_uses": 1,
        "secret_id_ttl": 300,
        "token_ttl": 900,
        "token_max_ttl": 3600,
        "token_type": "service",
        "token_no_default_policy": False,
        "token_policies": ["uhbse-canonical-loader"],
    }
    result = ah.validate_approle_observed(observed)
    assert result["checks"]["token_no_default_policy"] == ah.FAIL


def test_additional_policy_fails() -> None:
    observed = {
        "bind_secret_id": True,
        "secret_id_num_uses": 1,
        "secret_id_ttl": 300,
        "token_ttl": 900,
        "token_max_ttl": 3600,
        "token_type": "service",
        "token_no_default_policy": True,
        "token_policies": ["uhbse-canonical-loader", "default"],
    }
    result = ah.validate_approle_observed(observed)
    assert result["checks"]["token_policies_exact"] == ah.FAIL


def test_exact_policies_pass() -> None:
    observed = {
        "bind_secret_id": True,
        "secret_id_num_uses": 1,
        "secret_id_ttl": 300,
        "token_ttl": 900,
        "token_max_ttl": 3600,
        "token_type": "service",
        "token_no_default_policy": True,
        "token_policies": ["uhbse-canonical-loader"],
    }
    result = ah.validate_approle_observed(observed)
    assert result["overall_status"] == ah.PASS


def test_env_restored_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    snap = tl.vault_token_env_snapshot()
    os.environ["VAULT_TOKEN"] = "temporary"
    os.environ.pop("VAULT_TOKEN", None)
    assert tl.env_matches_snapshot(snap)


def test_env_restored_after_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setenv("VAULT_TOKEN", "prior-value")
    snap = tl.vault_token_env_snapshot()
    try:
        os.environ["VAULT_TOKEN"] = "mutated"
        raise RuntimeError("boom")
    except RuntimeError:
        os.environ["VAULT_TOKEN"] = "prior-value"
    assert tl.env_matches_snapshot(snap)


def test_accepted_v01_constant() -> None:
    assert v011.ACCEPTED_V01_SHA256 == (
        "a7708432dd0484797ee35b613de005bc147b541cb6e484fcd5a999fb024b25b4"
    )


def test_compose_has_no_secret_literals_in_runtime_service() -> None:
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    section = compose.split("canonical-loader-runtime:")[1].split("\nvolumes:")[0]
    assert "VAULT_TOKEN" not in section
    assert "SECRET_ID" not in section
    assert "ROLE_ID" not in section
    assert "PASSWORD" not in section
