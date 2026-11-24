"""Provenance and typed-value validators for Core Vertical Slice v0.1.2."""

from __future__ import annotations

from typing import Any

TYPED_VALUE_FIELDS: tuple[str, ...] = (
    "numeric_value",
    "text_value",
    "categorical_value",
    "boolean_value",
)

COMPUTED_REQUIRED: tuple[str, ...] = (
    "record_origin",
    "input_record_references",
    "computation_method",
    "computation_version",
    "uncertainty",
    "transformation_id",
    "transformation_version",
    "transformed_at",
    "input_artifact_sha256",
    "confidence",
    "mapping_status",
)

COMPUTED_FORBIDDEN: tuple[str, ...] = ("source_record_locator",)

SOURCE_REQUIRED: tuple[str, ...] = (
    "record_origin",
    "source_system",
    "source_schema",
    "source_relation",
    "source_record_locator",
    "transformation_id",
    "transformation_version",
    "transformed_at",
    "input_artifact_sha256",
    "confidence",
    "mapping_status",
)


def typed_value_xor_status(component: dict[str, Any] | Any) -> dict[str, Any]:
    """Exactly one typed value for non-missing components; zero for missing."""
    get = component.get if isinstance(component, dict) else lambda k, d=None: getattr(component, k, d)
    miss = get("missingness_status")
    filled = [f for f in TYPED_VALUE_FIELDS if get(f) is not None]
    if miss == "missing":
        ok = len(filled) == 0
        return {
            "ok": ok,
            "filled": filled,
            "rule": "missing_requires_zero_typed_values",
        }
    ok = len(filled) == 1
    return {
        "ok": ok,
        "filled": filled,
        "rule": "exactly_one_typed_value",
    }


def validate_computed_provenance(prov: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(prov, dict):
        return {"ok": False, "missing": list(COMPUTED_REQUIRED), "forbidden_present": [], "detail": "not_a_dict"}
    missing = [f for f in COMPUTED_REQUIRED if f not in prov or prov[f] in (None, "", [])]
    forbidden_present = [f for f in COMPUTED_FORBIDDEN if f in prov and prov[f] is not None]
    origin = prov.get("record_origin")
    if origin not in {"DERIVED", "IMPUTED"}:
        missing.append("record_origin_must_be_DERIVED_or_IMPUTED")
    refs = prov.get("input_record_references")
    if not isinstance(refs, list) or not refs:
        if "input_record_references" not in missing:
            missing.append("input_record_references")
    return {
        "ok": not missing and not forbidden_present,
        "missing": missing,
        "forbidden_present": forbidden_present,
    }


def validate_source_provenance(prov: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(prov, dict):
        return {"ok": False, "missing": list(SOURCE_REQUIRED), "detail": "not_a_dict"}
    missing = [f for f in SOURCE_REQUIRED if f not in prov or prov[f] in (None, "")]
    return {"ok": not missing, "missing": missing}


def evaluate_db_provenance_coverage(conn: Any) -> dict[str, Any]:
    """Full-table provenance coverage for the seven canonical evidence tables."""
    entities = {
        "source_system": None,  # no provenance column
        "source_record": "provenance",
        "subject": "provenance",
        "subject_characteristic": "provenance",
        "encounter": "provenance",
        "observation": "provenance",
        "observation_component": "provenance",
    }
    per_entity: dict[str, Any] = {}
    total = 0
    valid = 0
    invalid = 0
    invalid_by_entity: dict[str, int] = {}
    with conn.cursor() as cur:
        for entity, col in entities.items():
            if col is None:
                cur.execute(f"SELECT COUNT(*) FROM canonical_evidence.{entity}")  # noqa: S608
                n = int(cur.fetchone()[0])
                per_entity[entity] = {
                    "total": n,
                    "valid": n,
                    "invalid": 0,
                    "note": "no_provenance_column_identity_row",
                }
                total += n
                valid += n
                continue
            cur.execute(f"SELECT {col} FROM canonical_evidence.{entity}")  # noqa: S608
            rows = cur.fetchall()
            ent_invalid = 0
            for (prov,) in rows:
                check = validate_source_provenance(prov if isinstance(prov, dict) else None)
                if not check["ok"]:
                    ent_invalid += 1
            ent_total = len(rows)
            ent_valid = ent_total - ent_invalid
            per_entity[entity] = {
                "total": ent_total,
                "valid": ent_valid,
                "invalid": ent_invalid,
            }
            total += ent_total
            valid += ent_valid
            invalid += ent_invalid
            if ent_invalid:
                invalid_by_entity[entity] = ent_invalid
    return {
        "total_records_evaluated": total,
        "valid_records": valid,
        "invalid_records": invalid,
        "invalid_by_entity": invalid_by_entity,
        "per_entity": per_entity,
        "full_coverage": invalid == 0 and total > 0,
    }


def evaluate_snapshot_provenance(
    snapshot: dict[str, Any],
    *,
    known_entity_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Validate snapshot + components against COMPUTED provenance and typed XOR."""
    snap_prov = validate_computed_provenance(snapshot.get("provenance"))
    xor_violations = 0
    comp_invalid = 0
    unresolved = 0
    components = snapshot.get("components") or []
    for c in components:
        xor = typed_value_xor_status(c)
        if not xor["ok"]:
            xor_violations += 1
        cp = validate_computed_provenance(c.get("provenance"))
        if not cp["ok"]:
            comp_invalid += 1
        refs = (c.get("provenance") or {}).get("input_record_references") or c.get(
            "input_record_references"
        ) or []
        for ref in refs:
            eid = str(ref.get("entity_id") or "")
            if known_entity_ids is not None and eid and eid not in known_entity_ids:
                unresolved += 1
    return {
        "snapshot_provenance_ok": snap_prov["ok"],
        "snapshot_provenance_detail": snap_prov,
        "component_count": len(components),
        "component_provenance_invalid": comp_invalid,
        "typed_value_xor_violations": xor_violations,
        "unresolved_input_references": unresolved,
        "ok": snap_prov["ok"]
        and comp_invalid == 0
        and xor_violations == 0
        and unresolved == 0,
    }
