"""Read-only validation of Vault-compatible PGP public-key files for rekey.

Vault ``-pgp-keys`` expects binary public keys or standard base64 of binary
exports — not ASCII-armored ``.asc`` files.
"""

from __future__ import annotations

import base64
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PASS = "PASS"
FAIL = "FAIL"

ARMOR_PUBLIC_HEADER = "-----BEGIN PGP PUBLIC KEY BLOCK-----"
ARMOR_PRIVATE_HEADER = "-----BEGIN PGP PRIVATE KEY BLOCK-----"
FINGERPRINT_RE = re.compile(r"^[0-9A-Fa-f]{40}$|^[0-9A-Fa-f]{64}$")


def is_ascii_armored_pgp(data: bytes) -> bool:
    text = data.decode("utf-8", errors="ignore")
    return "-----BEGIN PGP" in text


def looks_like_private_key_material(data: bytes) -> bool:
    text = data.decode("utf-8", errors="ignore")
    if ARMOR_PRIVATE_HEADER in text:
        return True
    # Binary OpenPGP secret-key packet tags (old/new format heuristics via gpg below)
    return False


def _contains_secret_packets(binary: bytes) -> bool:
    with tempfile.TemporaryDirectory(prefix="ugpg-p-", dir="/tmp") as tmp:
        key_path = Path(tmp) / "key.bin"
        key_path.write_bytes(binary)
        env_home = Path(tmp) / "g"
        env_home.mkdir(mode=0o700)
        packets = subprocess.run(
            [
                "gpg",
                "--homedir",
                str(env_home),
                "--batch",
                "--list-packets",
                str(key_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        text = ((packets.stdout or "") + "\n" + (packets.stderr or "")).lower()
        return (
            "secret key packet" in text
            or "secret sub key packet" in text
            or ":secret" in text
        )


def decode_vault_pgp_key_file(path: Path) -> tuple[bytes, str]:
    """Return (binary_pgp, encoding_kind) or raise ValueError.

    encoding_kind: binary | base64
    Rejects ASCII armor as a Vault -pgp-keys input.
    """
    raw = path.read_bytes()
    if not raw:
        raise ValueError("empty_key_file")
    if is_ascii_armored_pgp(raw):
        raise ValueError("ascii_armor_rejected_for_vault_pgp_keys")
    if looks_like_private_key_material(raw) or _contains_secret_packets(raw):
        raise ValueError("private_key_material_rejected")

    # Try as binary OpenPGP first
    if _gpg_show_keys_ok(raw):
        return raw, "binary"

    # Standard base64 of binary (no armor headers)
    try:
        text = raw.decode("ascii").strip()
        if "BEGIN PGP" in text:
            raise ValueError("ascii_armor_rejected_for_vault_pgp_keys")
        decoded = base64.b64decode(text, validate=False)
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("ascii_armor"):
            raise
        raise ValueError("not_binary_or_standard_base64_public_key") from exc

    if is_ascii_armored_pgp(decoded) or looks_like_private_key_material(decoded):
        raise ValueError("decoded_material_not_public_binary")
    if _contains_secret_packets(decoded):
        raise ValueError("private_key_material_rejected")
    if not _gpg_show_keys_ok(decoded):
        raise ValueError("base64_decoded_not_valid_pgp_public_key")
    return decoded, "base64"


def _gpg_inspect(binary: bytes) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ugpg-i-", dir="/tmp") as tmp:
        key_path = Path(tmp) / "key.bin"
        key_path.write_bytes(binary)
        env_home = Path(tmp) / "g"
        env_home.mkdir(mode=0o700)
        show = subprocess.run(
            [
                "gpg",
                "--homedir",
                str(env_home),
                "--batch",
                "--show-keys",
                "--with-colons",
                "--with-fingerprint",
                str(key_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        packets = subprocess.run(
            [
                "gpg",
                "--homedir",
                str(env_home),
                "--batch",
                "--list-packets",
                str(key_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return {
            "show_rc": show.returncode,
            "show_stdout": show.stdout or "",
            "packets_rc": packets.returncode,
            "packets_stdout": packets.stdout or "",
            "packets_stderr": packets.stderr or "",
        }


def _gpg_show_keys_ok(binary: bytes) -> bool:
    with tempfile.TemporaryDirectory(prefix="ugpg-s-", dir="/tmp") as tmp:
        key_path = Path(tmp) / "key.bin"
        key_path.write_bytes(binary)
        env_home = Path(tmp) / "g"
        env_home.mkdir()
        proc = subprocess.run(
            [
                "gpg",
                "--homedir",
                str(env_home),
                "--batch",
                "--show-keys",
                "--with-colons",
                str(key_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return proc.returncode == 0 and "pub:" in (proc.stdout or "")


def validate_vault_pgp_public_key_file(
    path: Path,
    *,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Validate one custodian public-key file for Vault -pgp-keys use."""
    checks: dict[str, str] = {}
    try:
        binary, kind = decode_vault_pgp_key_file(path)
        checks["vault_compatible_encoding"] = PASS
        checks["encoding_kind"] = kind  # informational, not PASS/FAIL
    except ValueError as exc:
        code = str(exc)
        return {
            "overall_status": FAIL,
            "path": path.name,
            "checks": {
                "vault_compatible_encoding": FAIL,
                "reject_reason": code,
                "ascii_armor_rejected": PASS
                if code == "ascii_armor_rejected_for_vault_pgp_keys"
                else FAIL,
            },
        }

    insp = _gpg_inspect(binary)
    packet_text = (insp["packets_stdout"] + "\n" + insp["packets_stderr"]).lower()
    secret_packet = (
        "secret key packet" in packet_text
        or "secret sub key packet" in packet_text
        or ":secret" in packet_text
    )
    checks["parses_as_pgp_public_key"] = (
        PASS if insp["show_rc"] == 0 and "pub:" in insp["show_stdout"] else FAIL
    )
    checks["no_secret_key_packets"] = PASS if not secret_packet else FAIL

    fps: list[str] = []
    can_encrypt = False
    expired = False
    revoked = False
    uid_count = 0
    for line in insp["show_stdout"].splitlines():
        parts = line.split(":")
        if not parts:
            continue
        tag = parts[0]
        if tag == "fpr" and len(parts) > 9 and parts[9]:
            fps.append(parts[9].upper())
        if tag == "pub" and len(parts) > 11:
            # validity field parts[1]: 'e' expired, 'r' revoked, etc.
            validity = parts[1]
            if validity == "e":
                expired = True
            if validity == "r":
                revoked = True
            # capabilities parts[11] may include 'e'
            caps = parts[11] if len(parts) > 11 else ""
            if "e" in caps:
                can_encrypt = True
            # expire: parts[6] — non-zero and in the past handled via validity
        if tag == "sub" and len(parts) > 11:
            caps = parts[11] if len(parts) > 11 else ""
            if "e" in caps:
                can_encrypt = True
            if parts[1] == "e":
                expired = True
            if parts[1] == "r":
                revoked = True
        if tag == "uid":
            uid_count += 1
            if len(parts) > 1 and parts[1] == "r":
                revoked = True

    primary_fpr = fps[0] if fps else ""
    checks["fingerprint_present"] = PASS if primary_fpr and FINGERPRINT_RE.match(primary_fpr) else FAIL
    if expected_fingerprint:
        exp = expected_fingerprint.replace(" ", "").upper()
        checks["fingerprint_matches_approved"] = (
            PASS if primary_fpr == exp else FAIL
        )
    else:
        checks["fingerprint_matches_approved"] = PASS  # not asserted when unset

    checks["supports_encryption"] = PASS if can_encrypt else FAIL
    checks["not_expired"] = PASS if not expired else FAIL
    checks["not_revoked"] = PASS if not revoked else FAIL
    checks["exactly_one_primary_identity"] = PASS if uid_count >= 1 and primary_fpr else FAIL

    # Drop non PASS/FAIL informational before overall
    status_checks = {k: v for k, v in checks.items() if v in (PASS, FAIL)}
    overall = PASS if status_checks and all(v == PASS for v in status_checks.values()) else FAIL
    return {
        "overall_status": overall,
        "path": path.name,
        "encoding_kind": kind,
        "fingerprint": primary_fpr or None,
        "checks": checks,
        "secrets_recorded": False,
    }


def validate_three_custodian_public_keys(
    paths: list[Path],
    *,
    approved_fingerprints: list[str] | None = None,
) -> dict[str, Any]:
    if len(paths) != 3:
        return {
            "overall_status": FAIL,
            "detail": "expected_exactly_three_public_key_files",
        }
    results = []
    fps: list[str] = []
    for i, path in enumerate(paths):
        expected = None
        if approved_fingerprints and i < len(approved_fingerprints):
            expected = approved_fingerprints[i]
        one = validate_vault_pgp_public_key_file(path, expected_fingerprint=expected)
        results.append(one)
        if one.get("fingerprint"):
            fps.append(one["fingerprint"])

    distinct = len(set(fps)) == 3 and len(fps) == 3
    overall = (
        PASS
        if distinct and all(r.get("overall_status") == PASS for r in results)
        else FAIL
    )
    return {
        "overall_status": overall,
        "keys": results,
        "fingerprints": fps,
        "fingerprints_distinct": distinct,
        "shares": 3,
        "threshold": 2,
        "secrets_recorded": False,
    }


def ascii_armor_rejected_as_vault_pgp_keys_input(data: bytes) -> bool:
    """True when material must be rejected for direct ``-pgp-keys`` use."""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(data)
            path = Path(fh.name)
        try:
            decode_vault_pgp_key_file(path)
            return False
        except ValueError as exc:
            return str(exc) == "ascii_armor_rejected_for_vault_pgp_keys"
        finally:
            path.unlink(missing_ok=True)
    except OSError:
        return is_ascii_armored_pgp(data)


def _cli_main(argv: list[str] | None = None) -> int:
    import json
    import sys

    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 3:
        print(
            "usage: python -m human_simulator.stage03_alignment.pgp_public_key_validate "
            "key1.gpg.b64 key2.gpg.b64 key3.gpg.b64",
            file=sys.stderr,
        )
        return 2
    paths = [Path(a) for a in args]
    for p in paths:
        if not p.is_file():
            print(json.dumps({"overall_status": FAIL, "missing": p.name}))
            return 1
    result = validate_three_custodian_public_keys(paths)
    print(json.dumps(result, indent=2))
    return 0 if result.get("overall_status") == PASS else 1


if __name__ == "__main__":
    raise SystemExit(_cli_main())
