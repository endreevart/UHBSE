"""Phase 1 — source medication semantic profiles (private, technical classification)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v012.ingredients import (
    detect_ingredients,
    extract_forms,
    extract_strengths,
    identity_tokens,
    infer_route,
    normalize_term,
)
from human_simulator.medication_reference_v012.policy import (
    EXPECTED_MEDICINE_IDS,
    PRIOR_CONCEPT_REGISTRY,
    RUNTIME_DIR,
    VERSION,
)

_SUPPLEMENT_HINTS = (
    "бад",
    "жизнивек",
    "snt",
    "solgar",
    "now",
    "wildberries",
    "пищевая добавка",
    "биологически активн",
)
_DRUG_HINTS = (
    "мг",
    "мкг",
    "таблет",
    "капсул",
    "раствор",
    "мазь",
    "спрей",
    "суспенз",
    "рецепт",
)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_source_records(root: Path) -> list[dict[str, Any]]:
    path = root / PRIOR_CONCEPT_REGISTRY
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    if len(rows) != EXPECTED_MEDICINE_IDS:
        raise ValueError(f"expected_{EXPECTED_MEDICINE_IDS}_source_medicines_got_{len(rows)}")
    return rows


def _guess_trade_name(name: str) -> str:
    # Drop trailing parenthetical manufacturer lists for trade guess
    head = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    # Drop leading ПРО / marketing
    toks = identity_tokens(head)
    return " ".join(toks[:4]) if toks else normalize_term(head)


def _candidate_class(
    *,
    text: str,
    ingredients: list[str],
    route: str | None,
    forms: list[str],
    combination: bool,
) -> str:
    nt = normalize_term(text)
    if combination:
        return "COMBINATION_PRODUCT_CANDIDATE"
    if route == "topical" or any(
        f.startswith(("мазь", "крем", "гель", "спрей")) for f in forms
    ):
        return "TOPICAL_PRODUCT_CANDIDATE"
    if any(h in nt for h in _SUPPLEMENT_HINTS) and not any(
        x in ingredients
        for x in (
            "levothyroxine",
            "thiamazole",
            "omeprazole",
            "metformin",
            "nitrofural",
            "augmentin",
        )
    ):
        return "DIETARY_SUPPLEMENT_CANDIDATE"
    if not ingredients and not any(h in nt for h in _DRUG_HINTS):
        return "INSUFFICIENT_SEMANTIC_DATA"
    if ingredients or any(h in nt for h in _DRUG_HINTS):
        return "REGISTERED_DRUG_CANDIDATE"
    return "INSUFFICIENT_SEMANTIC_DATA"


def build_semantic_profile(record: dict[str, Any]) -> dict[str, Any]:
    mid = str(record["source_medicine_id"])
    name = str(record.get("original_name") or "")
    desc = str(record.get("original_description") or "")
    if not name.strip():
        raise ValueError(f"missing_original_name:{mid}")
    blob = f"{name}\n{desc}"
    ingredients = detect_ingredients(blob)
    # salt/form tokens: keep glycinate/picolinate etc. as free tokens
    salt_tokens = [
        t
        for t in identity_tokens(blob)
        if t
        in {
            "глицинат",
            "пиколинат",
            "сульфат",
            "ацетат",
            "хелат",
            "хелатный",
            "клавуланат",
        }
    ]
    strengths = extract_strengths(blob)
    # prefer registry candidate strength when present
    if record.get("candidate_strength_value"):
        strengths = [
            {
                "value": str(record["candidate_strength_value"])
                .replace(" мг", "")
                .replace(" мкг", "")
                .replace("мг", "")
                .replace("мкг", "")
                .strip()
                or str(record["candidate_strength_value"]),
                "unit": str(
                    record.get("candidate_strength_unit")
                    or record.get("strength_unit")
                    or ""
                )
                .casefold()
                .replace("none", "")
                or (
                    "мкг"
                    if "мкг" in str(record.get("candidate_strength_value"))
                    else "мг"
                    if "мг" in str(record.get("candidate_strength_value"))
                    else ""
                ),
            }
        ] + strengths
    forms = extract_forms(blob)
    route = infer_route(blob, forms)
    combination = ("+" in name) or (len(ingredients) >= 2 and " и " in normalize_term(name))
    candidate_class = _candidate_class(
        text=blob,
        ingredients=ingredients,
        route=route,
        forms=forms,
        combination=combination,
    )
    return {
        "version": VERSION,
        "source_medicine_id": mid,
        "original_name": name,
        "original_description": desc,
        "normalized_source_name": record.get("normalized_source_name")
        or normalize_term(name),
        "guessed_trade_name": _guess_trade_name(name),
        "active_ingredient_tokens": ingredients,
        "salt_form_tokens": salt_tokens,
        "strength_tokens": strengths[:8],
        "dosage_form_tokens": forms,
        "route_hint": route,
        "combination_product_flag": combination,
        "route_family": route or "unknown",
        "candidate_class": candidate_class,
        "identity_tokens": identity_tokens(name),
        "source_text_hash": record.get("source_text_hash") or _sha(f"{name}|{desc}"),
        "episode_coverage": record.get("episode_coverage") or {},
        "technical_classification_only": True,
        "not_a_clinical_claim": True,
    }


def build_all_profiles(root: Path) -> list[dict[str, Any]]:
    records = load_source_records(root)
    return [build_semantic_profile(r) for r in records]


def write_profiles(root: Path, profiles: list[dict[str, Any]]) -> Path:
    out = root / RUNTIME_DIR / "semantics" / "source-semantic-profiles.private.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for p in profiles:
            fh.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")
    return out
