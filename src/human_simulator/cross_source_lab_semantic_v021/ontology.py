"""Explicit analyte ontology — concept identity, not substring family equality."""

from __future__ import annotations

import re
from typing import Any

# Ordered concept rules: (regex_on_normalized_or_raw_lower, concept_id, family_id, kind)
# More specific patterns MUST come before generic ones.
_CONCEPT_RULES: list[tuple[str, str, str, str]] = [
    # Lipids — subtypes before generic cholesterol
    (r"(лпнп|ldl|β-холестерин|бета.?холестерин)", "ldl_cholesterol", "lipid_cholesterol", "fraction"),
    (r"(лпвп|hdl|α-холестерин|альфа.?холестерин)", "hdl_cholesterol", "lipid_cholesterol", "fraction"),
    (r"(холестерин\s*общий|общий\s*холестерин|total\s*cholesterol|cholesterol\s*total)", "total_cholesterol", "lipid_cholesterol", "total"),
    (r"^холестеринобщий$", "total_cholesterol", "lipid_cholesterol", "total"),
    (r"(триглицерид|triglycerid)", "triglycerides", "lipid", "direct"),
    # Cellular indices vs HGB — before hemoglobin
    (r"\bmchc\b|средняяконцентрациягемоглобина|mchc", "mchc", "rbc_index", "cellular_index"),
    (r"\bmch\b|среднеесодержаниегемоглобина|(?<![a-z])mch(?!c)", "mch", "rbc_index", "cellular_index"),
    (r"\bmcv\b|среднийобъемэритроцит", "mcv", "rbc_index", "cellular_index"),
    (r"\brdw\b", "rdw", "rbc_index", "cellular_index"),
    (r"(hba1c|гликированн|гликозилированн)", "hba1c", "glucose_related", "derived"),
    (r"(гематокрит|hematocrit|\bhct\b)", "hematocrit", "rbc_panel", "direct"),
    (r"(эритроцит|\brbc\b)", "rbc", "rbc_panel", "direct"),
    (r"(гемоглобин|\bhgb\b|\bhb\b)(?!a1c)", "hgb", "rbc_panel", "direct"),
    # Thyroid
    (r"(ттг|тиреотропн|\btsh\b)", "tsh", "thyroid", "direct"),
    (r"(т3свобод|т3св|freet3|ft3|трийодтиронинсвобод)", "free_t3", "thyroid", "free"),
    (r"(т3общ|totalt3|трийодтиронинобщ)", "total_t3", "thyroid", "total"),
    (r"(т4свобод|т4св|freet4|ft4|тироксинсвобод)", "free_t4", "thyroid", "free"),
    (r"(т4общ|totalt4|тироксинобщ)", "total_t4", "thyroid", "total"),
    # Liver / kidney
    (r"(билирубин\s*прямо|прямой\s*билирубин|direct\s*bilirubin|conjugated)", "direct_bilirubin", "bilirubin", "fraction"),
    (r"(билирубин\s*общ|общий\s*билирубин|total\s*bilirubin)", "total_bilirubin", "bilirubin", "total"),
    (r"(альбумин|albumin)", "albumin", "protein", "direct"),
    (r"(общий\s*белок|total\s*protein|белокобщ)", "total_protein", "protein", "total"),
    (r"(креатинин|creatinine)", "creatinine", "kidney", "direct"),
    (r"(egfr|скф|скоростьклубочков)", "egfr", "kidney", "derived"),
    (r"\bалт\b|аланинамино|alt\b", "alt", "liver_enzyme", "direct"),
    (r"\bаст\b|аспартатамино|ast\b", "ast", "liver_enzyme", "direct"),
    # Endocrine
    (r"(с.?пептид|c.?peptide)", "c_peptide", "insulin_axis", "direct"),
    (r"(инсулин|insulin)", "insulin", "insulin_axis", "direct"),
    (r"(глюкоза|glucose)", "glucose", "glucose", "direct"),
    (r"(ферритин|ferritin)", "ferritin", "iron", "direct"),
    (r"(витамин\s*d|25.?oh|25\(oh\))", "vit_d_25oh", "vitamin", "direct"),
    (r"(пролактин|prolactin)", "prolactin", "hormone", "direct"),
    (r"(кортизол|cortisol)", "cortisol", "hormone", "direct"),
    (r"\bпса\b|\bpsa\b", "psa", "tumor_marker", "direct"),
    (r"(срб|с.?реактивн|crp)", "crp", "inflammation", "direct"),
    (r"(лейкоцит|\bwbc\b)", "wbc", "cbc", "direct"),
    (r"(тромбоцит|\bplt\b|platelet)", "plt", "cbc", "direct"),
]

