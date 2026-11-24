"""Strengthened human decision gate — v0.1.1 corrective."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v011.policy import (
    HARD_CONFLICT_CLASSES,
    NON_USABLE_RESTRICTIONS,
    TYPED_DECISIONS,
    VERSION,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def stratum_hash(stratum: dict[str, Any] | None) -> str:
    return _hash(stratum or {})


def decision_log_path(runtime: Path) -> Path:
    return Path(runtime) / "decision-log.jsonl"


def load_decision_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def validate_decision_against_contract(
    entry: dict[str, Any],
    *,
    universe: dict[str, Any],
    classifications_by_id: dict[str, dict[str, Any]],
    strata_by_id: dict[str, dict[str, Any]],
) -> None:
    """Fail closed for stale hashes, unknown mapping_id, hard conflicts on ACCEPTED_COMPARABLE."""
    mid = str(entry.get("mapping_id") or "")
    if not mid or mid not in strata_by_id:
        raise ValueError("arbitrary_or_unknown_mapping_id")
    if mid not in classifications_by_id:
        raise ValueError("mapping_id_missing_classification")

    if entry.get("universe_hash") != universe.get("universe_hash"):
        raise ValueError("stale_or_missing_universe_hash")
    klass_row = classifications_by_id[mid]
    if entry.get("classification_hash") != klass_row.get("classification_hash"):
        raise ValueError("stale_classification_hash")

    stratum = strata_by_id[mid]
    expected_a = stratum_hash(stratum.get("source_a"))
    expected_b = stratum_hash(stratum.get("source_b"))
    if entry.get("source_a_stratum_hash") != expected_a:
        raise ValueError("stale_source_a_stratum_hash")
    if entry.get("source_b_stratum_hash") != expected_b:
        raise ValueError("stale_source_b_stratum_hash")

    decision = entry.get("typed_decision")
    if decision not in TYPED_DECISIONS:
        raise ValueError(f"invalid_typed_decision:{decision}")

    required_common = (
        "reviewer_id",
        "reviewer_role",
        "reason",
        "decision_scope",
        "evidence_file_hashes",
    )
    for k in required_common:
        if decision in {"ACCEPTED_COMPARABLE", "ACCEPTED_WITH_RESTRICTIONS"}:
            val = entry.get(k)
            if val is None or val == "" or val == {} or val == []:
                raise ValueError(f"{k}_required_for_accepted")

    ec = klass_row.get("evidence_contract") or {}
    candidate_class = klass_row.get("candidate_class")
    restrictions = list(entry.get("restrictions") or [])

    if decision == "ACCEPTED_COMPARABLE":
        if candidate_class in HARD_CONFLICT_CLASSES:
            raise ValueError("hard_conflict_blocks_accepted_comparable")
        required_ec = (
            "analyte_concept",
            "specimen_material",
            "method_assay_compatibility",
            "unit_identity_or_approved_conversion",
            "numeric_semantics",
            "temporal_semantics",
            "provenance_isolation",
        )
        for key in required_ec:
            if not ec.get(key):
                raise ValueError(f"accepted_comparable_requires_{key}")
        if klass_row.get("conflicts"):
            raise ValueError("hard_conflicts_present")
        # Cannot override hard conflict without new evidence + reclassification
        if entry.get("overrides_hard_conflict"):
            raise ValueError("hard_conflict_override_forbidden_without_reclassification")

    if decision == "ACCEPTED_WITH_RESTRICTIONS":
        if candidate_class in HARD_CONFLICT_CLASSES and not entry.get(
            "new_evidence_artifact_hash"
        ):
            raise ValueError(
                "hard_conflict_cannot_be_overridden_without_new_evidence_and_reclassification"
            )
        if not restrictions:
            raise ValueError("restrictions_required_for_accepted_with_restrictions")


def is_scientifically_usable(entry: dict[str, Any]) -> bool:
    decision = entry.get("typed_decision")
    if decision == "ACCEPTED_COMPARABLE":
        return True
    if decision != "ACCEPTED_WITH_RESTRICTIONS":
        return False
    restrictions = set(entry.get("restrictions") or [])
    if restrictions & NON_USABLE_RESTRICTIONS:
        return False
    return True


def is_technical_shadow_eligible(entry: dict[str, Any]) -> bool:
    """Technical shadow may include restricted accepts; still not scientific independence."""
    return entry.get("typed_decision") in {
        "ACCEPTED_COMPARABLE",
        "ACCEPTED_WITH_RESTRICTIONS",
    }


def ingest_decisions_v011(
    path: Path,
    *,
    universe: dict[str, Any],
    classifications: list[dict[str, Any]],
    strata: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = load_decision_log(path)
    by_class = {c["mapping_id"]: c for c in classifications}
    by_stratum = {s["mapping_id"]: s for s in strata}
    latest: dict[str, dict[str, Any]] = {}
    integrity_ok = True
    errors: list[str] = []
    for r in rows:
        mid = str(r.get("mapping_id"))
        try:
            validate_decision_against_contract(
                r,
                universe=universe,
                classifications_by_id=by_class,
                strata_by_id=by_stratum,
            )
        except ValueError as e:
            integrity_ok = False
            errors.append(f"{mid}:{e}")
            continue
        latest[mid] = r

    domain_accepted = [
        r
        for r in latest.values()
        if r.get("typed_decision")
        in {"ACCEPTED_COMPARABLE", "ACCEPTED_WITH_RESTRICTIONS"}
    ]
    usable = [r for r in domain_accepted if is_scientifically_usable(r)]
    shadow = [r for r in domain_accepted if is_technical_shadow_eligible(r)]

    return {
        "version": VERSION,
        "HUMAN_DECISION_GATE_INTEGRITY_STATUS": "PASS" if integrity_ok else "FAIL",
        "n_log_entries": len(rows),
        "DOMAIN_ACCEPTED_MAPPING_COUNT": len(domain_accepted),
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": len(usable),
        "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT": len(shadow),
        "usable_accepted": [
            {"mapping_id": r["mapping_id"], "typed_decision": r["typed_decision"]}
            for r in usable
        ],
        "integrity_errors": errors[:20],
        "ok": integrity_ok,
    }


def build_acceptance_gate_doc() -> dict[str, Any]:
    return {
        "version": VERSION,
        "ACCEPTED_COMPARABLE_requires": [
            "analyte confirmed",
            "specimen confirmed",
            "assay/method compatibility confirmed",
            "unit exact or approved conversion contract",
            "numeric semantics confirmed",
            "temporal semantics confirmed",
            "provenance isolation PASS",
            "no hard conflicts",
            "mapping_id + universe_hash + classification_hash + stratum hashes",
            "reviewer_id + reviewer_role + reason + decision_scope + evidence hashes",
        ],
        "ACCEPTED_WITH_RESTRICTIONS_not_scientifically_usable_if": sorted(
            NON_USABLE_RESTRICTIONS
        ),
        "hard_conflict_override": "FORBIDDEN without new evidence artifact and reclassification",
        "counts_separated": [
            "DOMAIN_ACCEPTED_MAPPING_COUNT",
            "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT",
            "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT",
        ],
    }
