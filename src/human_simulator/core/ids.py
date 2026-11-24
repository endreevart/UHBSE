"""Opaque ID helpers for core vertical slice (HMAC; never emit raw patient IDs)."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

from human_simulator.core.policy import ID_NAMESPACE_VERSION, KEY_VERSION, SOURCE_SYSTEM_ID
from human_simulator.stage03.canonical_id import compute_hmac_hex, length_prefix_utf8


def load_hmac_key(repo_root: Path) -> bytes:
    """Runtime HMAC key from env or private file — never logged.

    Precedence preserves identity continuity with the accepted core vertical slice:
    1. ``UHBSE_CORE_HMAC_KEY`` (explicit core secret)
    2. ``private/uhbse-core-hmac.key``
    3. Deterministic local-dev fallback from ``canonical-db.env`` (same material used
       by the accepted pilot canonical load)
    4. ``LINKAGE_HMAC_KEY`` / ``private/linkage-hmac.key`` only as last resort —
       Stage-02 linkage material must not silently re-key existing canonical IDs.
    """
    core_env = os.environ.get("UHBSE_CORE_HMAC_KEY")
    if core_env:
        return core_env.encode("utf-8")
    core_path = repo_root / "private" / "uhbse-core-hmac.key"
    if core_path.is_file():
        return core_path.read_bytes().strip()
    seed_path = repo_root / "canonical-db.env"
    if seed_path.is_file():
        return hashlib.sha256(b"uhbse-core-vertical-slice|" + seed_path.read_bytes()).digest()
    linkage_env = os.environ.get("LINKAGE_HMAC_KEY")
    if linkage_env:
        return linkage_env.encode("utf-8")
    linkage_path = repo_root / "private" / "linkage-hmac.key"
    if linkage_path.is_file():
        return linkage_path.read_bytes().strip()
    return hashlib.sha256(b"uhbse-core-vertical-slice|uhbse-core-dev").digest()


def opaque_subject_key(key: bytes, patient_id: int | str) -> str:
    return compute_hmac_hex(
        key_bytes=key,
        entity="Subject",
        id_namespace_version=ID_NAMESPACE_VERSION,
        source_system=SOURCE_SYSTEM_ID,
        inputs=[str(patient_id), KEY_VERSION],
    )


def entity_id(key: bytes, entity: str, *parts: str) -> str:
    return compute_hmac_hex(
        key_bytes=key,
        entity=entity,
        id_namespace_version=ID_NAMESPACE_VERSION,
        source_system=SOURCE_SYSTEM_ID,
        inputs=[*parts, KEY_VERSION],
    )


def locator(key: bytes, relation: str, pk: str) -> str:
    msg = length_prefix_utf8(f"locator|{SOURCE_SYSTEM_ID}|{relation}|{pk}|{KEY_VERSION}")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()