# Approved synonym: concept_id → alternate normalized phrases that mean THE SAME concept
APPROVED_SYNONYMS: dict[str, list[str]] = {
    "free_t3": ["трийодтиронин свободный", "т3 свободный", "free t3", "ft3"],
    "free_t4": ["тироксин свободный", "т4 свободный", "free t4", "ft4"],
    "tsh": ["тиреотропный гормон", "тиреотропин", "tsh"],
    "total_cholesterol": ["холестерин общий", "общий холестерин", "total cholesterol"],
    "ldl_cholesterol": ["холестерин лпнп", "лпнп", "ldl", "ldl cholesterol"],
    "hdl_cholesterol": ["холестерин лпвп", "лпвп", "hdl", "hdl cholesterol"],
    "hgb": ["гемоглобин", "hgb", "hb"],
    "mchc": ["mchc", "средняя концентрация гемоглобина в эритроцитах"],
}

# Pairs that must never have analyte identity (concept or family misuse)
NEGATIVE_CONCEPT_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("total_cholesterol", "ldl_cholesterol"),
        ("total_cholesterol", "hdl_cholesterol"),
        ("ldl_cholesterol", "hdl_cholesterol"),
        ("hgb", "mch"),
        ("hgb", "mchc"),
        ("hgb", "hba1c"),
        ("rbc", "hematocrit"),
        ("free_t3", "total_t3"),
        ("free_t4", "total_t4"),
        ("tsh", "free_t3"),
        ("tsh", "total_t3"),
        ("tsh", "free_t4"),
        ("tsh", "total_t4"),
        ("total_bilirubin", "direct_bilirubin"),
        ("creatinine", "egfr"),
        ("total_protein", "albumin"),
        ("insulin", "c_peptide"),
        ("alt", "ast"),
    }
)

SECONDS_UNITS = frozenset({"сек.", "сек", "s", "sec", "second", "seconds"})


