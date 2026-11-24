"""Build scope records. The prior decision text and its answer hash stay as they were."""

from __future__ import annotations

import hashlib
from typing import Any

from human_simulator.stage05_gate_1a_completion_v01.policy import (
    DECIDED_AT,
    PRIOR_RECORDS,
    REVIEWER_LABEL,
    REVIEWER_ROLE,
    SCOPE,
)
from human_simulator.stage05_gate_1a_completion_v01.prior import record_sha256


def reviewer_digest() -> str:
    return hashlib.sha256(REVIEWER_LABEL.encode("utf-8")).hexdigest()


def build_superseding(prior: dict[str, Any], temporal: dict[str, Any]) -> list[dict[str, Any]]:
    excluded = temporal["uncomparable_count"]
    records = []
    for question_id, requires_classification in (("B_TIMING", False), ("B_PERIOD", True)):
        previous = prior["scoped"][question_id]
        records.append({
            "attestation": "accepted",
            "attestation_scope": SCOPE,
            "basis": (
                f"{PRIOR_RECORDS}#{question_id}; workflow rule only; "
                f"excludes {temporal['uncomparable_category']} count={excluded}"
            ),
            "closes_question": False,
            "decided_at": DECIDED_AT,
            "decision": previous["decision"],
            "decision_schema_version": "0.1.1",
            "evidence_sha256": previous["evidence_sha256"],
            "field_path": previous["field_path"],
            "prior_record_sha256": record_sha256(previous),
            "prior_reviewer_digest": previous["reviewer_digest"],
            "prior_role": previous["role"],
            "proposition": previous["proposition"],
            "question_id": question_id,
            "requires_first_vs_repeat_visit_classification": requires_classification,
            "reviewer_digest": reviewer_digest(),
            "role": REVIEWER_ROLE,
            "row_level_proof": False,
            "source_system": previous["source_system"],
            "supersedes_artifact": PRIOR_RECORDS,
        })
    return records


def timing_applies_to_category(category: str, temporal: dict[str, Any]) -> bool:
    return category != temporal["uncomparable_category"]


def period_applies_to_visit(visit_class: str | None) -> bool:
    return visit_class in {"FIRST", "REPEAT"}
