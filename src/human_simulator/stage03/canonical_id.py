"""Canonical ID contract computation and validation (design phase)."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any

NULL_LENGTH_PREFIX = 0xFFFFFFFF


@dataclass(frozen=True)
class CanonicalIdValidationError:
    name: str
    detail: str


def length_prefix_utf8(value: str | None) -> bytes:
    """Serialize one field per canonical-id-contract message_layout."""
    if value is None:
        return NULL_LENGTH_PREFIX.to_bytes(4, byteorder="big")
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(4, byteorder="big") + encoded


def get_document_version(contract: dict[str, Any]) -> str:
    return str(contract.get("document_version") or contract.get("version") or "")


def get_id_namespace_version(contract: dict[str, Any]) -> str:
    namespace = contract.get("id_namespace_version")
    if namespace:
        return str(namespace)
    test_block = contract.get("test_vectors", {})
    if test_block.get("id_namespace_version"):
        return str(test_block["id_namespace_version"])
    return str(test_block.get("contract_version") or get_document_version(contract))


def build_domain(entity: str, id_namespace_version: str, source_system: str) -> str:
    return f"{entity}|{id_namespace_version}|{source_system}"


def compute_hmac_hex(
    *,
    key_bytes: bytes,
    entity: str,
    id_namespace_version: str,
    source_system: str,
    inputs: list[str | None],
) -> str:
    message = length_prefix_utf8(build_domain(entity, id_namespace_version, source_system))
    for item in inputs:
        message += length_prefix_utf8(item)
    return hmac.new(key_bytes, message, hashlib.sha256).hexdigest()


def null_and_empty_distinct() -> bool:
    return length_prefix_utf8(None) != length_prefix_utf8("")


def validate_key_rotation_policy(contract: dict[str, Any]) -> list[CanonicalIdValidationError]:
    errors: list[CanonicalIdValidationError] = []
    rotation = contract.get("key_rotation", {})
    runtime = rotation.get("runtime_secret_rotation", {})
    rule = str(runtime.get("rule", ""))
    forbidden = runtime.get("forbidden", [])
    if not isinstance(forbidden, list):
        forbidden = []

    if "secret_change_without_key_version_bump" not in forbidden:
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_key_rotation_forbidden",
                "secret_change_without_key_version_bump must be forbidden",
            )
        )
    if re.search(r"must not change canonical ids?", rule, re.IGNORECASE):
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_key_rotation_false_claim",
                "must not claim secret rotation leaves canonical IDs unchanged at same key_version",
            )
        )
    if "claiming_same_key_version_after_secret_rotation" not in forbidden:
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_key_rotation_claim_forbidden",
                "claiming_same_key_version_after_secret_rotation must be forbidden",
            )
        )
    return errors


def validate_canonical_id_contract_document(contract: dict[str, Any]) -> list[CanonicalIdValidationError]:
    errors: list[CanonicalIdValidationError] = []
    spec = contract.get("canonical_id_contract", {})
    document_version = get_document_version(contract)
    id_namespace_version = get_id_namespace_version(contract)
    binding = spec.get("identity_rule_binding", {})
    key_version = spec.get("key_version", {})
    input_fields = spec.get("input_fields", {})
    domain = spec.get("domain_separation", {})

    if not document_version:
        errors.append(CanonicalIdValidationError("canonical_id_document_version", "document_version required"))
    if not id_namespace_version:
        errors.append(CanonicalIdValidationError("canonical_id_namespace_version", "id_namespace_version required"))
    if domain.get("id_namespace_version_field") != "id_namespace_version":
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_domain_namespace_field",
                "domain_separation must use id_namespace_version_field: id_namespace_version",
            )
        )
    if "{id_namespace_version}" not in str(domain.get("format", "")):
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_domain_format",
                "domain_separation.format must reference id_namespace_version",
            )
        )

    if spec.get("output_encoding") != "hex":
        errors.append(CanonicalIdValidationError("canonical_id_output_encoding", "output_encoding must be hex"))
    if spec.get("alternate_output_encoding"):
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_no_alternate_encoding",
                "alternate_output_encoding forbidden; hex is sole canonical encoding",
            )
        )
    if input_fields.get("null_encoding") == "empty_utf8_string":
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_null_encoding",
                "null must not encode as empty UTF-8 string",
            )
        )
    if not null_and_empty_distinct():
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_null_empty_distinct",
                "null and empty string must serialize differently",
            )
        )
    message_layout = spec.get("message_layout")
    if not message_layout:
        errors.append(CanonicalIdValidationError("canonical_id_message_layout", "message_layout required"))
    elif "length_prefix(domain)" not in message_layout:
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_message_layout_format",
                "message_layout must describe length_prefix(domain) || length_prefix(inputs)",
            )
        )

    expected_contract_ref = binding.get("contract_reference")
    if not expected_contract_ref:
        errors.append(
            CanonicalIdValidationError("canonical_id_contract_reference", "identity_rule_binding.contract_reference required")
        )

    key_reference = key_version.get("key_reference")
    if not key_reference:
        errors.append(CanonicalIdValidationError("canonical_id_key_reference", "key_version.key_reference required"))

    errors.extend(validate_key_rotation_policy(contract))

    test_block = contract.get("test_vectors", {})
    active_namespace = test_block.get("id_namespace_version") or test_block.get("contract_version")
    if active_namespace != id_namespace_version:
        errors.append(
            CanonicalIdValidationError(
                "canonical_id_test_vectors_namespace",
                f"test_vectors namespace {active_namespace!r} != id_namespace_version {id_namespace_version!r}",
            )
        )

    key_hex = test_block.get("artificial_key_hex")
    if not isinstance(key_hex, str):
        errors.append(CanonicalIdValidationError("canonical_id_test_key", "test_vectors.artificial_key_hex required"))
        return errors

    key_bytes = bytes.fromhex(key_hex)
    for vector in test_block.get("vectors", []):
        if not isinstance(vector, dict):
            continue
        expected = vector.get("expected_hex")
        computed = compute_hmac_hex(
            key_bytes=key_bytes,
            entity=str(vector.get("entity", "")),
            id_namespace_version=str(id_namespace_version),
            source_system=str(vector.get("source_system", "")),
            inputs=[str(v) if v is not None else None for v in vector.get("inputs", [])],
        )
        if expected != computed:
            errors.append(
                CanonicalIdValidationError(
                    f"canonical_id_test_vector_{vector.get('name', 'unknown')}",
                    f"expected {expected}, computed {computed}",
                )
            )

    return errors


def validate_identity_rule_references(
    identity_rule: dict[str, Any],
    *,
    canonical_id_contract: dict[str, Any],
    group_id: str,
) -> list[CanonicalIdValidationError]:
    errors: list[CanonicalIdValidationError] = []
    spec = canonical_id_contract.get("canonical_id_contract", {})
    binding = spec.get("identity_rule_binding", {})
    expected_contract = binding.get("contract_reference")
    expected_key_ref = spec.get("key_version", {}).get("key_reference")

    for field_name, rule in identity_rule.items():
        if not isinstance(rule, dict):
            continue
        contract_ref = rule.get("contract")
        if expected_contract and contract_ref != expected_contract:
            errors.append(
                CanonicalIdValidationError(
                    f"construction_group_{group_id}_contract_ref",
                    f"{group_id}.{field_name} contract {contract_ref!r} != {expected_contract!r}",
                )
            )
        key_ref = rule.get("key_reference")
        if expected_key_ref and key_ref != expected_key_ref:
            errors.append(
                CanonicalIdValidationError(
                    f"construction_group_{group_id}_key_ref",
                    f"{group_id}.{field_name} key_reference {key_ref!r} != {expected_key_ref!r}",
                )
            )
    return errors
