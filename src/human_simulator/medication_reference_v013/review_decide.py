"""Typed append-only review decisions (v0.1.3) — does not rewrite v0.1.1 log."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v013.acceptance import (
    latest_v013_by_medicine,
    load_jsonl,
    v013_decision_log_path,
)
from human_simulator.medication_reference_v013.policy import (
    DECISION_TYPES,
    V012_MAPPING,
    VERSION,
)

AUTHORITATIVE_NEEDS_EVIDENCE = frozenset(
    {
        "PRODUCT_IDENTITY_ACCEPTED",
        "INGREDIENT_SET_ACCEPTED",
        "INGREDIENT_FORM_ROUTE_ACCEPTED",
    }
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _load_mapping_row(root: Path, medicine_id: str) -> dict[str, Any] | None:
    for row in load_jsonl(root / V012_MAPPING):
        if str(row.get("source_medicine_id")) == str(medicine_id):
            return row
    # fallback v011
    from human_simulator.medication_reference_v013.policy import V011_MAPPING

    for row in load_jsonl(root / V011_MAPPING):
        if str(row.get("source_medicine_id")) == str(medicine_id):
            return row
    return None


def _candidate_ids(row: dict[str, Any]) -> set[str]:
    ids = set()
    if row.get("provider_concept_id"):
        ids.add(str(row["provider_concept_id"]))
    for c in row.get("candidates") or []:
        if c.get("provider_concept_id"):
            ids.add(str(c["provider_concept_id"]))
    return ids


def append_typed_decision(
    root: Path,
    *,
    source_medicine_id: str,
    decision: str,
    reviewer_id: str | None,
    reason: str | None,
    evidence_hash: str | None,
    candidate_id: str | None = None,
    provider_neutral_concept_id: str | None = None,
    llm_generated: bool = False,
    product_evidence: bool | None = None,
    ingredient_evidence: bool | None = None,
) -> dict[str, Any]:
    if decision not in DECISION_TYPES:
        raise ValueError(f"invalid_decision_type:{decision}")
    if not reviewer_id or not str(reviewer_id).strip():
        raise ValueError("explicit_reviewer_id_required")
    if str(reviewer_id).strip() == "local-reviewer":
        raise ValueError("default_reviewer_local-reviewer_forbidden")
    if not reason or not str(reason).strip():
        raise ValueError("explicit_decision_reason_required")
    if not evidence_hash or not str(evidence_hash).strip():
        raise ValueError("explicit_evidence_hash_required")
    if llm_generated and decision in AUTHORITATIVE_NEEDS_EVIDENCE:
        raise ValueError("llm_cannot_create_accepted_decision")

    row = _load_mapping_row(root, source_medicine_id)
    if row is None:
        raise ValueError("source_medicine_not_in_mapping")

    if decision in AUTHORITATIVE_NEEDS_EVIDENCE:
        if decision == "PRODUCT_IDENTITY_ACCEPTED" and not candidate_id:
            raise ValueError("candidate_id_required_for_product_identity")
        if candidate_id:
            allowed = _candidate_ids(row)
            if candidate_id not in allowed:
                raise ValueError("candidate_not_in_current_candidates")
        if decision == "PRODUCT_IDENTITY_ACCEPTED" and product_evidence is False:
            raise ValueError("product_acceptance_without_product_evidence")
        if decision in {
            "INGREDIENT_SET_ACCEPTED",
            "INGREDIENT_FORM_ROUTE_ACCEPTED",
        } and ingredient_evidence is False:
            raise ValueError("ingredient_acceptance_without_ingredient_evidence")

    prev = latest_v013_by_medicine(root).get(str(source_medicine_id))
    entry = {
        "version": VERSION,
        "source_medicine_id": str(source_medicine_id),
        "decision": decision,
        "candidate_id": candidate_id,
        "provider_neutral_concept_id": provider_neutral_concept_id,
        "reviewer_identifier": str(reviewer_id).strip(),
        "reason": str(reason).strip(),
        "evidence_hash": str(evidence_hash).strip(),
        "timestamp": _now(),
        "llm_generated": bool(llm_generated),
        "previous_decision_hash": (prev or {}).get("entry_hash"),
        "log_namespace": "medication-reference-v013-typed",
        "does_not_modify_v011_decision_log": True,
    }
    entry["entry_hash"] = _sha_obj({k: v for k, v in entry.items() if k != "entry_hash"})
    path = v013_decision_log_path(root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry
