"""Executable contracts for source snapshot fingerprint and canonical payload hash."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import struct
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

CANONICAL_JSON_CONTRACT_VERSION = "4"
SCALAR_SERIALIZATION_CONTRACT_VERSION = "2"

SOURCE_BACKED_PROVENANCE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "record_origin",
        "source_system",
        "source_system_id",
        "source_schema",
        "source_relation",
        "source_record_locator",
        "transformation_id",
        "transformation_version",
        "input_artifact_sha256",
        "confidence",
        "mapping_status",
        "locator_key_version",
        "locator_scheme",
    }
)


class ContractSerializationError(ValueError):
    pass


class MissingRowFieldError(ContractSerializationError):
    pass


class UnsupportedScalarTypeError(ContractSerializationError):
    pass


def length_prefix_utf8(value: str | None) -> bytes:
    if value is None:
        return struct.pack(">I", 0xFFFFFFFF)
    encoded = value.encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


def serialize_scalar(value: Any) -> str:
    if value is None:
        raise ContractSerializationError("serialize_scalar received None; use explicit row null handling")
    if isinstance(value, bool):
        return "bool:true" if value else "bool:false"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"int:{value}"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractSerializationError("non-finite float is forbidden")
        return f"float:{repr(value)}"
    if isinstance(value, Decimal):
        normalized = format(value, "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".") or "0"
        return f"decimal:{normalized}"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ContractSerializationError("naive datetime is forbidden")
        utc = value.astimezone(timezone.utc)
        micros = utc.microsecond
        if micros:
            rendered = utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{micros:06d}Z"
        else:
            rendered = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"datetime:{rendered}"
    if isinstance(value, date):
        return f"date:{value.isoformat()}"
    if isinstance(value, UUID):
        return f"uuid:{value}"
    if isinstance(value, str):
        return value
    raise UnsupportedScalarTypeError(f"unsupported scalar type: {type(value)!r}")


def serialize_row_fields(row: dict[str, Any], field_order: list[str]) -> bytes:
    parts: list[bytes] = []
    for field in field_order:
        if field not in row:
            raise MissingRowFieldError(f"missing expected row field: {field}")
        raw = row[field]
        if raw is None:
            parts.append(length_prefix_utf8(None))
        else:
            parts.append(length_prefix_utf8(serialize_scalar(raw)))
    return b"".join(parts)


def row_content_hmac(
    *,
    source_system: str,
    source_relation: str,
    row: dict[str, Any],
    field_order: list[str],
    secret: bytes,
    contract_version: str = "2",
) -> str:
    domain = f"source_snapshot_row|{contract_version}|{source_system}|{source_relation}".encode("utf-8")
    payload = serialize_row_fields(row, field_order)
    message = struct.pack(">I", len(domain)) + domain + payload
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def relation_aggregate_hmac(*, ordered_row_hmacs: list[str], secret: bytes) -> str:
    parts = b"".join(bytes.fromhex(value) for value in ordered_row_hmacs)
    return hmac.new(secret, parts, hashlib.sha256).hexdigest()


def snapshot_aggregate_hmac(*, relation_hmacs: list[str], secret: bytes) -> str:
    parts = b"".join(bytes.fromhex(value) for value in relation_hmacs)
    return hmac.new(secret, parts, hashlib.sha256).hexdigest()


def _normalize_decimal_string(value: Decimal) -> str:
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".") or "0"
    return normalized


def _normalize_datetime_string(value: datetime) -> str:
    if value.tzinfo is None:
        raise ContractSerializationError("naive datetime is forbidden")
    utc = value.astimezone(timezone.utc)
    micros = utc.microsecond
    if micros:
        return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{micros:06d}Z"
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_canonical_json(value: Any) -> Any:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, int) and not isinstance(value, bool):
        return ["integer", value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractSerializationError("non-finite float is forbidden")
        return ["float", repr(value)]
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, Decimal):
        return ["decimal", _normalize_decimal_string(value)]
    if isinstance(value, datetime):
        return ["datetime", _normalize_datetime_string(value)]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, UUID):
        return ["uuid", str(value)]
    if isinstance(value, tuple):
        raise ContractSerializationError("tuple is forbidden; use list")
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise ContractSerializationError("object keys must be strings")
        entries = [[key, normalize_canonical_json(value[key])] for key in sorted(value)]
        return ["object", entries]
    if isinstance(value, list):
        return ["list", [normalize_canonical_json(item) for item in value]]
    raise UnsupportedScalarTypeError(f"unsupported canonical json type: {type(value)!r}")


def canonical_json_dumps(value: Any) -> str:
    normalized = normalize_canonical_json(value)
    return json.dumps(normalized, separators=(",", ":"), ensure_ascii=False)


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = canonical_json_dumps(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_stable_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    return {key: provenance[key] for key in sorted(provenance) if key in SOURCE_BACKED_PROVENANCE_ALLOWLIST}


def build_stable_payload(
    *,
    canonical_entity: str,
    canonical_id: str,
    stable_clinical_fields: dict[str, Any],
    provenance: dict[str, Any],
    source_record_locator: str,
    mapping_status: str,
    mapping_version: str,
    transformation_version: str,
) -> dict[str, Any]:
    return {
        "canonical_entity": canonical_entity,
        "canonical_id": canonical_id,
        "stable_clinical_fields": stable_clinical_fields,
        "stable_source_backed_provenance": build_stable_provenance(provenance),
        "source_record_locator": source_record_locator,
        "mapping_status": mapping_status,
        "mapping_version": mapping_version,
        "transformation_version": transformation_version,
    }


def classify_promotion(
    *,
    canonical_id_present: bool,
    payload_hash_match: bool,
    input_version_tuple_match: bool,
    mapping_or_transform_changed: bool,
) -> str:
    if not canonical_id_present:
        return "INSERT"
    if payload_hash_match:
        return "NOOP_ALREADY_PUBLISHED"
    if mapping_or_transform_changed:
        return "VERSIONED_REBUILD_REQUIRED"
    if input_version_tuple_match:
        return "SOURCE_PAYLOAD_CHANGED"
    return "CANONICAL_PAYLOAD_CONFLICT"
