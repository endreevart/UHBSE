"""Semantic candidate classification — never auto-ACCEPTED."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from human_simulator.cross_source_semantic_review_v01.policy import (
    CANDIDATE_CLASSES,
    VERSION,
)

# Catalog ground truth from Source B analyses_catalog (evidence attachment only)
CATALOG_ANALYTE_BY_CODE: dict[str, str] = {
    "53": "free_t3",
    "55": "free_t4",
    "56": "tsh",
}

A_ANALYTE_HINT: dict[str, str] = {
    "т3св.": "free_t3",
    "т3св": "free_t3",
    "т4св.": "free_t4",
    "т4св": "free_t4",
    "ттг": "tsh",
}


def _norm(s: str) -> str:
    import re

    t = (s or "").lower().replace("ё", "е")
    return re.sub(r"[\s_\-./]+", "", t)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def classify_stratum(stratum: dict[str, Any]) -> dict[str, Any]:
    """Assign machine candidate class. Label+unit match never yields ACCEPTED."""
    a = stratum.get("source_a") or {}
    b = stratum.get("source_b")
    prior = stratum.get("prior_lineage_status") or "UNKNOWN"
    missing: list[str] = []
    conflicts: list[str] = []
    evidence_contract = {
        "analyte_concept": False,
        "specimen_material": False,
        "method_assay_compatibility": False,
        "unit_identity_or_approved_conversion": False,
        "numeric_semantics": False,
        "temporal_semantics": False,
        "provenance_isolation": True,  # sources remain separate by construction
        "domain_review_decision": False,
    }

    if not b or not stratum.get("has_b_candidate"):
        return {
            "mapping_id": stratum["mapping_id"],
            "candidate_class": "INSUFFICIENT_EVIDENCE",
            "prior_lineage_status": prior,
            "typed_decision": None,
            "auto_accepted": False,
            "label_unit_match_insufficient": True,
            "missing_evidence": ["no_b_candidate"],
            "conflicts": [],
            "evidence_contract": evidence_contract,
            "blocks_unrestricted_accepted": True,
            "blocks_accepted": True,
            "reason_codes": ["NO_B_CANDIDATE"],
        }

    a_outcome = str(a.get("outcome") or "")
    a_unit = str(a.get("unit") or "").strip()
    b_code = str(b.get("raw_code") or "")
    b_unit = str(b.get("unit") or "").strip()
    cat = b.get("catalog") or {}

    a_hint = A_ANALYTE_HINT.get(_norm(a_outcome))
    b_analyte = CATALOG_ANALYTE_BY_CODE.get(b_code)
    if a_hint and b_analyte and a_hint == b_analyte:
        evidence_contract["analyte_concept"] = True
    elif a_hint and b_analyte and a_hint != b_analyte:
        conflicts.append("analyte_catalog_mismatch")
    elif not a_hint or not b_analyte:
        missing.append("analyte_concept_unconfirmed")

    specimen_a = a.get("specimen_material")
    specimen_b = b.get("specimen_material") or cat.get("material")
    specimen_a_empty = a.get("specimen_material_empty", True) or not specimen_a
    specimen_b_empty = b.get("specimen_material_empty", True) or not (
        specimen_b and str(specimen_b).strip()
    )
    if specimen_a_empty or specimen_b_empty:
        missing.append("specimen_material")
    elif str(specimen_a).strip() != str(specimen_b).strip():
        conflicts.append("specimen_conflict")
    else:
        evidence_contract["specimen_material"] = True

    assay_a = a.get("method_assay")
    assay_b = b.get("method_assay") or cat.get("method_assay")
    assay_a_empty = a.get("method_assay_empty", True) or not assay_a
    assay_b_empty = b.get("method_assay_empty", True) or not (assay_b and str(assay_b).strip())
    if assay_a_empty or assay_b_empty:
        missing.append("method_assay")
    elif str(assay_a).strip() != str(assay_b).strip():
        conflicts.append("assay_conflict")
    else:
        evidence_contract["method_assay_compatibility"] = True

    unit_exact = bool(a_unit) and a_unit == b_unit
    approved_conversion = bool(stratum.get("approved_unit_conversion_contract"))
    if unit_exact or approved_conversion:
        evidence_contract["unit_identity_or_approved_conversion"] = True
    else:
        conflicts.append("unit_conflict")

    n_num = int(b.get("n_numeric") or 0)
    n_non = int(b.get("n_non_numeric_with_text") or 0)
    if n_num <= 0 and n_non > 0:
        conflicts.append("numeric_semantics_non_numeric_only")
    elif n_num > 0:
        evidence_contract["numeric_semantics"] = True
    else:
        missing.append("numeric_values")

    if int(b.get("n_dated_numeric") or 0) > 0:
        evidence_contract["temporal_semantics"] = True
    else:
        missing.append("dated_numeric_values")

    # Priority of classes
    if "analyte_catalog_mismatch" in conflicts:
        klass = "ANALYTE_AMBIGUOUS"
    elif "unit_conflict" in conflicts:
        klass = "UNIT_CONFLICT"
    elif "specimen_conflict" in conflicts:
        klass = "SPECIMEN_CONFLICT"
    elif "assay_conflict" in conflicts:
        klass = "ASSAY_CONFLICT"
    elif "numeric_semantics_non_numeric_only" in conflicts:
        klass = "NUMERIC_SEMANTICS_CONFLICT"
    elif "specimen_material" in missing:
        klass = "SPECIMEN_MISSING"
    elif "method_assay" in missing:
        # Specimen may also be missing; SPECIMEN_MISSING takes precedence above.
        # If specimen somehow present but assay missing:
        klass = "ASSAY_MISSING"
    elif missing or not evidence_contract["analyte_concept"]:
        klass = "INSUFFICIENT_EVIDENCE"
    else:
        # All hard fields present → still only a candidate for human review
        klass = "SEMANTICALLY_ALIGNED_CANDIDATE"

    # Empty never equals empty for specimen/assay
    if specimen_a_empty and specimen_b_empty:
        # already SPECIMEN_MISSING
        pass

    label_unit_ok = unit_exact and bool(a_hint and b_analyte and a_hint == b_analyte)
    blocks_accepted = True  # machine never accepts
    blocks_unrestricted = (
        "specimen_material" in missing
        or "method_assay" in missing
        or bool(conflicts)
        or klass != "SEMANTICALLY_ALIGNED_CANDIDATE"
    )

    assert klass in CANDIDATE_CLASSES
    return {
        "mapping_id": stratum["mapping_id"],
        "candidate_class": klass,
        "prior_lineage_status": prior,
        "typed_decision": None,
        "auto_accepted": False,
        "label_unit_match": label_unit_ok,
        "label_unit_match_insufficient": True,  # always insufficient alone
        "missing_evidence": missing,
        "conflicts": conflicts,
        "evidence_contract": evidence_contract,
        "blocks_unrestricted_accepted": blocks_unrestricted,
        "blocks_accepted": blocks_accepted,
        "a_outcome": a_outcome,
        "a_unit": a_unit,
        "b_raw_code": b_code,
        "b_unit": b_unit,
        "b_catalog_name_ru": cat.get("name_ru"),
        "a_analyte_hint": a_hint,
        "b_catalog_analyte": b_analyte,
        "coverage": {
            "b_subjects": int(b.get("n_subjects") or 0),
            "b_subjects_with_pairs": int(b.get("n_subjects_with_pairs") or 0),
            "b_strict_pairs": int(b.get("n_strict_consecutive_pairs") or 0),
            "b_dated_numeric": int(b.get("n_dated_numeric") or 0),
        },
        "classification_hash": _hash(
            {
                "id": stratum["mapping_id"],
                "klass": klass,
                "missing": missing,
                "conflicts": conflicts,
            }
        ),
        "reason_codes": [klass] + missing + conflicts,
    }


def classify_universe(strata: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [classify_stratum(s) for s in strata]
    counts = Counter(r["candidate_class"] for r in rows)
    return {
        "version": VERSION,
        "CROSS_SOURCE_SEMANTIC_REVIEW_STATUS": "PASS",
        "n_classified": len(rows),
        "candidate_class_counts": dict(counts),
        "n_auto_accepted": 0,
        "auto_accepted_forbidden": True,
        "classifications": rows,
        "ok": True,
    }


def label_unit_cannot_accept(
    *,
    a_label: str,
    a_unit: str,
    b_code: str,
    b_unit: str,
    specimen: str | None = None,
    assay: str | None = None,
) -> dict[str, Any]:
    """Contract helper: label+unit alone never ACCEPTED."""
    stratum = {
        "mapping_id": _hash({"a": a_label, "u": a_unit, "b": b_code, "bu": b_unit}),
        "has_b_candidate": True,
        "prior_lineage_status": "HYPOTHESIS",
        "source_a": {
            "outcome": a_label,
            "unit": a_unit,
            "specimen_material": specimen,
            "specimen_material_empty": not specimen,
            "method_assay": assay,
            "method_assay_empty": not assay,
        },
        "source_b": {
            "raw_code": b_code,
            "unit": b_unit,
            "specimen_material": specimen,
            "specimen_material_empty": not specimen,
            "method_assay": assay,
            "method_assay_empty": not assay,
            "n_numeric": 10,
            "n_non_numeric_with_text": 0,
            "n_dated_numeric": 10,
            "catalog": {"name_ru": None, "material": specimen, "method_assay": assay},
        },
    }
    out = classify_stratum(stratum)
    return {
        "accepted": False,
        "candidate_class": out["candidate_class"],
        "label_unit_match_insufficient": out["label_unit_match_insufficient"],
        "blocks_accepted": out["blocks_accepted"],
    }
