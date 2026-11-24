"""Provider-neutral concept layer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v013.policy import RUNTIME_DIR, VERSION


def _nid(kind: str, *parts: str) -> str:
    blob = "|".join([kind, *parts])
    return f"{kind}_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:28]


def build_provider_neutral_bundle(
    *,
    source_medicine_id: str,
    original_text: str,
    ingredients: list[str],
    chemical_form: str | None,
    dosage_form: str | None,
    route: str | None,
    strength_key: str | None,
    family: str | None,
    esklp_ref: str | None,
    evidence_level: str,
    reviewer_decision: str | None = None,
) -> dict[str, Any]:
    ing_key = ",".join(sorted(ingredients)) or "none"
    form = dosage_form or "unknown_form"
    rte = route or "unknown_route"
    chem = chemical_form or "unknown_chem"
    fam = family or "unknown_family"
    strength = strength_key or "strength_unknown"

    product = _nid("MedicationProductConcept", source_medicine_id, esklp_ref or "none")
    ing_set = _nid("IngredientSetConcept", ing_key)
    chem_c = _nid("ChemicalFormConcept", ing_key, chem)
    ifr = _nid("IngredientFormRouteConcept", ing_key, chem, form, rte)
    stratum = _nid("StrengthStratum", ifr, strength)
    family_c = _nid("IngredientFamilyConcept", fam)

    return {
        "version": VERSION,
        "source_medicine_id": source_medicine_id,
        "original_text_hash": hashlib.sha256(original_text.encode()).hexdigest(),
        "MedicationProductConcept": {
            "id": product,
            "esklp_external_reference": esklp_ref,
            "note": "ESKLP ID is external reference, not sole internal concept id",
        },
        "IngredientSetConcept": {"id": ing_set, "ingredients": ingredients},
        "ChemicalFormConcept": {"id": chem_c, "chemical_form": chem},
        "IngredientFormRouteConcept": {
            "id": ifr,
            "ingredients": ingredients,
            "chemical_form": chem,
            "dosage_form": form,
            "route": rte,
        },
        "StrengthStratum": {"id": stratum, "strength_key": strength},
        "IngredientFamilyConcept": {"id": family_c, "family": fam},
        "provider_mapping": {"ESKLP": esklp_ref},
        "evidence_level": evidence_level,
        "reviewer_decision": reviewer_decision,
        "provenance": {
            "source_system": "magerya_api",
            "record_origin": "OBSERVED",
            "transformation": "acceptance_semantics_v0.1.3",
        },
    }


def write_omega3_concept_hierarchy(
    root: Path, cards: list[dict[str, Any]], omacor_card: dict[str, Any]
) -> Path:
    bundles = []
    for c in cards:
        bundles.append(
            build_provider_neutral_bundle(
                source_medicine_id=str(c["source_medicine_id"]),
                original_text=f"{c.get('original_name')}\n{c.get('original_description')}",
                ingredients=list(c.get("ingredient_set") or []),
                chemical_form=c.get("chemical_form"),
                dosage_form=",".join(c.get("dosage_form_tokens") or []) or None,
                route=c.get("route"),
                strength_key=json.dumps(c.get("strength_tokens") or [], ensure_ascii=False),
                family="omega3_fatty_acids",
                esklp_ref=(c.get("esklp_candidate") or {}).get("provider_concept_id"),
                evidence_level=c.get("provider_neutral_concept") or "unspecified",
            )
        )
    # Separate concepts must remain distinct
    distinct = {
        "omega_3_fatty_acids_unspecified",
        "epa_dha_combination_form_unspecified",
        "omega_3_acid_ethyl_esters_strength_stratum",
    }
    path = root / RUNTIME_DIR / "review-pack" / "omega3-concept-hierarchy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": VERSION,
        "omacor_provider": omacor_card,
        "required_distinct_concepts": sorted(distinct),
        "source_bundles": bundles,
        "concept_ids_by_source": {
            c["source_medicine_id"]: c.get("provider_neutral_concept") for c in cards
        },
        "no_automatic_merge_across_chemical_forms": True,
        "supplement_cannot_inherit_omacor_product_id": True,
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