def normalize_label(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    return re.sub(r"[\s_\-./()]+", "", t)


def resolve_analyte(label: str) -> dict[str, Any]:
    """Map a free-text lab label to explicit concept/family/kind."""
    raw = (label or "").lower().replace("ё", "е")
    n = normalize_label(label)
    for pat, concept, family, kind in _CONCEPT_RULES:
        if re.search(pat, raw, flags=re.IGNORECASE) or re.search(
            pat.replace(r"\s*", "").replace(r"\s+", ""), n, flags=re.IGNORECASE
        ):
            # Prefer matching on raw with spaces for phrase rules; also try normalized
            if re.search(pat, raw, flags=re.IGNORECASE) or (
                re.search(pat, n, flags=re.IGNORECASE)
                if "\\s" not in pat and " " not in pat
                else False
            ):
                return {
                    "concept_id": concept,
                    "family_id": family,
                    "kind": kind,
                    "label": label,
                    "normalized": n,
                }
            # normalized fallback for compact patterns
            if re.search(pat, n, flags=re.IGNORECASE):
                return {
                    "concept_id": concept,
                    "family_id": family,
                    "kind": kind,
                    "label": label,
                    "normalized": n,
                }
    # Second pass: normalized-only for compact keys
    for pat, concept, family, kind in _CONCEPT_RULES:
        compact = pat.replace(r"\s*", "").replace(r"\s+", "").replace(" ", "")
        try:
            if re.search(compact, n, flags=re.IGNORECASE):
                return {
                    "concept_id": concept,
                    "family_id": family,
                    "kind": kind,
                    "label": label,
                    "normalized": n,
                }
        except re.error:
            continue
    return {
        "concept_id": None,
        "family_id": None,
        "kind": None,
        "label": label,
        "normalized": n,
    }


def compare_analytes(a_label: str, b_label: str) -> dict[str, Any]:
    """Return identity status. Family match alone NEVER sets analyte_ok."""
    a = resolve_analyte(a_label)
    b = resolve_analyte(b_label)
    a_c, b_c = a.get("concept_id"), b.get("concept_id")
    a_f, b_f = a.get("family_id"), b.get("family_id")

    # Explicit negative pairs
    if a_c and b_c and (
        (a_c, b_c) in NEGATIVE_CONCEPT_PAIRS or (b_c, a_c) in NEGATIVE_CONCEPT_PAIRS
    ):
        kind_conflict = "DERIVED_MEASURE_CONFLICT" if (
            a.get("kind") == "derived"
            or b.get("kind") == "derived"
            or a.get("kind") == "cellular_index"
            or b.get("kind") == "cellular_index"
        ) else "ANALYTE_SUBTYPE_CONFLICT"
        return {
            "a": a,
            "b": b,
            "analyte_ok": False,
            "identity_level": kind_conflict,
            "retrieval_ok": False,
            "conflict": f"negative_control:{a_c}!={b_c}",
        }

    # Exact concept
    if a_c and b_c and a_c == b_c:
        return {
            "a": a,
            "b": b,
            "analyte_ok": True,
            "identity_level": "EXACT_ANALYTE_IDENTITY",
            "retrieval_ok": True,
            "conflict": None,
        }

    # Approved synonym: same concept via synonym phrase on B for A's concept
    if a_c and a_c in APPROVED_SYNONYMS:
        b_low = (b_label or "").lower().replace("ё", "е")
        for syn in APPROVED_SYNONYMS[a_c]:
            if syn.lower() in b_low and (not b_c or b_c == a_c):
                return {
                    "a": a,
                    "b": b,
                    "analyte_ok": True,
                    "identity_level": "APPROVED_ANALYTE_SYNONYM",
                    "retrieval_ok": True,
                    "conflict": None,
                }

    # Subtype within same family but different concepts
    if a_c and b_c and a_f and a_f == b_f and a_c != b_c:
        return {
            "a": a,
            "b": b,
            "analyte_ok": False,
            "identity_level": "ANALYTE_SUBTYPE_CONFLICT",
            "retrieval_ok": False,
            "conflict": f"subtype:{a_c}!={b_c}",
        }

    # Family-only retrieval — NEVER analyte_ok
    if a_f and b_f and a_f == b_f:
        return {
            "a": a,
            "b": b,
            "analyte_ok": False,
            "identity_level": "ANALYTE_FAMILY_RETRIEVAL_ONLY",
            "retrieval_ok": True,
            "conflict": None,
        }

    # Normalized exact label without concept
    if a.get("normalized") and a.get("normalized") == b.get("normalized"):
        return {
            "a": a,
            "b": b,
            "analyte_ok": True,
            "identity_level": "EXACT_ANALYTE_IDENTITY",
            "retrieval_ok": True,
            "conflict": None,
        }

    return {
        "a": a,
        "b": b,
        "analyte_ok": False,
        "identity_level": "INSUFFICIENT_ANALYTE_EVIDENCE",
        "retrieval_ok": False,
        "conflict": None,
    }


def negative_control_violation(*, a_label: str, b_label: str, b_unit: str = "") -> str | None:
    cmp = compare_analytes(a_label, b_label)
    if cmp.get("conflict") and str(cmp["conflict"]).startswith("negative_control"):
        return cmp["conflict"]
    a_c = (cmp.get("a") or {}).get("concept_id")
    if a_c == "tsh" and (b_unit or "").strip().lower() in SECONDS_UNITS:
        return "negative_control:tsh_neq_seconds"
    return None


def ontology_snapshot() -> dict[str, Any]:
    return {
        "n_concept_rules": len(_CONCEPT_RULES),
        "n_negative_pairs": len(NEGATIVE_CONCEPT_PAIRS),
        "n_approved_synonym_concepts": len(APPROVED_SYNONYMS),
        "family_never_sets_analyte_ok": True,
        "substring_alone_insufficient": True,
    }
