"""Readiness impact + classifier threshold options (no invented global policy)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.policy import (
    ACCEPTED_GS011_ARTIFACT_DIR,
    ACCEPTED_PRIVACY_XS_ARTIFACT_DIR,
    VERSION,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def existing_classifier_min_accepted(root: Path) -> int | None:
    """Return configured min accepted outcomes if present; else None (do not invent)."""
    candidates = [
        Path(root) / ACCEPTED_GS011_ARTIFACT_DIR / "policy.json",
        Path(root) / ACCEPTED_PRIVACY_XS_ARTIFACT_DIR / "policy.json",
        Path(root) / "config" / "current-state-classifier-policy.json",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        doc = _load_json(p)
        for key in (
            "min_accepted_comparable_outcomes",
            "MIN_ACCEPTED_COMPARABLE_OUTCOMES",
            "classifier_min_accepted_outcomes",
        ):
            if key in doc and doc[key] is not None:
                return int(doc[key])
    return None


def build_threshold_options(root: Path) -> dict[str, Any]:
    configured = existing_classifier_min_accepted(root)
    if configured is not None:
        return {
            "version": VERSION,
            "THRESHOLD_DECISION_REQUIRED": False,
            "configured_min_accepted_outcomes": configured,
            "options": [],
            "note": "Existing policy threshold found; no new global policy written.",
        }
    return {
        "version": VERSION,
        "THRESHOLD_DECISION_REQUIRED": True,
        "configured_min_accepted_outcomes": None,
        "options": [
            {
                "option_id": "T1",
                "min_scientifically_usable_accepted": 1,
                "rationale": "Minimal single-outcome pilot readiness (owner decision required)",
            },
            {
                "option_id": "T3",
                "min_scientifically_usable_accepted": 3,
                "rationale": "Small multi-analyte set before classifier training gate",
            },
            {
                "option_id": "T5",
                "min_scientifically_usable_accepted": 5,
                "rationale": "Broader coverage before classifier training gate",
            },
        ],
        "note": (
            "No existing policy min-accepted threshold found. "
            "Do not write a new global policy without owner decision."
        ),
        "global_policy_written": False,
    }


def readiness_for_candidate(
    *,
    classification: dict[str, Any],
    stratum: dict[str, Any],
    b_split: dict[str, Any] | None,
    a_split: dict[str, Any] | None,
) -> dict[str, Any]:
    b = stratum.get("source_b") or {}
    a = stratum.get("source_a") or {}
    cov = classification.get("coverage") or {}
    b_train = b_val = b_test = None
    if b_split and isinstance(b_split.get("n_subjects"), dict):
        # Aggregate only — not outcome-specific split counts (unknown without subject×OU join)
        ns = b_split["n_subjects"]
        b_train, b_val, b_test = ns.get("train"), ns.get("validation"), ns.get("test")
    a_train = a_val = a_test = None
    if a_split and isinstance(a_split.get("n_subjects"), dict):
        ns = a_split["n_subjects"]
        a_train, a_val, a_test = ns.get("train"), ns.get("validation"), ns.get("test")

    usable_if_accepted = classification.get("candidate_class") in {
        "SEMANTICALLY_ALIGNED_CANDIDATE",
        "ASSAY_MISSING",  # still needs restrictions
        "SPECIMEN_MISSING",
    }
    restrictions = []
    if "specimen_material" in (classification.get("missing_evidence") or []):
        restrictions.append("specimen_unverified")
    if "method_assay" in (classification.get("missing_evidence") or []):
        restrictions.append("method_assay_unverified")
    if classification.get("candidate_class") == "UNIT_CONFLICT":
        restrictions.append("unit_conflict_blocks_unrestricted")
    if classification.get("candidate_class") == "ANALYTE_AMBIGUOUS":
        restrictions.append("analyte_ambiguous_blocks_accept")

    zero_shot_possible = (
        usable_if_accepted
        and classification.get("candidate_class")
        not in {"ANALYTE_AMBIGUOUS", "UNIT_CONFLICT", "NUMERIC_SEMANTICS_CONFLICT"}
        and bool(a.get("model_file_hash"))
        and int(cov.get("b_subjects_with_pairs") or 0) > 0
    )

    return {
        "mapping_id": classification["mapping_id"],
        "a_outcome": classification.get("a_outcome"),
        "b_raw_code": classification.get("b_raw_code"),
        "if_accepted": {
            "a_split_subjects_available_aggregate": {
                "train": a_train,
                "validation": a_val,
                "test": a_test,
            },
            "b_split_subjects_available_aggregate": {
                "train": b_train,
                "validation": b_val,
                "test": b_test,
            },
            "b_subjects_with_pairs": cov.get("b_subjects_with_pairs"),
            "b_strict_pairs": cov.get("b_strict_pairs"),
            "frozen_a_provider_applicable": bool(a.get("model_file_hash")),
            "unit_specimen_assay_restrictions": restrictions,
            "a_to_b_technical_zero_shot_possible": zero_shot_possible,
            "b_as_independent_verification": False,  # INDEPENDENCE_NOT_ESTABLISHED
            "independence_status_unchanged": "INDEPENDENCE_NOT_ESTABLISHED",
        },
        "candidate_class": classification.get("candidate_class"),
        "note": "Independence not established automatically after accept.",
    }


def build_readiness_impact(
    *,
    root: Path,
    classifications: list[dict[str, Any]],
    strata: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {s["mapping_id"]: s for s in strata}
    a_split = _load_json(
        Path(root) / ACCEPTED_GS011_ARTIFACT_DIR / "global-subject-split-contract.json"
    )
    b_split = _load_json(
        Path(root)
        / ACCEPTED_PRIVACY_XS_ARTIFACT_DIR
        / "source-b-global-split-contract.json"
    )
    impacts = [
        readiness_for_candidate(
            classification=c,
            stratum=by_id.get(c["mapping_id"]) or {},
            b_split=b_split,
            a_split=a_split,
        )
        for c in classifications
        if c.get("has_b_candidate") is not False and c.get("b_raw_code")
    ]
    threshold = build_threshold_options(root)
    return {
        "version": VERSION,
        "n_candidates_with_impact": len(impacts),
        "impacts": impacts,
        "threshold_options": threshold,
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "INDEPENDENCE_NOT_ESTABLISHED",
        "ok": True,
    }


def longitudinal_priority_score(c: dict[str, Any]) -> tuple[int, int, int, int]:
    """Rank by longitudinal coverage only — never model performance."""
    cov = c.get("coverage") or {}
    return (
        int(cov.get("b_subjects_with_pairs") or 0),
        int(cov.get("b_strict_pairs") or 0),
        int(cov.get("b_subjects") or 0),
        int(cov.get("b_dated_numeric") or 0),
    )
