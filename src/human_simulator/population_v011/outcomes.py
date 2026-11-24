"""Clinical outcome concept registry (raw terms vs grouped concepts)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from human_simulator.population_v011.policy import SOURCE_A, SOURCE_B, VERSION


def _norm_label(s: str) -> str:
    s = (s or "").strip().casefold()
    s = re.sub(r"\s+", " ", s)
    return s


def _cid(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


# Deterministic grouping keys for high-coverage families (hypothesis only)
_FAMILY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cbc_lymphocytes", re.compile(r"лимфоцит|lymphocyte", re.I)),
    ("cbc_monocytes", re.compile(r"моноцит|monocyte", re.I)),
    ("cbc_eosinophils", re.compile(r"эозинофил|eosinophil", re.I)),
    ("cbc_neutrophils", re.compile(r"нейтрофил|neutrophil", re.I)),
    ("cbc_basophils", re.compile(r"базофил|basophil", re.I)),
    ("cbc_platelets", re.compile(r"тромбоцит|platelet", re.I)),
    ("cbc_leukocytes", re.compile(r"лейкоцит|leukocyte|wbc", re.I)),
    ("cbc_erythrocytes", re.compile(r"эритроцит|erythrocyte|rbc", re.I)),
    ("thyroid_t3", re.compile(r"\bт3\b|t3|трийод|triiod", re.I)),
    ("thyroid_t4", re.compile(r"\bт4\b|t4|тироксин|thyrox", re.I)),
    ("thyroid_tsh", re.compile(r"ттг|tsh|тиреотроп", re.I)),
    ("glucose", re.compile(r"глюкоз|glucose|hba1c|гликир", re.I)),
    ("liver_alt", re.compile(r"\bалт\b|alt|алат", re.I)),
    ("liver_ast", re.compile(r"\bаст\b|ast|асат", re.I)),
    ("kidney_creatinine", re.compile(r"креатинин|creatinine", re.I)),
    ("lipid_cholesterol", re.compile(r"холестерин|cholesterol", re.I)),
    ("vitamin_d", re.compile(r"витамин\s*d|vitamin\s*d|25.?oh", re.I)),
]


def build_outcome_registries(conn: Any) -> dict[str, Any]:
    """Build raw terms + concept candidates from canonical components (aggregates)."""
    raw_terms: list[dict[str, Any]] = []
    for sys in (SOURCE_A, SOURCE_B):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT oc.raw_code,
                       COALESCE(oc.raw_unit, '') AS unit,
                       COUNT(*)::bigint AS n_obs,
                       COUNT(*) FILTER (WHERE oc.numeric_value IS NOT NULL)::bigint AS n_num,
                       COUNT(DISTINCT o.subject_id)::bigint AS n_subj
                FROM canonical_evidence.observation_component oc
                JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
                JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
                WHERE s.source_system_id = %s
                  AND oc.raw_code IS NOT NULL AND btrim(oc.raw_code) <> ''
                GROUP BY oc.raw_code, COALESCE(oc.raw_unit, '')
                ORDER BY n_obs DESC
                """,
                (sys,),
            )
            for code, unit, n_obs, n_num, n_subj in cur.fetchall():
                raw_terms.append(
                    {
                        "source_system": sys,
                        "source_code": code,
                        "raw_label": code,
                        "raw_unit": unit,
                        "n_observations": int(n_obs),
                        "n_numeric": int(n_num),
                        "n_subjects": int(n_subj),
                        "term_id": _cid(sys, str(code), str(unit)),
                        "mapping_status": "UNKNOWN",
                    }
                )

    # Group into concept candidates by normalized label + family pattern (HYPOTHESIS)
    concepts: dict[str, dict[str, Any]] = {}
    for term in raw_terms:
        label = _norm_label(str(term["raw_label"]))
        family = None
        for fam, rx in _FAMILY_PATTERNS:
            if rx.search(label):
                family = fam
                break
        key = family or f"raw::{label}::{term['raw_unit']}"
        # Unit mismatch within family → separate concept
        if family:
            key = f"{family}::{term['raw_unit']}"
        if key not in concepts:
            concepts[key] = {
                "concept_candidate_id": _cid("concept", key),
                "normalized_label": family or label,
                "analyte_candidate": family.split("_")[-1] if family else label,
                "specimen_candidate": "UNKNOWN",
                "assay_method_candidate": "UNKNOWN",
                "canonical_unit_candidate": term["raw_unit"],
                "mapping_confidence": (
                    "DETERMINISTIC_NORMALIZATION" if family else "HYPOTHESIS"
                ),
                "domain_review_status": "DOMAIN_REVIEW_REQUIRED",
                "unit_conversion_status": "NOT_PERFORMED",
                "source_terms": [],
                "n_raw_terms": 0,
                "n_observations": 0,
            }
        concepts[key]["source_terms"].append(term["term_id"])
        concepts[key]["n_raw_terms"] += 1
        concepts[key]["n_observations"] += int(term["n_observations"])

    # Cap source_terms listing length in publication (ids only, already opaque)
    concept_list = []
    for c in concepts.values():
        c["source_terms"] = c["source_terms"][:50]
        concept_list.append(c)
    concept_list.sort(key=lambda x: (-x["n_observations"], x["normalized_label"]))

    # Cross-source: only same normalized family + identical unit → HYPOTHESIS not EXACT
    cross = []
    by_fam_unit: dict[str, list[dict[str, Any]]] = {}
    for term in raw_terms:
        label = _norm_label(str(term["raw_label"]))
        family = None
        for fam, rx in _FAMILY_PATTERNS:
            if rx.search(label):
                family = fam
                break
        if not family:
            continue
        k = f"{family}::{term['raw_unit']}"
        by_fam_unit.setdefault(k, []).append(term)
    for k, terms in by_fam_unit.items():
        systems = {t["source_system"] for t in terms}
        if SOURCE_A in systems and SOURCE_B in systems:
            cross.append(
                {
                    "key": k,
                    "mapping_status": "HYPOTHESIS",
                    "domain_review_status": "DOMAIN_REVIEW_REQUIRED",
                    "note": (
                        "Label/family co-occurrence with identical unit is NOT EXACT "
                        "clinical equivalence; analyte/specimen/assay review required."
                    ),
                    "n_terms": len(terms),
                }
            )

    domain_packet = {
        "version": VERSION,
        "families_for_review": [f for f, _ in _FAMILY_PATTERNS],
        "medical_semantics_approved": False,
        "status": "DOMAIN_REVIEW_REQUIRED",
        "note": "Packet for human review only; no programmatic medical approval.",
    }

    return {
        "version": VERSION,
        "raw_measurement_terms": {
            "n": len(raw_terms),
            "n_source_a": sum(1 for t in raw_terms if t["source_system"] == SOURCE_A),
            "n_source_b": sum(1 for t in raw_terms if t["source_system"] == SOURCE_B),
            # store compact top terms only in artifact builder
            "top_terms_by_obs": sorted(
                raw_terms, key=lambda t: -t["n_observations"]
            )[:200],
        },
        "clinical_outcome_concept_candidates": {
            "n": len(concept_list),
            "candidates_top": concept_list[:200],
        },
        "cross_source_concept_candidates": cross,
        "outcome_domain_review_packet": domain_packet,
        "raw_outcome_catalog_status": "PASS",
        "clinical_outcome_concept_registry_status": "PARTIAL",
        "cross_source_outcome_semantics_status": "DOMAIN_REVIEW_REQUIRED",
        "distinction": {
            "many_raw_labels": len(raw_terms),
            "fewer_grouped_clinical_concept_candidates": len(concept_list),
        },
    }
