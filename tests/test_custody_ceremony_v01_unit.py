"""Regression tests for corrected Phase 2 custody ceremony validators."""

from __future__ import annotations

import base64
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from human_simulator.stage03_alignment.custody_ceremony_validate import (
    FAIL,
    PASS,
    document_alone_cannot_close_blockers,
    validate_ceremony_evidence,
    validate_rekey_command_flags,
)
from human_simulator.stage03_alignment.pgp_public_key_validate import (
    ascii_armor_rejected_as_vault_pgp_keys_input,
    decode_vault_pgp_key_file,
    validate_three_custodian_public_keys,
    validate_vault_pgp_public_key_file,
)

REPO = Path(__file__).resolve().parents[1]
RUNBOOK = REPO / "ops/vault/runbooks/multi-custodian-rekey-ceremony.md"


def _gpg_available() -> bool:
    return subprocess.run(["gpg", "--version"], capture_output=True, check=False).returncode == 0


pytestmark = pytest.mark.skipif(not _gpg_available(), reason="gpg required")


def _make_encrypt_keypair(home: Path, uid: str, *, expire: str = "0") -> tuple[Path, str]:
    # Short path under /tmp — macOS gpg-agent fails when GNUPGHOME sockets are too long.
    import tempfile as _tf

    short = Path(_tf.mkdtemp(prefix="ugpg-", dir="/tmp"))
    short.chmod(0o700)
    env = os.environ.copy()
    env["GNUPGHOME"] = str(short)
    subprocess.run(
        ["gpg", "--batch", "--list-keys"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            uid,
            "rsa2048",
            "cert,encrypt",
            expire,
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "gpg keygen failed")
    listing = subprocess.run(
        ["gpg", "--list-keys", "--with-colons", uid],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    fpr = ""
    for line in listing.stdout.splitlines():
        if line.startswith("fpr:"):
            fpr = line.split(":")[9]
            break
    assert fpr
    # Stash path for cleanup via home marker
    (home).mkdir(parents=True, exist_ok=True)
    (home / "GNUPGHOME").write_text(str(short), encoding="utf-8")
    return short, fpr


def test_runbook_requires_verify_and_rejects_armor_and_false_snapshot_rollback() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "-verify" in text
    assert "ascii" in text.lower() or "ASCII" in text
    assert "base64" in text
    assert "WAITING_FOR_THREE_CUSTODIANS" in text
    assert "substitute for a valid unseal quorum" in text
    assert "vault operator rekey -cancel" in text
    assert "Current unseal-key holders" in text
    assert "New custodians" in text
    assert "Do **not** retire or destroy old shares immediately" in text
    assert "snapshot restore -force" in text


def test_ascii_armored_input_rejected_as_direct_pgp_keys() -> None:
    armor = textwrap.dedent(
        """\
        -----BEGIN PGP PUBLIC KEY BLOCK-----

        mQENBFTEST
        -----END PGP PUBLIC KEY BLOCK-----
        """
    ).encode()
    assert ascii_armor_rejected_as_vault_pgp_keys_input(armor) is True


def test_binary_and_base64_public_key_accepted(tmp_path: Path) -> None:
    home, fpr = _make_encrypt_keypair(tmp_path / "g1", "Custodian One <c1@example.test>")
    env = os.environ.copy()
    env["GNUPGHOME"] = str(home)
    binary = subprocess.run(
        ["gpg", "--export", fpr], env=env, check=True, capture_output=True
    ).stdout
    bin_path = tmp_path / "c1.bin"
    bin_path.write_bytes(binary)
    b64_path = tmp_path / "c1.b64"
    b64_path.write_text(base64.b64encode(binary).decode("ascii"), encoding="ascii")

    assert decode_vault_pgp_key_file(bin_path)[1] == "binary"
    assert decode_vault_pgp_key_file(b64_path)[1] == "base64"
    assert validate_vault_pgp_public_key_file(bin_path, expected_fingerprint=fpr)[
        "overall_status"
    ] == PASS
    assert validate_vault_pgp_public_key_file(b64_path, expected_fingerprint=fpr)[
        "overall_status"
    ] == PASS


def test_private_pgp_material_rejected(tmp_path: Path) -> None:
    private_armor = (
        b"-----BEGIN PGP PRIVATE KEY BLOCK-----\n\nxxyy\n-----END PGP PRIVATE KEY BLOCK-----\n"
    )
    path = tmp_path / "secret.asc"
    path.write_bytes(private_armor)
    result = validate_vault_pgp_public_key_file(path)
    assert result["overall_status"] == FAIL


def test_non_encryption_key_fails(tmp_path: Path) -> None:
    import tempfile as _tf

    home = Path(_tf.mkdtemp(prefix="ugpg-s-", dir="/tmp"))
    home.chmod(0o700)
    env = os.environ.copy()
    env["GNUPGHOME"] = str(home)
    uid = "Sign Only <sign@example.test>"
    subprocess.run(
        ["gpg", "--batch", "--list-keys"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            uid,
            "rsa2048",
            "sign",
            "0",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    listing = subprocess.run(
        ["gpg", "--list-keys", "--with-colons", uid],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    fpr = next(line.split(":")[9] for line in listing.stdout.splitlines() if line.startswith("fpr:"))
    binary = subprocess.run(
        ["gpg", "--export", fpr], env=env, check=True, capture_output=True
    ).stdout
    path = tmp_path / "sign.bin"
    path.write_bytes(binary)
    result = validate_vault_pgp_public_key_file(path, expected_fingerprint=fpr)
    assert result["checks"]["supports_encryption"] == FAIL
    assert result["overall_status"] == FAIL


def test_exported_secret_key_rejected(tmp_path: Path) -> None:
    home, fpr = _make_encrypt_keypair(tmp_path / "sec", "Secret Export <s@example.test>")
    env = os.environ.copy()
    env["GNUPGHOME"] = str(home)
    secret = subprocess.run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--export-secret-keys",
            fpr,
        ],
        env=env,
        check=True,
        capture_output=True,
    ).stdout
    path = tmp_path / "secret.bin"
    path.write_bytes(secret)
    result = validate_vault_pgp_public_key_file(path)
    assert result["overall_status"] == FAIL
    reason = result["checks"].get("reject_reason")
    assert reason == "private_key_material_rejected" or result["checks"].get(
        "no_secret_key_packets"
    ) == FAIL


def test_expired_key_fails(tmp_path: Path) -> None:
    import time

    home, fpr = _make_encrypt_keypair(
        tmp_path / "exp", "Expired <e@example.test>", expire="seconds=1"
    )
    time.sleep(2)
    env = os.environ.copy()
    env["GNUPGHOME"] = str(home)
    binary = subprocess.run(
        ["gpg", "--export", fpr], env=env, check=True, capture_output=True
    ).stdout
    path = tmp_path / "expired.bin"
    path.write_bytes(binary)
    result = validate_vault_pgp_public_key_file(path, expected_fingerprint=fpr)
    assert result["checks"]["not_expired"] == FAIL
    assert result["overall_status"] == FAIL


def test_duplicate_fingerprints_fail(tmp_path: Path) -> None:
    home, fpr = _make_encrypt_keypair(tmp_path / "g1", "Custodian Dup <d@example.test>")
    env = os.environ.copy()
    env["GNUPGHOME"] = str(home)
    binary = subprocess.run(
        ["gpg", "--export", fpr], env=env, check=True, capture_output=True
    ).stdout
    paths = []
    for i in range(3):
        p = tmp_path / f"k{i}.bin"
        p.write_bytes(binary)
        paths.append(p)
    result = validate_three_custodian_public_keys(paths)
    assert result["fingerprints_distinct"] is False
    assert result["overall_status"] == FAIL


def test_rekey_without_verify_fails_validation() -> None:
    flags = {
        "key_shares": 3,
        "key_threshold": 2,
        "verify": False,
        "pgp_keys_count": 3,
        "pgp_keys_encoding": "base64",
    }
    assert validate_rekey_command_flags(flags)["verify_flag_present"] == FAIL


def test_missing_verification_nonce_fails() -> None:
    doc = _minimal_passing_evidence()
    doc["verification_nonce_recorded"] = False
    result = validate_ceremony_evidence(doc)
    assert result["checks"]["verification_nonce_recorded"] == FAIL
    assert result["overall_status"] == FAIL


def test_completed_rekey_without_verification_pass_fails() -> None:
    doc = _minimal_passing_evidence()
    doc["rekey_verification"] = FAIL
    doc["rekey_completed"] = True
    result = validate_ceremony_evidence(doc)
    assert result["checks"]["completed_requires_verification_pass"] == FAIL


def test_optional_unseal_drill_fails_acceptance() -> None:
    doc = _minimal_passing_evidence()
    doc["seal_unseal_drill"] = "SKIP"
    result = validate_ceremony_evidence(doc)
    assert result["checks"]["unseal_drill_mandatory"] == FAIL
    assert result["custody_blockers_may_close"] is False


def test_snapshot_not_treated_as_rekey_rollback() -> None:
    doc = _minimal_passing_evidence()
    doc["raft_snapshot_is_rekey_rollback"] = True
    result = validate_ceremony_evidence(doc)
    assert result["checks"]["snapshot_not_treated_as_rekey_rollback"] == FAIL


def test_old_share_retirement_before_unseal_drill_fails() -> None:
    doc = _minimal_passing_evidence()
    doc["old_share_retirement"] = {"retired_before_unseal_drill": True, "retired": False}
    result = validate_ceremony_evidence(doc)
    assert result["checks"]["old_shares_not_retired_before_drill"] == FAIL


def test_one_human_controlling_two_custodian_slots_fails() -> None:
    doc = _minimal_passing_evidence()
    doc["no_single_human_controls_threshold_shares"] = False
    result = validate_ceremony_evidence(doc)
    assert result["checks"]["no_single_human_controls_threshold"] == FAIL
    assert result["overall_status"] == FAIL


def test_no_custody_blocker_closes_from_documents_alone() -> None:
    assert document_alone_cannot_close_blockers({"fingerprints": ["A" * 40, "B" * 40, "C" * 40]})


def test_passing_evidence_shape_allows_closure_eligibility() -> None:
    result = validate_ceremony_evidence(_minimal_passing_evidence())
    assert result["overall_status"] == PASS
    assert result["custody_blockers_may_close"] is True


def _minimal_passing_evidence() -> dict:
    return {
        "public_fingerprints": ["A" * 40, "B" * 40, "C" * 40],
        "shares": 3,
        "threshold": 2,
        "rekey_flags": {
            "key_shares": 3,
            "key_threshold": 2,
            "verify": True,
            "pgp_keys_count": 3,
            "pgp_keys_encoding": "base64",
        },
        "rekey_initiated": True,
        "rekey_operation_nonce_recorded": True,
        "verification_nonce_recorded": True,
        "rekey_verification": PASS,
        "rekey_completed": True,
        "current_and_new_share_holders_distinguished": True,
        "unseal_drill_custodian_slots": ["c1", "c3"],
        "seal_unseal_drill": PASS,
        "no_single_human_controls_threshold_shares": True,
        "raft_snapshot_is_rekey_rollback": False,
        "three_custodian_receipt_confirmed": True,
        "post_unseal_runtime_verification": PASS,
        "old_share_retirement": {"retired": False, "retired_before_unseal_drill": False},
        "close_blockers_from_document_only": False,
    }
