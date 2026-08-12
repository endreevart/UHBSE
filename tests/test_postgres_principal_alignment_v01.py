"""Unit tests for postgres-principal alignment v0.1 (no secret values)."""

from __future__ import annotations

import json
from pathlib import Path

from human_simulator.stage03_alignment import postgres_principal as pp
from human_simulator.stage03_alignment import vault_secret_shape as vss
from human_simulator.stage03_alignment.vault_provider import (
    POSTGRES_LOGIN_PRINCIPAL,
    POSTGRES_NOLOGIN_GROUP,
    VAULT_APPROLE,
)


def test_identity_separation() -> None:
    assert VAULT_APPROLE != POSTGRES_LOGIN_PRINCIPAL
    assert VAULT_APPROLE != POSTGRES_NOLOGIN_GROUP
    assert POSTGRES_LOGIN_PRINCIPAL != POSTGRES_NOLOGIN_GROUP
    assert pp.LOGIN_ROLE == POSTGRES_LOGIN_PRINCIPAL
    assert pp.GROUP_ROLE == POSTGRES_NOLOGIN_GROUP


def test_expected_attributes_are_restrictive() -> None:
    attrs = pp.EXPECTED_ATTRIBUTES
    assert attrs["rolcanlogin"] is True
    assert attrs["rolinherit"] is False
    assert attrs["rolsuper"] is False
    assert attrs["rolcreatedb"] is False
    assert attrs["rolcreaterole"] is False
    assert attrs["rolreplication"] is False
    assert attrs["rolbypassrls"] is False


def test_hmac_shape_validator_pass_fail_only() -> None:
    good = {
        "key_version": 1,
        "algorithm": "HMAC-SHA256",
        "key_material": "a" * 64,  # 32 decoded bytes; length check only
    }
    fields = vss.validate_hmac_secret(good)
    assert set(fields.values()) == {vss.PASS}
    assert "entropy_ge_256_bits" not in fields
    assert "a" * 64 not in json.dumps(fields)

    bad = {"key_version": 2, "algorithm": "SHA256", "key_material": "ab"}
    fields_bad = vss.validate_hmac_secret(bad)
    assert fields_bad["key_version"] == vss.FAIL
    assert fields_bad["algorithm"] == vss.FAIL
    assert fields_bad["decoded_key_length_ge_32_bytes"] == vss.FAIL


def test_loader_credential_validator() -> None:
    good = {
        "key_version": "1",
        "username": POSTGRES_LOGIN_PRINCIPAL,
        "password": "x" * 32,
    }
    fields = vss.validate_loader_credential(good)
    assert fields["username"] == vss.PASS
    assert fields["password_min_length_32"] == vss.PASS
    assert "x" * 32 not in json.dumps(fields)

    bad = {"key_version": 1, "username": "wrong", "password": "short"}
    fields_bad = vss.validate_loader_credential(bad)
    assert fields_bad["username"] == vss.FAIL
    assert fields_bad["password_min_length_32"] == vss.FAIL


def test_hex_key_decode_length() -> None:
    assert vss.decode_hex_key_material("ab" * 32) is not None
    assert len(vss.decode_hex_key_material("ab" * 32) or b"") == 32
    assert vss.decode_hex_key_material("short") is None


def test_contract_match_requires_membership() -> None:
    snap = pp.RoleSnapshot(
        exists=True,
        attributes=dict(pp.EXPECTED_ATTRIBUTES),
        memberships=[],
    )
    assert pp.attributes_match(snap)
    assert not pp.membership_match(snap)
    assert not pp.contract_match(snap)

    snap_ok = pp.RoleSnapshot(
        exists=True,
        attributes=dict(pp.EXPECTED_ATTRIBUTES),
        memberships=[pp.GROUP_ROLE],
    )
    assert pp.contract_match(snap_ok)


def test_artefacts_exclude_absolute_volume_path_when_present() -> None:
    root = Path(__file__).resolve().parents[1]
    candidates = list(
        (root / "artifacts" / "stage-03-alignment-candidate").glob("postgres-principal*.json")
    )
    candidates += list(
        (root / "artifacts" / "stage-03-alignment-candidate").glob("vault-secret-shape.json")
    )
    if not candidates:
        return
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        assert "/" + "Volumes/Siska" not in text
        assert "postgresql" + "://" not in text.lower()
