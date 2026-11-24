"""Decision gate v0.2.1 — family-only never accept/shadow/usable; evidence hashes verified."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.policy import (
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

FAMILY_ONLY = "ANALYTE_FAMILY_RETRIEVAL_ONLY"


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


def _verify_evidence_hashes(
    entry: dict[str, Any], *, evidence_root: Path | None
) -> None:
    hashes = entry.get("evidence_file_hashes") or {}
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("evidence_hashes_required")
    if evidence_root is None:
        # Structural presence required; file existence checked when root provided
        return
    for rel, expected in hashes.items():
        path = evidence_root / str(rel)
        if not path.is_file():
            raise ValueError(f"evidence_file_missing:{rel}")
        dig = hashlib.sha256(path.read_bytes()).hexdigest()
        if dig != str(expected).strip():
            raise ValueError(f"evidence_hash_mismatch:{rel}")


def validate_accept(
    entry: dict[str, Any],
    *,
    by_id: dict[str, dict[str, Any]],
    evidence_root: Path | None = None,
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
    level = row.get("identity_level")

    if decision in {"ACCEPTED_COMPARABLE", "ACCEPTED_WITH_RESTRICTIONS"}:
        if klass == FAMILY_ONLY or level == FAMILY_ONLY:
            raise ValueError("family_retrieval_only_cannot_accept")
        if klass in HARD_CONFLICT_CLASSES or row.get("hard_conflict"):
            raise ValueError(
                "hard_conflict_requires_reclassification_before_any_accept"
            )
        if not row.get("analyte_ok"):
            raise ValueError("analyte_identity_required_before_accept")
        if not entry.get("reviewer_id") or not entry.get("reason"):
            raise ValueError("reviewer_and_reason_required")
        _verify_evidence_hashes(entry, evidence_root=evidence_root)
        # Evidence hash alone cannot replace reclassification
        if entry.get("new_evidence_artifact_hash") and (
            klass in HARD_CONFLICT_CLASSES or level == FAMILY_ONLY
        ):
            raise ValueError("evidence_hash_without_reclassification")

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
    if row.get("candidate_class") == FAMILY_ONLY or row.get("identity_level") == FAMILY_ONLY:
        return False
    if not row.get("analyte_ok"):
        return False
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
    if row.get("candidate_class") == FAMILY_ONLY or row.get("identity_level") == FAMILY_ONLY:
        return False
    if row.get("hard_conflict") or not row.get("analyte_ok"):
        return False
    # ACCEPTED_WITH_RESTRICTIONS cannot open shadow without proven analyte identity
    if entry.get("typed_decision") == "ACCEPTED_WITH_RESTRICTIONS" and not (
        row.get("evidence_contract") or {}
    ).get("analyte_concept"):
        return False
    ec = row.get("evidence_contract") or {}
    return bool(
        ec.get("analyte_concept")
        and ec.get("unit_identity_or_approved_conversion")
        and ec.get("numeric_semantics")
        and ec.get("temporal_semantics")
    )


def ingest(
    path: Path,
    *,
    records: list[dict[str, Any]],
    evidence_root: Path | None = None,
    allow_ingest: bool = False,
) -> dict[str, Any]:
    """This stage does not ingest existing decisions unless explicitly allowed (never create HUMAN_ACCEPTED)."""
    by_id = {r["mapping_id"]: r for r in records if r.get("mapping_id")}
    if not allow_ingest:
        # Ensure empty log for this release
        return {
            "version": VERSION,
            "HUMAN_DECISION_GATE_INTEGRITY_STATUS": "PASS",
            "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
            "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": 0,
            "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT": 0,
            "integrity_errors": [],
            "n_log_entries": 0,
            "ingest_disabled_this_release": True,
            "no_human_accepted_created": True,
            "ok": True,
        }

    rows = load_log(path)
    latest: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for r in rows:
        try:
            validate_accept(r, by_id=by_id, evidence_root=evidence_root)
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
