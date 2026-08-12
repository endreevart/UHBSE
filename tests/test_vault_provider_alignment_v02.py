"""Regression: Vault identity separation and contract URI shape (no live Vault)."""

from __future__ import annotations

from human_simulator.stage03_alignment import vault_provider as vp


def test_vault_dev_mode_prohibited() -> None:
    assert vp.DEV_MODE_PROHIBITED is True
    assert vp.VAULT_MODE == "production"


def test_contract_references_use_confirmed_paths() -> None:
    assert vp.CONTRACT_HMAC_REFERENCE == "vault://uhbse/canonical/hmac-subject-key?version=1"
    assert vp.CONTRACT_LOADER_REFERENCE == "vault://uhbse/canonical/loader-credential?version=1"
    assert "?version=1" in vp.CONTRACT_HMAC_REFERENCE
    assert "latest" not in vp.CONTRACT_HMAC_REFERENCE
    assert "TBD" not in vp.CONTRACT_LOADER_REFERENCE


def test_approle_is_not_postgres_principal() -> None:
    assert vp.VAULT_APPROLE == "uhbse-canonical-loader"
    assert vp.POSTGRES_LOGIN_PRINCIPAL == "canonical_loader_login"
    assert vp.POSTGRES_NOLOGIN_GROUP == "canonical_loader"
    assert vp.VAULT_APPROLE != vp.POSTGRES_LOGIN_PRINCIPAL
    assert vp.VAULT_APPROLE != vp.POSTGRES_NOLOGIN_GROUP
    assert vp.POSTGRES_LOGIN_PRINCIPAL != vp.POSTGRES_NOLOGIN_GROUP


def test_kv_mount_and_logical_paths() -> None:
    assert vp.KV_MOUNT == "uhbse"
    assert vp.LOGICAL_HMAC_PATH == "canonical/hmac-subject-key"
    assert vp.LOGICAL_LOADER_PATH == "canonical/loader-credential"
