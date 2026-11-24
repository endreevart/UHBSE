"""Decision gate v0.2 — hard conflicts require reclassification, not hash alone."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v02.policy import (
    HARD_CONFLICT_CLASSES,
    VERSION,
)

NON_USABLE_RESTRICTIONS = frozenset(
    {
        "analyte_unverified",
        "specimen_unverified",
        "assay_unverified",
        "unit_unverified",
        "numeric_semantics_unverified",
    }
)


def decision_log_path(pack: Path) -> Path:
    return Path(pack) / "decision-log.jsonl"


def load_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_accept(
    entry: dict[str, Any],
    *,
    by_id: dict[str, dict[str, Any]],
) -> None:
    mid = str(entry.get("mapping_id") or "")
    if mid not in by_id:
        raise ValueError("arbitrary_or_unknown_mapping_id")
    row = by_id[mid]
    if entry.get("classification_hash") != row.get("classification_hash"):
        raise ValueError("stale_classification_hash")
    if entry.get("a_stratum_hash") != row.get("a_stratum_hash"):
        raise ValueError("stale_a_stratum_hash")
    if row.get("b_raw_code") and entry.get("b_stratum_hash") != row.get("b_stratum_hash"):
        raise ValueError("stale_b_stratum_hash")

    decision = entry.get("typed_decision")
    klass = row.get("candidate_class")

    if decision in {"ACCEPTED_COMPARABLE", "ACCEPTED_WITH_RESTRICTIONS"}:
        if klass in HARD_CONFLICT_CLASSES:
            # Even with new_evidence_artifact_hash alone — FORBIDDEN until reclassified
            raise ValueError(
                "hard_conflict_requires_reclassification_before_any_accept"
            )
        if not entry.get("reviewer_id") or not entry.get("reason"):
            raise ValueError("reviewer_and_reason_required")
        if not entry.get("evidence_file_hashes"):
            raise ValueError("evidence_hashes_required")

    if decision == "ACCEPTED_COMPARABLE":
        ec = row.get("evidence_contract") or {}
        for k in (
            "analyte_concept",
            "specimen_material",
            "method_assay_compatibility",
            "unit_identity_or_approved_conversion",
            "numeric_semantics",
            "temporal_semantics",
            "provenance_isolation",
        ):
            if not ec.get(k):
                raise ValueError(f"accepted_comparable_requires_{k}")


def is_scientifically_usable(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    if entry.get("typed_decision") != "ACCEPTED_COMPARABLE":
        if entry.get("typed_decision") != "ACCEPTED_WITH_RESTRICTIONS":
            return False
        restrictions = set(entry.get("restrictions") or [])
        if restrictions & NON_USABLE_RESTRICTIONS:
            return False
        ec = row.get("evidence_contract") or {}
        return bool(
            ec.get("analyte_concept")
            and ec.get("specimen_material")
            and ec.get("method_assay_compatibility")
            and ec.get("unit_identity_or_approved_conversion")
            and ec.get("numeric_semantics")
            and not row.get("hard_conflict")
        )
    return True


def is_technical_shadow_eligible(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    if entry.get("typed_decision") not in {
        "ACCEPTED_COMPARABLE",
        "ACCEPTED_WITH_RESTRICTIONS",
    }:
        return False
    if row.get("hard_conflict"):
        return False
    ec = row.get("evidence_contract") or {}
    return bool(
        ec.get("analyte_concept")
        and ec.get("unit_identity_or_approved_conversion")
        and ec.get("numeric_semantics")
        and ec.get("temporal_semantics")
    )


def ingest(path: Path, *, records: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {r["mapping_id"]: r for r in records}
    rows = load_log(path)
    latest: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for r in rows:
        try:
            validate_accept(r, by_id=by_id)
            latest[str(r["mapping_id"])] = r
        except ValueError as e:
            errors.append(f"{r.get('mapping_id')}:{e}")

    domain = [
        r
        for r in latest.values()
        if r.get("typed_decision")
        in {"ACCEPTED_COMPARABLE", "ACCEPTED_WITH_RESTRICTIONS"}
    ]
    usable = [
        r for r in domain if is_scientifically_usable(r, by_id[r["mapping_id"]])
    ]
    shadow = [
        r for r in domain if is_technical_shadow_eligible(r, by_id[r["mapping_id"]])
    ]
    return {
        "version": VERSION,
        "HUMAN_DECISION_GATE_INTEGRITY_STATUS": "PASS" if not errors else "FAIL",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": len(domain),
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": len(usable),
        "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT": len(shadow),
        "integrity_errors": errors[:20],
        "n_log_entries": len(rows),
        "ok": not errors,
    }
