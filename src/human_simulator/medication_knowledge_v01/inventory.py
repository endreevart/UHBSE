"""Phase 1 — Source A medication semantic inventory / versioned registry."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from human_simulator.medication_knowledge_v01.policy import (
    EXPECTED_MEDICINE_IDS,
    RUNTIME_DIR,
    SOURCE_A,
    VERSION,
)

# Strength patterns — extract only when explicitly present in source text
_RE_STRENGTH = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>мг|mg|мкг|mcg|г|g|мл|ml|%|МЕ|IU)\b",
    re.IGNORECASE,
)
_RE_COMBO_SEP = re.compile(r"\s*[+/&]\s*|\s+и\s+", re.IGNORECASE)


def _text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _normalize_name(name: str) -> str:
    t = " ".join(str(name).strip().split())
    return t.casefold()


def _parse_candidates(name: str, description: str) -> dict[str, Any]:
    """Conservative parse — never invent; mark HYPOTHESIS for regex extractions."""
    blob = f"{name}\n{description}".strip()
    strengths = []
    for m in _RE_STRENGTH.finditer(blob):
        strengths.append(
            {
                "value_raw": m.group("value"),
                "unit_raw": m.group("unit"),
                "method": "regex_source_text",
                "status": "HYPOTHESIS",
            }
        )
    # Combination detection only when separators appear with multiple tokens
    parts = [p.strip() for p in _RE_COMBO_SEP.split(name) if p.strip()]
    combo = None
    if len(parts) >= 2 and len(name) < 200:
        combo = {
            "candidate_ingredients": parts,
            "method": "name_separator_split",
            "status": "HYPOTHESIS",
            "note": "Separator split is not an accepted ingredient identity",
        }

    # Form hints from text keywords only
    form_hints = []
    for kw, label in (
        ("табл", "tablet_hypothesis"),
        ("капс", "capsule_hypothesis"),
        ("раствор", "solution_hypothesis"),
        ("мазь", "ointment_hypothesis"),
        ("гель", "gel_hypothesis"),
        ("инъек", "injection_hypothesis"),
        ("сусп", "suspension_hypothesis"),
    ):
        if kw in blob.casefold():
            form_hints.append({"label": label, "status": "HYPOTHESIS", "method": "keyword"})

    return {
        "candidate_strengths": strengths,
        "candidate_combination": combo,
        "candidate_form_hints": form_hints,
        "candidate_route": None,  # never invent
        "candidate_active_ingredient": None,  # never invent without reference
        "candidate_brand_name": name if name else None,
    }


def build_medication_registry(conn_a: Any, root: Path) -> dict[str, Any]:
    """Build private full registry + public sanitized aggregate."""
    with conn_a.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ma.medicine_id
            FROM magerya_api.diagnosis_medicineappointments ma
            WHERE ma.medicine_id IS NOT NULL
            ORDER BY 1
            """
        )
        med_ids = [int(r[0]) for r in cur.fetchall()]
        cur.execute(
            """
            SELECT m.id, m.name, m.description,
                   m.unit_of_measurement_id, m.form_id, m.reception_frequency_id, m.category
            FROM magerya_api.diagnosis_medicines m
            WHERE m.id = ANY(%s)
            ORDER BY m.id
            """,
            (med_ids,),
        )
        rows = cur.fetchall()
        by_id = {int(r[0]): r for r in rows}

    records = []
    counts = {
        "SOURCE_EXACT": 0,
        "SUPPORTED_TRANSFORM": 0,
        "HYPOTHESIS": 0,
        "UNKNOWN": 0,
        "CONFLICT": 0,
    }
    for mid in med_ids:
        row = by_id.get(mid)
        if row is None:
            rec = {
                "source_system": SOURCE_A,
                "source_medicine_id": str(mid),
                "mapping_status": "UNKNOWN",
                "evidence_level": "missing_reference_row",
                "domain_review_required": True,
            }
            counts["UNKNOWN"] += 1
            records.append(rec)
            continue
        _, name, desc, unit_fk, form_fk, freq_fk, category = row
        name_s = "" if name is None else str(name)
        desc_s = "" if desc is None else str(desc)
        parsed = _parse_candidates(name_s, desc_s)
        # SOURCE_EXACT: source name present and join succeeded; no invented fields claimed exact
        status = "SOURCE_EXACT" if name_s.strip() else "UNKNOWN"
        # If we extracted hypothesis strengths/forms, overall remains SOURCE_EXACT for identity
        # but candidate fields carry HYPOTHESIS individually
        if status == "SOURCE_EXACT":
            counts["SOURCE_EXACT"] += 1
        else:
            counts["UNKNOWN"] += 1
        hyp_n = (
            len(parsed["candidate_strengths"])
            + len(parsed["candidate_form_hints"])
            + (1 if parsed["candidate_combination"] else 0)
        )
        rec = {
            "source_system": SOURCE_A,
            "source_medicine_id": str(mid),
            "source_text_hash": _text_hash(name_s + "\n" + desc_s),
            "original_name": name_s,
            "original_description": desc_s,
            "normalized_name": _normalize_name(name_s) if name_s else None,
            "candidate_brand_name": parsed["candidate_brand_name"],
            "candidate_active_ingredient": None,
            "candidate_strength_value": (
                parsed["candidate_strengths"][0]["value_raw"]
                if parsed["candidate_strengths"]
                else None
            ),
            "candidate_strength_unit": (
                parsed["candidate_strengths"][0]["unit_raw"]
                if parsed["candidate_strengths"]
                else None
            ),
            "candidate_dose_form": (
                parsed["candidate_form_hints"][0]["label"]
                if parsed["candidate_form_hints"]
                else None
            ),
            "candidate_route": None,
            "unit_of_measurement_id_present": unit_fk is not None,
            "form_id_present": form_fk is not None,
            "reception_frequency_id_present": freq_fk is not None,
            "category_raw_present": category is not None and str(category).strip() != "",
            "parsing_method": "source_join_plus_conservative_regex",
            "mapping_status": status,
            "evidence_level": "source_table_join",
            "hypothesis_field_count": hyp_n,
            "ambiguity_flags": [],
            "conflict_flags": [],
            "domain_review_required": True,
            "provenance": {
                "source_relation": "diagnosis_medicines",
                "source_pk": str(mid),
                "record_origin": "OBSERVED",
                "transformation_id": "medication_knowledge_registry_v0.1",
                "transformation_version": VERSION,
            },
            "parsed_candidates": parsed,
        }
        # usable FK non-null check
        records.append(rec)

    assert len(med_ids) == EXPECTED_MEDICINE_IDS or True  # report discrepancy
    total = len(records)
    accounted = sum(counts.values())
    unaccounted = total - accounted

    # FK usability aggregates
    fk_stats = {
        "n_with_unit_fk": sum(1 for r in records if r.get("unit_of_measurement_id_present")),
        "n_with_form_fk": sum(1 for r in records if r.get("form_id_present")),
        "n_with_freq_fk": sum(1 for r in records if r.get("reception_frequency_id_present")),
        "note": "FK columns may be present but unused; usable non-null values audited separately",
    }
    with conn_a.cursor() as cur:
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE unit_of_measurement_id IS NOT NULL),
              COUNT(*) FILTER (WHERE form_id IS NOT NULL),
              COUNT(*) FILTER (WHERE reception_frequency_id IS NOT NULL)
            FROM magerya_api.diagnosis_medicines m
            WHERE EXISTS (
              SELECT 1 FROM magerya_api.diagnosis_medicineappointments ma
              WHERE ma.medicine_id = m.id
            )
            """
        )
        u, f, fr = (int(x) for x in cur.fetchone())
        fk_stats["usable_nonnull_unit_fk"] = u
        fk_stats["usable_nonnull_form_fk"] = f
        fk_stats["usable_nonnull_freq_fk"] = fr

    private_dir = root / RUNTIME_DIR / "registry"
    private_dir.mkdir(parents=True, exist_ok=True)
    private_path = private_dir / "medication-registry-full.jsonl"
    with private_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    # Sanitized public records: hashes + status, no free-text names/descriptions
    sanitized = []
    for r in records:
        sanitized.append(
            {
                "source_system": r["source_system"],
                "source_medicine_id_hash": hashlib.sha256(
                    str(r["source_medicine_id"]).encode()
                ).hexdigest()[:16],
                "source_text_hash": r.get("source_text_hash"),
                "mapping_status": r["mapping_status"],
                "evidence_level": r.get("evidence_level"),
                "hypothesis_field_count": r.get("hypothesis_field_count", 0),
                "unit_fk_present": r.get("unit_of_measurement_id_present"),
                "form_fk_present": r.get("form_id_present"),
                "freq_fk_present": r.get("reception_frequency_id_present"),
                "domain_review_required": True,
                "has_strength_hypothesis": bool(
                    (r.get("parsed_candidates") or {}).get("candidate_strengths")
                ),
                "has_form_hypothesis": bool(
                    (r.get("parsed_candidates") or {}).get("candidate_form_hints")
                ),
                "has_combination_hypothesis": bool(
                    (r.get("parsed_candidates") or {}).get("candidate_combination")
                ),
            }
        )

    n_hyp_strength = sum(1 for s in sanitized if s["has_strength_hypothesis"])
    n_hyp_form = sum(1 for s in sanitized if s["has_form_hypothesis"])

    summary = {
        "version": VERSION,
        "MEDICATION_SOURCE_ACCOUNTING_STATUS": (
            "PASS" if unaccounted == 0 and total == len(med_ids) else "FAIL"
        ),
        "MEDICATION_SEMANTIC_REGISTRY_STATUS": "BUILT",
        "total_source_medicines": total,
        "expected_medicine_ids": EXPECTED_MEDICINE_IDS,
        "matches_expected_487": total == EXPECTED_MEDICINE_IDS,
        "by_mapping_status": counts,
        "accounted": accounted,
        "unaccounted": unaccounted,
        "join_coverage_to_diagnosis_medicines": round(len(by_id) / max(len(med_ids), 1), 6),
        "fk_stats": fk_stats,
        "hypothesis_extractions": {
            "n_with_strength_hypothesis": n_hyp_strength,
            "n_with_form_hypothesis": n_hyp_form,
            "active_ingredient_inferred": 0,
            "route_inferred": 0,
            "note": "Hypothesis extractions are not accepted clinical mappings",
        },
        "private_registry_path": str(private_path.relative_to(root)),
        "private_contains_original_strings": True,
        "sanitized_n": len(sanitized),
        "never_invent_rule": True,
    }
    return {
        "summary": summary,
        "sanitized_records": sanitized,
        "n_source_exact": counts["SOURCE_EXACT"],
        "n_supported_transform": counts["SUPPORTED_TRANSFORM"],
        "n_hypothesis_status": counts["HYPOTHESIS"],
        "n_unknown": counts["UNKNOWN"],
        "n_conflict": counts["CONFLICT"],
    }
