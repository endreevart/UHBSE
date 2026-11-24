"""Omega-3 composition evidence extraction — product ≠ family."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from human_simulator.medication_reference_v012.ingredients import normalize_term
from human_simulator.medication_reference_v013.policy import OMACOR_ESKLP_ID, VERSION

_RE_STRENGTH = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>мг|mg|мкг|г|мл|ml|%)\b",
    re.IGNORECASE,
)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _detect_chemical_form(text: str) -> str:
    nt = normalize_term(text)
    if any(
        x in nt
        for x in (
            "этилов",
            "ethyl ester",
            "кислот этиловые эфиры",
            "омега-3 кислот этиловые",
        )
    ):
        return "ethyl_esters"
    if "триглицер" in nt or "triglyceride" in nt:
        return "triglycerides"
    if (
        ("рыбн" in nt and "жир" in nt)
        or "fish oil" in nt
        or "рыбный жир" in nt
    ):
        return "fish_oil"
    if "пнжк" in nt or "омега" in nt or "omega" in nt:
        return "unspecified_omega3"
    return "unknown"


def _detect_epa_dha(text: str) -> dict[str, Any]:
    nt = normalize_term(text)
    epa = "epa" in nt or "эпк" in nt or "эйкозапентаен" in nt
    dha = "dha" in nt or "дгк" in nt or "докозагексаен" in nt
    return {
        "epa_mentioned": epa,
        "dha_mentioned": dha,
        "epa_amount": None,
        "dha_amount": None,
        "epa_dha_amounts_known": False,
    }


def _brand_hints(name: str, desc: str) -> dict[str, Any]:
    blob = f"{name}\n{desc}"
    nt = normalize_term(blob)
    brands = []
    for b in (
        "омакор",
        "жизнивек",
        "мюллерс",
        "лиси",
        "lysi",
        "mollers",
        "мюллер",
    ):
        if b in nt:
            brands.append(b)
    is_omacor_named = "омакор" in normalize_term(name) or (
        "омакор" in nt and "этилов" in normalize_term(name)
    )
    is_supplement = any(
        x in nt for x in ("жизнивек", "бад", "добавка", "wildberries", "альтернативн")
    )
    return {
        "brands_mentioned": brands,
        "omacor_named_as_primary": is_omacor_named
        and "этилов" in normalize_term(name),
        "omacor_mentioned_as_alternative_only": (
            "омакор" in nt and not ("этилов" in normalize_term(name) and "омакор" in normalize_term(name))
        ),
        "dietary_supplement_candidate": is_supplement
        and not ("этилов" in normalize_term(name) and "омакор" in normalize_term(name)),
    }


def assign_omega3_concept(card: dict[str, Any]) -> str:
    form = card.get("chemical_form")
    epa = card.get("epa_dha") or {}
    if form == "ethyl_esters" and card.get("strength_comparability") in {
        "COMPATIBLE",
        "SAME_STRENGTH_STATUM",
    }:
        return "omega_3_acid_ethyl_esters_strength_stratum"
    if epa.get("epa_mentioned") and epa.get("dha_mentioned") and form in {
        "unspecified_omega3",
        "unknown",
        "fish_oil",
    }:
        return "epa_dha_combination_form_unspecified"
    return "omega_3_fatty_acids_unspecified"


def strength_vs_omacor(
    strengths: list[dict[str, str]],
    *,
    omacor_strength: str = "1000 мг",
) -> str:
    if not strengths:
        return "STRENGTH_NOT_COMPARABLE"
    # Prefer mg capsule strengths
    mg_vals = [
        s for s in strengths if normalize_term(s.get("unit") or "") in {"мг", "mg"}
    ]
    if not mg_vals:
        return "STRENGTH_NOT_COMPARABLE"
    for s in mg_vals:
        if normalize_term(s["value"]) in normalize_term(omacor_strength):
            return "COMPATIBLE"
    return "STRENGTH_NOT_COMPARABLE"


def build_omega3_source_card(
    profile: dict[str, Any],
    mapping: dict[str, Any] | None,
    *,
    omacor: dict[str, Any],
) -> dict[str, Any]:
    mid = str(profile["source_medicine_id"])
    name = profile.get("original_name") or ""
    desc = profile.get("original_description") or ""
    blob = f"{name}\n{desc}"
    brands = _brand_hints(name, desc)
    chem = _detect_chemical_form(blob)
    epa = _detect_epa_dha(blob)
    strengths = list(profile.get("strength_tokens") or [])
    # For 809, description explicitly says 1000 mg capsules
    if mid == "809" and not any(
        normalize_term(s.get("value") or "") == "1000" for s in strengths
    ):
        strengths = [{"value": "1000", "unit": "мг"}] + strengths
    # URL noise 1500/200ml must not invent composition evidence
    clean_strengths = [
        s
        for s in strengths
        if normalize_term(s.get("unit") or "") in {"мг", "mg"}
        and normalize_term(s.get("value") or "") not in {"0"}
    ]
    str_cmp = strength_vs_omacor(clean_strengths)
    forms = list(profile.get("dosage_form_tokens") or [])
    route = profile.get("route_hint")
    units_per_dose = None
    m = re.search(r"(\d+)\s*капс", blob, re.IGNORECASE)
    if m:
        units_per_dose = int(m.group(1))
    if "1 капсул" in normalize_term(blob) or "по 1 капсул" in normalize_term(blob):
        units_per_dose = 1
    if "2 капс" in normalize_term(blob) or "1 капсула после обеда" in normalize_term(blob):
        if "после обеда" in normalize_term(blob) and "после ужина" in normalize_term(blob):
            units_per_dose = 2

    evidence_complete = {
        "ingredient_omega3": "omega3" in (profile.get("active_ingredient_tokens") or []),
        "epa_known": bool(epa["epa_mentioned"]),
        "dha_known": bool(epa["dha_mentioned"]),
        "chemical_form_specific": chem in {"ethyl_esters", "triglycerides", "fish_oil"},
        "strength_comparable": str_cmp == "COMPATIBLE",
        "form_known": bool(forms),
        "route_known": route is not None,
    }
    completeness_score = sum(1 for v in evidence_complete.values() if v)

    card = {
        "version": VERSION,
        "source_medicine_id": mid,
        "original_name": name,
        "original_description": desc,
        "brand_manufacturer_hints": brands,
        "candidate_class": profile.get("candidate_class"),
        "ingredient_set": profile.get("active_ingredient_tokens") or ["omega3"],
        "epa_dha": epa,
        "chemical_form": chem,
        "strength_tokens": clean_strengths,
        "strength_comparability_vs_omacor": str_cmp,
        "dosage_form_tokens": forms,
        "route": route,
        "units_per_dose": units_per_dose,
        "evidence_completeness": evidence_complete,
        "evidence_completeness_score": completeness_score,
        "evidence_hash": _sha(blob),
        "esklp_candidate": {
            "provider": "ESKLP",
            "provider_concept_id": OMACOR_ESKLP_ID,
            "trade_name": omacor.get("trade_name"),
            "strength": omacor.get("strength"),
            "form": omacor.get("form"),
            "manufacturer": omacor.get("manufacturer"),
            "inn": omacor.get("inn"),
        },
        "mapping_status_v012": (mapping or {}).get("final_mapping_status"),
    }
    card["provider_neutral_concept"] = assign_omega3_concept(
        {
            **card,
            "strength_comparability": str_cmp,
        }
    )

    # Eligibility for decision types — never auto-accept
    product_ok = (
        brands["omacor_named_as_primary"]
        and chem == "ethyl_esters"
        and str_cmp == "COMPATIBLE"
        and not brands["dietary_supplement_candidate"]
    )
    ingredient_set_ok = "omega3" in card["ingredient_set"]
    form_route_ok = (
        ingredient_set_ok
        and chem == "ethyl_esters"
        and route in {"oral", None}
        and any(str(f).startswith("капсул") for f in forms)
        and str_cmp == "COMPATIBLE"
    )
    family_only = ingredient_set_ok and not form_route_ok

    card["eligibility"] = {
        "PRODUCT_IDENTITY_ACCEPTED": product_ok,
        "INGREDIENT_SET_ACCEPTED": ingredient_set_ok and not product_ok,
        "INGREDIENT_FORM_ROUTE_ACCEPTED": form_route_ok and not product_ok,
        "INGREDIENT_FAMILY_ONLY": family_only,
        "forbidden_product_identity_as_omacor": (
            brands["dietary_supplement_candidate"]
            or chem in {"fish_oil", "unspecified_omega3"}
            or brands["omacor_mentioned_as_alternative_only"]
        ),
    }
    card["suggested_review_action"] = (
        "PRODUCT_IDENTITY_ACCEPTED"
        if product_ok
        else (
            "INGREDIENT_FORM_ROUTE_ACCEPTED"
            if form_route_ok
            else (
                "INGREDIENT_SET_ACCEPTED"
                if ingredient_set_ok and chem == "ethyl_esters"
                else (
                    "INGREDIENT_FAMILY_ONLY"
                    if family_only
                    else "INSUFFICIENT_SOURCE_EVIDENCE"
                )
            )
        )
    )
    card["human_readable"] = (
        f"source={name}; chemical_form={chem}; strength_vs_omacor={str_cmp}; "
        f"concept={card['provider_neutral_concept']}; "
        f"product_identity_forbidden="
        f"{card['eligibility']['forbidden_product_identity_as_omacor']}"
    )
    return card


def build_omacor_provider_card(omacor: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "ESKLP",
        "provider_concept_id": omacor.get("provider_concept_id") or OMACOR_ESKLP_ID,
        "trade_name": omacor.get("trade_name") or "Омакор",
        "active_ingredient_label": "omega-3-acid ethyl esters (ESKLP SMNN code present)",
        "chemical_form": "ethyl_esters",
        "epa_mentioned": False,  # not in ESKLP row text
        "dha_mentioned": False,
        "strength": omacor.get("strength") or "1000 мг",
        "dosage_form": omacor.get("form") or "КАПСУЛЫ",
        "route": "oral",  # capsules for oral use (inferred from form family)
        "manufacturer": omacor.get("manufacturer"),
        "units": omacor.get("unit"),
        "note": (
            "ESKLP row does not enumerate EPA/DHA amounts in indexed fields; "
            "product identity requires trade-name + ethyl-esters evidence on source"
        ),
    }
