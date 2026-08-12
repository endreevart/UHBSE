"""Runtime-only Vault secret shape validation (no secret values in artifacts)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from human_simulator.stage03_alignment.vault_provider import (
    CONTRACT_HMAC_REFERENCE,
    CONTRACT_LOADER_REFERENCE,
    KV_MOUNT,
    LOGICAL_HMAC_PATH,
    LOGICAL_LOADER_PATH,
    POSTGRES_LOGIN_PRINCIPAL,
)

PASS = "PASS"
FAIL = "FAIL"

HMAC_ALGORITHM_EXPECTED = "HMAC-SHA256"
MIN_DECODED_KEY_BYTES = 32
MIN_PASSWORD_LENGTH = 32
EXPECTED_KEY_VERSION = 1

PROJECT_ROOT_CACERT = "$PROJECT_ROOT/ops/vault/tls/ca.crt"
GENERATOR_SOURCE_REL = Path("ops") / "vault" / "scripts" / "bootstrap-kv-approle.sh"
GENERATOR_USES_CSPRNG = True
GENERATOR_IMPLEMENTATION = "python_secrets_token_hex_and_token_urlsafe"


class VaultSecretAccessError(RuntimeError):
    """Raised when Vault cannot be read. Never includes secret values."""


@dataclass(frozen=True)
class VaultRuntimeConfig:
    addr: str
    token: str
    cacert: Path

    def normalised_cacert_evidence(self) -> str:
        return PROJECT_ROOT_CACERT


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_vault_runtime(*, require_token: bool = True) -> VaultRuntimeConfig:
    root = repo_root()
    addr = os.environ.get("VAULT_ADDR", "https://127.0.0.1:8200").rstrip("/")
    cacert_env = os.environ.get("VAULT_CACERT", str(root / "ops" / "vault" / "tls" / "ca.crt"))
    cacert = Path(cacert_env)
    token = os.environ.get("VAULT_TOKEN", "").strip()
    if require_token and not token:
        raise VaultSecretAccessError("VAULT_TOKEN unavailable")
    if not cacert.is_file():
        raise VaultSecretAccessError("VAULT_CACERT missing")
    return VaultRuntimeConfig(addr=addr, token=token, cacert=cacert)


def _ssl_context(cacert: Path) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(cacert))


def vault_kv_v2_read(
    config: VaultRuntimeConfig,
    *,
    mount: str,
    path: str,
    version: int,
) -> dict[str, Any]:
    """Read KV v2 data into process memory. Caller must not log the payload."""
    url = f"{config.addr}/v1/{mount}/data/{path}?version={version}"
    request = urllib.request.Request(
        url,
        headers={"X-Vault-Token": config.token, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, context=_ssl_context(config.cacert), timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise VaultSecretAccessError(f"Vault HTTP {exc.code} for {mount}/{path}") from None
    except urllib.error.URLError as exc:
        raise VaultSecretAccessError(f"Vault unreachable: {exc.__class__.__name__}") from None
    data = (payload.get("data") or {}).get("data")
    if not isinstance(data, dict):
        raise VaultSecretAccessError(f"Vault payload missing data for {mount}/{path}")
    return data


_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def decode_hex_key_material(material: object) -> bytes | None:
    """Decode hex key material. Returns None on any failure. Never claims entropy."""
    if not isinstance(material, str) or not material:
        return None
    text = material.strip()
    if not _HEX_RE.fullmatch(text) or len(text) % 2 != 0:
        return None
    try:
        return bytes.fromhex(text)
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def validate_hmac_secret(data: dict[str, Any]) -> dict[str, str]:
    key_version = _as_int(data.get("key_version"))
    algorithm = data.get("algorithm")
    material = data.get("key_material")
    present = material not in (None, "")
    decoded = decode_hex_key_material(material) if present else None
    return {
        "key_version": PASS if key_version == EXPECTED_KEY_VERSION else FAIL,
        "algorithm": PASS if algorithm == HMAC_ALGORITHM_EXPECTED else FAIL,
        "key_material_present": PASS if present else FAIL,
        "hex_decoding_succeeds": PASS if decoded is not None else FAIL,
        "decoded_key_length_ge_32_bytes": PASS
        if decoded is not None and len(decoded) >= MIN_DECODED_KEY_BYTES
        else FAIL,
    }


def validate_loader_credential(data: dict[str, Any]) -> dict[str, str]:
    key_version = _as_int(data.get("key_version"))
    username = data.get("username")
    password = data.get("password")
    password_ok = isinstance(password, str) and len(password) >= MIN_PASSWORD_LENGTH
    return {
        "key_version": PASS if key_version == EXPECTED_KEY_VERSION else FAIL,
        "username": PASS if username == POSTGRES_LOGIN_PRINCIPAL else FAIL,
        "password_present": PASS if isinstance(password, str) and password != "" else FAIL,
        "password_min_length_32": PASS if password_ok else FAIL,
    }


def field_status_overall(field_map: dict[str, str]) -> str:
    return PASS if all(status == PASS for status in field_map.values()) else FAIL


def generation_provenance(repo: Path | None = None) -> dict[str, Any]:
    root = repo or repo_root()
    source = root / GENERATOR_SOURCE_REL
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
    uses_secrets = False
    if source.is_file():
        text = source.read_text(encoding="utf-8")
        uses_secrets = "import secrets" in text and (
            "token_hex" in text or "token_urlsafe" in text
        )
    status = PASS if uses_secrets and source_sha and GENERATOR_USES_CSPRNG else FAIL
    return {
        "generator_implementation": GENERATOR_IMPLEMENTATION,
        "uses_os_backed_csprng": uses_secrets and GENERATOR_USES_CSPRNG,
        "generator_source_file": str(GENERATOR_SOURCE_REL).replace("\\", "/"),
        "generator_source_sha256": source_sha,
        "status": status,
        "note": "Does not claim measurable entropy from a single stored value",
    }


@dataclass
class SecretShapeResult:
    document: dict[str, Any]
    loader_password: str | None
    hmac_key_material: str | None
    overall_status: str


def validate_secret_shapes(
    config: VaultRuntimeConfig | None = None,
    *,
    repo: Path | None = None,
) -> SecretShapeResult:
    """Validate secret shapes; retain secrets only in returned object (never persist)."""
    cfg = config or resolve_vault_runtime()
    hmac_data = vault_kv_v2_read(
        cfg, mount=KV_MOUNT, path=LOGICAL_HMAC_PATH, version=EXPECTED_KEY_VERSION
    )
    loader_data = vault_kv_v2_read(
        cfg, mount=KV_MOUNT, path=LOGICAL_LOADER_PATH, version=EXPECTED_KEY_VERSION
    )

    hmac_fields = validate_hmac_secret(hmac_data)
    loader_fields = validate_loader_credential(loader_data)
    hmac_status = field_status_overall(hmac_fields)
    loader_status = field_status_overall(loader_fields)
    provenance = generation_provenance(repo)
    overall = (
        PASS
        if hmac_status == PASS and loader_status == PASS and provenance["status"] == PASS
        else FAIL
    )

    password = loader_data.get("password") if loader_status == PASS else None
    if not isinstance(password, str):
        password = None
    material = hmac_data.get("key_material") if hmac_status == PASS else None
    if not isinstance(material, str):
        material = None

    document = {
        "stage": "03",
        "phase": "alignment_candidate",
        "title": "Vault secret shape validation (sanitised)",
        "document_version": "0.1.1",
        "sanitised": True,
        "secrets_recorded": False,
        "secrets_recorded_in_artifacts": False,
        "vault_addr": cfg.addr,
        "vault_cacert_evidence": cfg.normalised_cacert_evidence(),
        "tls_skip_verify_used": False,
        "contract_references": [CONTRACT_HMAC_REFERENCE, CONTRACT_LOADER_REFERENCE],
        "version_pinned": EXPECTED_KEY_VERSION,
        "hmac_subject_key": {
            "path": f"{KV_MOUNT}/{LOGICAL_HMAC_PATH}",
            "fields": hmac_fields,
            "status": hmac_status,
        },
        "loader_credential": {
            "path": f"{KV_MOUNT}/{LOGICAL_LOADER_PATH}",
            "fields": loader_fields,
            "status": loader_status,
        },
        "generation_provenance": provenance,
        "overall_status": overall,
        "forbidden_in_evidence": [
            "key_material",
            "password",
            "token",
            "role_id",
            "secret_id",
            "dsn",
            "entropy_claim_from_single_value",
        ],
    }
    return SecretShapeResult(
        document=document,
        loader_password=password if overall == PASS else None,
        hmac_key_material=material if overall == PASS else None,
        overall_status=overall,
    )
