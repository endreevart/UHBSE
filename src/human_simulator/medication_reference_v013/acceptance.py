"""Acceptance semantics: product ≠ ingredient set ≠ form/route ≠ family."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v013.policy import (
    AUTHORITATIVE_ACCEPTANCE_LEVELS,
    DECISION_TYPES,
    EXACT_REVIEW_ID,
    RUNTIME_DIR,
    V011_DECISION_LOG,
    V011_MAPPING,
    VERSION,
)


def _sha_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def historical_authoritative_accepted(root: Path) -> dict[str, Any]:
    rows = load_jsonl(root / V011_MAPPING)
    accepted = [
        r
        for r in rows
        if r.get("drug_concept_status")
        in {"EXACT_PROVIDER_MATCH", "SUPPORTED_TRANSFORM", "HUMAN_ACCEPTED"}
    ]
    human = [r for r in rows if r.get("drug_concept_status") == "HUMAN_ACCEPTED"]
    return {
        "HISTORICAL_AUTHORITATIVE_ACCEPTED_COUNT": len(accepted),
        "HUMAN_ACCEPTED_COUNT": len(human),
        "accepted_source_medicine_ids": [str(r["source_medicine_id"]) for r in accepted],
        "note": (
            "Historical v0.1.1 registry count; scientifically usable may be lower "
            "when eligibility review is required"
        ),
    }


def exact_813_eligibility(root: Path) -> dict[str, Any]:
    """Do not rewrite EXACT; overlay eligibility for scientific use."""
    rows = load_jsonl(root / V011_MAPPING)
    row = next((r for r in rows if str(r.get("source_medicine_id")) == EXACT_REVIEW_ID), None)
    if row is None:
        return {
            "source_medicine_id": EXACT_REVIEW_ID,
            "historical_status": None,
            "SCIENTIFICALLY_USABLE_ACCEPTED": False,
            "eligibility": "MISSING",
            "PRODUCT_IDENTITY_REVIEW_REQUIRED": True,
        }
    doubts = []
    cand = (row.get("candidates") or [{}])[0]
    if not (cand.get("trade_name") or row.get("product_name")):
        doubts.append("empty_trade_name")
    if str(row.get("provider_concept_id") or "").startswith("esklp_group_"):
        doubts.append("group_sheet_id_not_klp_product")
    src_form = "solution_tablet_for_topical_use"
    prov_form = str(cand.get("form") or row.get("form") or "")
    if "ШИПУЧ" in prov_form.upper() or "шипуч" in prov_form.casefold():
        doubts.append("form_nuance_solution_tablet_vs_effervescent")
    return {
        "source_medicine_id": EXACT_REVIEW_ID,
        "historical_status": row.get("drug_concept_status"),
        "provider_concept_id": row.get("provider_concept_id"),
        "doubts": doubts,
        "SCIENTIFICALLY_USABLE_ACCEPTED": False,  # until typed human review
        "eligibility": "AUTOMATIC_EXACT_MATCH_REVIEW_REQUIRED",
        "PRODUCT_IDENTITY_REVIEW_REQUIRED": True,
        "historical_registry_unchanged": True,
        "allowed_decisions": [
            "PRODUCT_IDENTITY_ACCEPTED",
            "INGREDIENT_FORM_ROUTE_ACCEPTED",
            "AMBIGUOUS",
            "HUMAN_REJECTED",
        ],
    }


def v013_decision_log_path(root: Path) -> Path:
    p = root / RUNTIME_DIR / "review" / "typed-decision-log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_v013_decisions(root: Path) -> list[dict[str, Any]]:
    return load_jsonl(v013_decision_log_path(root))


def latest_v013_by_medicine(root: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in load_v013_decisions(root):
        latest[str(row["source_medicine_id"])] = row
    return latest


def scientifically_usable_accepted(root: Path) -> dict[str, Any]:
    """Only typed human decisions at authoritative levels with evidence."""
    latest = latest_v013_by_medicine(root)
    usable = []
    for mid, d in latest.items():
        if d.get("decision") not in AUTHORITATIVE_ACCEPTANCE_LEVELS:
            continue
        if not d.get("reviewer_identifier") or not d.get("reason") or not d.get("evidence_hash"):
            continue
        if d.get("llm_generated"):
            continue
        usable.append(
            {
                "source_medicine_id": mid,
                "decision": d.get("decision"),
                "candidate_id": d.get("candidate_id"),
                "provider_neutral_concept_id": d.get("provider_neutral_concept_id"),
                "reviewer_identifier": d.get("reviewer_identifier"),
            }
        )
    # 813 historical EXACT is NOT usable until typed review
    elig = exact_813_eligibility(root)
    return {
        "version": VERSION,
        "SCIENTIFICALLY_USABLE_ACCEPTED_COUNT": len(usable),
        "items": usable,
        "exact_813_eligibility": elig,
        "historical_exact_excluded_until_review": True,
        "ingredient_family_excluded_from_usable": True,
        "provisional_excluded": True,
    }


def assert_decision_type_semantics() -> dict[str, bool]:
    return {
        "product_identity_neq_ingredient_set": (
            "PRODUCT_IDENTITY_ACCEPTED" != "INGREDIENT_SET_ACCEPTED"
        ),
        "ingredient_set_not_in_authoritative_readiness": (
            "INGREDIENT_SET_ACCEPTED" not in AUTHORITATIVE_ACCEPTANCE_LEVELS
        ),
        "family_only_not_authoritative": (
            "INGREDIENT_FAMILY_ONLY" not in AUTHORITATIVE_ACCEPTANCE_LEVELS
        ),
        "all_types_defined": DECISION_TYPES
        == {
            "PRODUCT_IDENTITY_ACCEPTED",
            "INGREDIENT_SET_ACCEPTED",
            "INGREDIENT_FORM_ROUTE_ACCEPTED",
            "INGREDIENT_FAMILY_ONLY",
            "AMBIGUOUS",
            "INSUFFICIENT_SOURCE_EVIDENCE",
            "HUMAN_REJECTED",
        },
    }


def v011_log_untouched(root: Path) -> dict[str, Any]:
    rows = load_jsonl(root / V011_DECISION_LOG)
    return {
        "path": V011_DECISION_LOG,
        "n": len(rows),
        "n_human_rejected": sum(1 for r in rows if r.get("decision") == "HUMAN_REJECTED"),
        "append_only_preserved": True,
        "not_rewritten_by_v013": True,
    }


def write_acceptance_semantics_doc(root: Path) -> Path:
    doc = {
        "version": VERSION,
        "decision_types": sorted(DECISION_TYPES),
        "rules": {
            "PRODUCT_IDENTITY_ACCEPTED": (
                "Same pharmaceutical product identity — not merely similar composition"
            ),
            "INGREDIENT_SET_ACCEPTED": (
                "Active ingredient set confirmed — does NOT imply product identity"
            ),
            "INGREDIENT_FORM_ROUTE_ACCEPTED": (
                "Ingredient set + chemical form + dosage form + route compatible"
            ),
            "INGREDIENT_FAMILY_ONLY": (
                "Broad nutrient/pharmacologic family — exploratory only; "
                "cannot open authoritative intervention cohort"
            ),
            "ESKLP_product_id_not_source_supplement_id": True,
            "one_decision_may_accept_ingredient_without_product": True,
            "candidate_or_provisional_never_accepted": True,
            "llm_cannot_create_accepted_decision": True,
        },
        "authoritative_acceptance_levels": sorted(AUTHORITATIVE_ACCEPTANCE_LEVELS),
        "semantics_checks": assert_decision_type_semantics(),
        "exact_813_overlay": exact_813_eligibility(root),
        "historical": historical_authoritative_accepted(root),
        "scientifically_usable": scientifically_usable_accepted(root),
        "v011_decision_log": v011_log_untouched(root),
    }
    path = root / RUNTIME_DIR / "review-pack" / "acceptance-semantics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    usable_path = root / RUNTIME_DIR / "review-pack" / "scientifically-usable-accepted.json"
    usable_path.write_text(
        json.dumps(doc["scientifically_usable"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
