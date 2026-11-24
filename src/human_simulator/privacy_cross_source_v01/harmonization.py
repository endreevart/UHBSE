"""Cross-source outcome harmonization — honest mapping statuses only."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from human_simulator.privacy_cross_source_v01.policy import (
    ACCEPTED_GS011_ARTIFACT_DIR,
    ACCEPTED_MAPPING_STATUSES,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _norm_label(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"[\s_\-./]+", "", t)
    return t


# Conservative synonym table: A label → B catalog code candidates (NOT automatic EXACT)
# Evidence must still satisfy unit + specimen/method gates.
_KNOWN_CANDIDATES: dict[str, list[dict[str, Any]]] = {
    "т3св.": [{"raw_code": "53", "evidence": "prior_unified_t3_stratum", "analyte_hint": "free_t3"}],
    "т3св": [{"raw_code": "53", "evidence": "prior_unified_t3_stratum", "analyte_hint": "free_t3"}],
    "т4св.": [{"raw_code": "54", "evidence": "catalog_code_hypothesis", "analyte_hint": "free_t4"}],
    "ттг": [
        {"raw_code": "55", "evidence": "catalog_code_hypothesis", "analyte_hint": "tsh"},
        {"raw_code": "1", "evidence": "catalog_code_hypothesis", "analyte_hint": "tsh"},
    ],
}


def load_source_a_providers(root: Path) -> list[dict[str, Any]]:
    reg = json.loads(
        (
            Path(root) / ACCEPTED_GS011_ARTIFACT_DIR / "global-provider-registry.json"
        ).read_text(encoding="utf-8")
    )
    return list(reg.get("providers") or [])


def load_prior_t3_matrix(root: Path) -> dict[str, Any] | None:
    p = (
        Path(root)
        / "artifacts/stage-03-unified-source-expansion-v0.1.2.1.1"
        / "t3-semantic-comparison-matrix.json"
    )
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def evaluate_mapping(
    *,
    a_outcome: str,
    a_unit: str,
    b_raw_code: str | None,
    b_unit: str | None,
    b_analyte_name: str | None,
    b_specimen: str | None,
    b_method: str | None,
    b_n_subjects: int,
    b_n_numeric: int,
    prior_t3_status: str | None,
    verified_unit_transform: bool = False,
) -> dict[str, Any]:
    """Never accept on name similarity alone; specimen/method empty ⇒ not EXACT."""
    unit_a = (a_unit or "").strip()
    unit_b = (b_unit or "").strip()
    specimen = (b_specimen or "").strip()
    method = (b_method or "").strip()
    failed: list[str] = []

    if not b_raw_code:
        return {
            "mapping_status": "UNKNOWN",
            "failed_checks": ["no_b_candidate_code"],
            "domain_review_status": "DOMAIN_REVIEW_REQUIRED",
            "accepted_for_transfer": False,
        }

    unit_exact = unit_a == unit_b and bool(unit_a)
    if not unit_exact and not verified_unit_transform:
        failed.append("unit_not_exact_and_no_verified_transform")
    if not specimen:
        failed.append("specimen_material_empty")
    # method optional but recorded
    method_empty = not method
    if method_empty:
        failed.append("method_assay_empty")

    # Name-only is insufficient
    name_only = True  # we never have independent clinical confirmation in this release
    if name_only and not (unit_exact and specimen):
        # Prefer prior T3 evidence if present
        if prior_t3_status == "DOMAIN_REVIEW_REQUIRED" and b_raw_code == "53":
            status = "HYPOTHESIS"
            domain = "DOMAIN_REVIEW_REQUIRED"
        elif prior_t3_status == "OUTCOME_COMPARABLE" and unit_exact and specimen:
            status = "EXACT"
            domain = "ACCEPTED"
        else:
            status = "HYPOTHESIS" if b_raw_code else "UNKNOWN"
            domain = "DOMAIN_REVIEW_REQUIRED"
    elif unit_exact and specimen and verified_unit_transform is False:
        # Still need domain review for cross-clinic method equivalence
        status = "HYPOTHESIS"
        domain = "DOMAIN_REVIEW_REQUIRED"
        failed.append("cross_clinic_method_equivalence_unverified")
    elif verified_unit_transform and specimen:
        status = "SUPPORTED_TRANSFORM"
        domain = "DOMAIN_REVIEW_REQUIRED"
    else:
        status = "NOT_COMPARABLE"
        domain = "REJECTED"

    # Hard rule: empty specimen ⇒ never EXACT / SUPPORTED_TRANSFORM acceptance
    if not specimen and status in ACCEPTED_MAPPING_STATUSES:
        status = "HYPOTHESIS"
        domain = "DOMAIN_REVIEW_REQUIRED"
        failed.append("blocked_acceptance_without_specimen")

    accepted = status in ACCEPTED_MAPPING_STATUSES and domain == "ACCEPTED"
    return {
        "mapping_status": status,
        "failed_checks": failed,
        "domain_review_status": domain,
        "accepted_for_transfer": accepted,
        "unit_exact": unit_exact,
        "specimen_present": bool(specimen),
        "method_present": bool(method),
        "verified_unit_transform": verified_unit_transform,
        "b_n_subjects": b_n_subjects,
        "b_n_numeric": b_n_numeric,
        "a_analyte": a_outcome,
        "a_unit": a_unit,
        "b_raw_code": b_raw_code,
        "b_unit": unit_b,
        "b_analyte_name": (b_analyte_name or "")[:120] or None,
        "name_similarity_alone_insufficient": True,
        "test_performance_not_used_for_mapping": True,
    }


def build_harmonization(
    *,
    root: Path,
    b_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    providers = load_source_a_providers(root)
    prior_t3 = load_prior_t3_matrix(root)
    prior_status = (prior_t3 or {}).get("t3_semantic_harmonization_status")
    preferred = (prior_t3 or {}).get("preferred_stratum") or {}

    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in b_catalog:
        by_code.setdefault(str(row["raw_code"]), []).append(row)

    mappings: list[dict[str, Any]] = []
    for p in providers:
        outcome = str(p.get("outcome") or "")
        unit = str(p.get("unit") or "")
        key = _norm_label(outcome)
        candidates = _KNOWN_CANDIDATES.get(key) or []
        if not candidates:
            mappings.append(
                {
                    "source_a": {
                        "system": SOURCE_A_SYSTEM_ID,
                        "outcome": outcome,
                        "unit": unit,
                        "grain_id": p.get("grain_id"),
                        "active_provider": p.get("active_provider"),
                    },
                    "source_b": None,
                    "mapping_status": "UNKNOWN",
                    "domain_review_status": "DOMAIN_REVIEW_REQUIRED",
                    "accepted_for_transfer": False,
                    "evidence_hash": _hash({"a": outcome, "u": unit, "status": "UNKNOWN"}),
                    "failed_checks": ["no_catalog_candidate_without_name_guess"],
                    "note": "No mapping invented from label similarity alone.",
                }
            )
            continue

        for cand in candidates:
            code = cand["raw_code"]
            b_rows = by_code.get(code) or []
            # Prefer exact unit match among B strata
            b_row = next((r for r in b_rows if str(r.get("unit") or "") == unit), None)
            if b_row is None and b_rows:
                b_row = max(b_rows, key=lambda r: int(r.get("n_subjects") or 0))
            specimen = None
            analyte = None
            if code == "53" and preferred:
                specimen = preferred.get("specimen_material")
                analyte = preferred.get("analyte_name")
            ev = evaluate_mapping(
                a_outcome=outcome,
                a_unit=unit,
                b_raw_code=code if b_row or code == "53" else None,
                b_unit=(b_row or {}).get("unit") if b_row else (preferred.get("raw_unit") if code == "53" else None),
                b_analyte_name=analyte,
                b_specimen=specimen,
                b_method=None,
                b_n_subjects=int((b_row or {}).get("n_subjects") or preferred.get("n_subjects") or 0),
                b_n_numeric=int((b_row or {}).get("n_numeric") or preferred.get("n_numeric") or 0),
                prior_t3_status=prior_status if code == "53" else None,
            )
            doc = {
                "source_a": {
                    "system": SOURCE_A_SYSTEM_ID,
                    "outcome": outcome,
                    "unit": unit,
                    "grain_id": p.get("grain_id"),
                    "active_provider": p.get("active_provider"),
                    "model_identity_hash": p.get("model_identity_hash"),
                },
                "source_b": {
                    "system": SOURCE_B_SYSTEM_ID,
                    "raw_code": code,
                    "unit": ev.get("b_unit"),
                    "analyte_name": ev.get("b_analyte_name"),
                    "specimen_material": specimen,
                    "method_assay": None,
                    "n_subjects": ev.get("b_n_subjects"),
                    "n_numeric": ev.get("b_n_numeric"),
                },
                **{k: v for k, v in ev.items() if k not in {"b_n_subjects", "b_n_numeric", "b_analyte_name", "b_unit", "b_raw_code"}},
                "candidate_evidence": cand.get("evidence"),
                "evidence_hash": _hash(
                    {
                        "a": outcome,
                        "au": unit,
                        "b": code,
                        "bu": ev.get("b_unit"),
                        "status": ev.get("mapping_status"),
                        "failed": ev.get("failed_checks"),
                    }
                ),
            }
            mappings.append(doc)

    accepted = [m for m in mappings if m.get("accepted_for_transfer")]
    status_counts: dict[str, int] = {}
    for m in mappings:
        st = str(m.get("mapping_status"))
        status_counts[st] = status_counts.get(st, 0) + 1

    # Overall harmonization status
    if accepted:
        harm_status = "PASS"
    elif any(m.get("mapping_status") == "HYPOTHESIS" for m in mappings):
        harm_status = "PARTIAL_NO_ACCEPTED"
    else:
        harm_status = "INSUFFICIENT_NO_ACCEPTED"

    return {
        "version": VERSION,
        "CROSS_SOURCE_OUTCOME_HARMONIZATION_STATUS": harm_status,
        "ACCEPTED_COMPARABLE_OUTCOME_COUNT": len(accepted),
        "n_source_a_providers_considered": len(providers),
        "n_mapping_rows": len(mappings),
        "mapping_status_counts": status_counts,
        "accepted_mappings": accepted,
        "mappings_public": [
            {
                "a_outcome": m["source_a"]["outcome"],
                "a_unit": m["source_a"]["unit"],
                "b_raw_code": (m.get("source_b") or {}).get("raw_code"),
                "b_unit": (m.get("source_b") or {}).get("unit"),
                "mapping_status": m.get("mapping_status"),
                "domain_review_status": m.get("domain_review_status"),
                "accepted_for_transfer": m.get("accepted_for_transfer"),
                "failed_checks": m.get("failed_checks"),
                "evidence_hash": m.get("evidence_hash"),
                "specimen_present": m.get("specimen_present"),
                "unit_exact": m.get("unit_exact"),
            }
            for m in mappings
            if m.get("source_b") is not None or m.get("mapping_status") != "UNKNOWN"
        ],
        "unknown_without_candidate_count": sum(
            1 for m in mappings if m.get("mapping_status") == "UNKNOWN"
        ),
        "prior_t3_status_carried": prior_status,
        "forbidden": {
            "name_only_exact": False,
            "unverified_unit_conversion": False,
            "hypothesis_treated_as_accepted": False,
            "mapping_by_test_performance": False,
        },
        "missing_evidence_for_acceptance": [
            "specimen_material_for_candidate_strata",
            "method_assay_equivalence_A_vs_B",
            "domain_review_signoff",
        ],
        "ok_for_zero_shot": len(accepted) > 0,
        "harmonization_hash": _hash(
            {
                "accepted": len(accepted),
                "counts": status_counts,
                "n": len(mappings),
            }
        ),
    }
