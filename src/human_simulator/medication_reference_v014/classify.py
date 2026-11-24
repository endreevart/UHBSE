"""Phase 0 baseline + typed classification of 85 ingredient-compatible candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v012.ingredients import normalize_term
from human_simulator.medication_reference_v013.omega3_evidence import _detect_chemical_form
from human_simulator.medication_reference_v014.policy import (
    BROAD_FAMILY_INGREDIENTS,
    EXPECTED_COMPATIBLE_CANDIDATES,
    EXPECTED_ESKLP_SNAPSHOT,
    EXPECTED_MEDICINE_IDS,
    EXPECTED_SNAPSHOT_SHA256,
    REGRESSION_REJECTS,
    V011_DECISION_LOG,
    V011_MAPPING,
    V012_MAPPING,
    V012_PROFILES,
    V013_SUMMARY,
    V013_TYPED_LOG,
    VERSION,
)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def verify_baseline(root: Path) -> dict[str, Any]:
    snap = root / EXPECTED_ESKLP_SNAPSHOT
    sha = _sha_file(snap) if snap.is_file() else None
    maps = load_jsonl(root / V012_MAPPING)
    compat = [m for m in maps if int(m.get("n_candidates") or 0) > 0]
    v011 = load_jsonl(root / V011_MAPPING)
    log = load_jsonl(root / V011_DECISION_LOG)
    rej = {
        (
            str(r["source_medicine_id"]),
            str(r.get("candidate_id") or r.get("provider_concept_id")),
        )
        for r in log
        if r.get("decision") == "HUMAN_REJECTED"
    }
    typed = load_jsonl(root / V013_TYPED_LOG)
    usable = 0
    if (root / V013_SUMMARY).is_file():
        s = json.loads((root / V013_SUMMARY).read_text(encoding="utf-8"))
        usable = int(s.get("SCIENTIFICALLY_USABLE_ACCEPTED_COUNT") or 0)
        no_train = bool(s.get("no_model_training")) and s.get(
            "association_baseline_status"
        ) in {None, "NOT_RUN"}
    else:
        no_train = True
    return {
        "snapshot_ok": sha == EXPECTED_SNAPSHOT_SHA256,
        "snapshot_sha256": sha,
        "n_source_medicines": len(v011),
        "accounting_ok": len(v011) == EXPECTED_MEDICINE_IDS,
        "n_compatible_candidates": len(compat),
        "compatible_accounting_ok": len(compat) == EXPECTED_COMPATIBLE_CANDIDATES,
        "historical_authoritative_accepted": sum(
            1
            for r in v011
            if r.get("drug_concept_status")
            in {"EXACT_PROVIDER_MATCH", "SUPPORTED_TRANSFORM", "HUMAN_ACCEPTED"}
        ),
        "human_accepted": sum(
            1 for r in v011 if r.get("drug_concept_status") == "HUMAN_ACCEPTED"
        ),
        "scientifically_usable_accepted": usable,
        "decision_log_ok": set(REGRESSION_REJECTS) <= rej and len(log) == 6,
        "n_human_rejected": len([r for r in log if r.get("decision") == "HUMAN_REJECTED"]),
        "typed_v013_decisions_ingested": len(typed),
        "typed_decisions": typed,
        "no_model_training_after_v013": no_train,
        "gates_unchanged": {"min_subjects": 100, "min_episodes": 300, "min_test_subjects": 30},
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
    }


def form_family(tokens: list[str] | None, prov_form: str | None) -> str:
    blob = normalize_term(
        " ".join([*(tokens or []), prov_form or ""])
    )
    if any(x in blob for x in ("таблет", "таб ")):
        return "tablet"
    if "капсул" in blob:
        return "capsule"
    if any(x in blob for x in ("мазь", "крем", "гель")):
        return "topical_semisolid"
    if "спрей" in blob:
        return "spray"
    if "капл" in blob:
        return "drops"
    if any(x in blob for x in ("раствор", "суспенз", "сироп", "жидк")):
        return "liquid"
    if any(x in blob for x in ("порошок", "гранул", "лиофил")):
        return "powder"
    if "ингаляц" in blob:
        return "inhalation"
    return "unknown_form"


def strength_stratum(
    strength_tokens: list[dict[str, str]] | None,
    prov_strength: str | None,
    *,
    strength_compat: str | None,
) -> str:
    """Return comparable stratum key or unknown_strength / not_comparable."""
    if strength_compat == "CONFLICT":
        return "strength_conflict"
    mg = [
        s
        for s in (strength_tokens or [])
        if normalize_term(s.get("unit") or "") in {"мг", "mg", "мкг", "mcg", "ме", "iu"}
        and normalize_term(s.get("value") or "") not in {"", "0"}
    ]
    if mg:
        # prefer mcg/mg matching provider when possible
        s0 = mg[0]
        return f"{normalize_term(s0['value'])}_{normalize_term(s0['unit'])}"
    if prov_strength and strength_compat == "COMPATIBLE":
        return "provider_" + normalize_term(prov_strength).replace(" ", "_")
    return "unknown_strength"


def detect_chemical_form(profile: dict[str, Any], top: dict[str, Any]) -> str:
    blob = f"{profile.get('original_name')}\n{profile.get('original_description')}"
    # omega-3 specific
    chem = _detect_chemical_form(blob)
    if chem not in {"unknown", "unspecified_omega3"}:
        return chem
    salts = list(profile.get("salt_form_tokens") or [])
    if salts:
        return "salt:" + ",".join(sorted(salts))
    trade = normalize_term(top.get("trade_name") or "")
    # levothyroxine sodium often implicit in eutirox — keep unspecified salt
    ings = set(profile.get("active_ingredient_tokens") or [])
    if ings == {"levothyroxine"}:
        return "levothyroxine_unspecified_salt"
    if ings == {"ursodeoxycholic_acid"}:
        return "udca_unspecified"
    if ings == {"metformin"}:
        return "metformin_unspecified"
    if ings & {"omega3"}:
        return chem  # unspecified_omega3 / fish_oil / etc.
    if ings & BROAD_FAMILY_INGREDIENTS and len(ings) == 1:
        return "family_unspecified_chemical_form"
    return "unspecified"


def classify_candidate(
    mapping: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    mid = str(mapping["source_medicine_id"])
    top = (mapping.get("candidates") or [None])[0] or {}
    ings = list(mapping.get("active_ingredient_tokens") or profile.get("active_ingredient_tokens") or [])
    route = profile.get("route_hint") or mapping.get("route_hint")
    forms = list(profile.get("dosage_form_tokens") or [])
    fam = form_family(forms, top.get("dosage_form") or top.get("form"))
    chem = detect_chemical_form(profile, top)
    str_toks = list(profile.get("strength_tokens") or [])
    # filter noise % / 0
    str_toks = [
        s
        for s in str_toks
        if normalize_term(s.get("unit") or "") in {"мг", "mg", "мкг", "mcg", "ме", "iu", "г", "g"}
        and normalize_term(s.get("value") or "") not in {"", "0"}
    ]
    s_compat = top.get("strength_compatibility")
    f_compat = top.get("form_compatibility")
    r_compat = top.get("route_compatibility")
    i_compat = top.get("ingredient_compatibility")
    stratum = strength_stratum(str_toks, top.get("strength"), strength_compat=s_compat)

    positive = list(top.get("positive_evidence") or mapping.get("positive_evidence") or [])
    negative = list(top.get("negative_evidence") or mapping.get("negative_evidence") or [])
    hard = bool(top.get("hard_conflict")) or i_compat == "CONFLICT" or r_compat == "CONFLICT"

    name = mapping.get("original_name") or profile.get("original_name") or ""
    desc = profile.get("original_description") or ""
    trade = top.get("trade_name") or ""
    product_identity = False
    nt_name = normalize_term(name)
    nt_trade = normalize_term(trade)
    # Require substantial trade-name identity (not marketing crumbs / short tokens)
    if (
        nt_trade
        and len(nt_trade) >= 5
        and nt_trade in nt_name
        and i_compat == "COMPATIBLE"
        and profile.get("candidate_class") != "DIETARY_SUPPLEMENT_CANDIDATE"
    ):
        product_identity = True
    # Explicit registered Omacor ethyl esters
    if "омакор" in nt_name and chem == "ethyl_esters":
        product_identity = True
        if profile.get("candidate_class") == "DIETARY_SUPPLEMENT_CANDIDATE":
            product_identity = False

    # Broad family without specific chemical/product evidence
    family_only = False
    if set(ings) <= BROAD_FAMILY_INGREDIENTS and len(ings) == 1:
        if chem in {
            "family_unspecified_chemical_form",
            "unspecified_omega3",
            "fish_oil",
            "unspecified",
        }:
            family_only = True
        if profile.get("candidate_class") == "DIETARY_SUPPLEMENT_CANDIDATE" and not product_identity:
            family_only = True

    level = "INSUFFICIENT_SOURCE_EVIDENCE"
    if hard or not ings:
        level = "HARD_CONFLICT" if hard else "INSUFFICIENT_SOURCE_EVIDENCE"
    elif family_only:
        level = "INGREDIENT_FAMILY_ONLY"
    elif product_identity and i_compat == "COMPATIBLE" and s_compat == "COMPATIBLE" and f_compat in {
        "COMPATIBLE",
        "UNKNOWN",
    }:
        level = "PRODUCT_IDENTITY_CANDIDATE"
    elif (
        i_compat == "COMPATIBLE"
        and f_compat == "COMPATIBLE"
        and r_compat in {"COMPATIBLE", "UNKNOWN"}
        and s_compat == "COMPATIBLE"
        and stratum not in {"unknown_strength", "strength_conflict"}
    ):
        level = "INGREDIENT_FORM_ROUTE_STRENGTH_CANDIDATE"
    elif (
        i_compat == "COMPATIBLE"
        and f_compat == "COMPATIBLE"
        and r_compat in {"COMPATIBLE", "UNKNOWN"}
    ):
        level = "INGREDIENT_FORM_ROUTE_CANDIDATE"
    elif i_compat in {"COMPATIBLE", "PARTIAL"}:
        level = "INGREDIENT_SET_CANDIDATE"
    else:
        level = "INSUFFICIENT_SOURCE_EVIDENCE"

    evidence_complete = {
        "ingredient": bool(ings) and i_compat == "COMPATIBLE",
        "chemical_form_specific": chem
        not in {
            "unspecified",
            "family_unspecified_chemical_form",
            "unspecified_omega3",
            "levothyroxine_unspecified_salt",
            "udca_unspecified",
            "metformin_unspecified",
        },
        "route": route is not None and r_compat != "CONFLICT",
        "dosage_form": fam != "unknown_form" and f_compat != "CONFLICT",
        "strength": stratum not in {"unknown_strength", "strength_conflict"}
        and s_compat == "COMPATIBLE",
        "product_identity": product_identity,
    }

    return {
        "version": VERSION,
        "source_medicine_id": mid,
        "original_name": name,
        "original_description": desc,
        "candidate_class": profile.get("candidate_class") or mapping.get("candidate_class"),
        "provider_concept_id": top.get("provider_concept_id") or mapping.get("provider_concept_id"),
        "provider_trade_name": trade,
        "provider_strength": top.get("strength"),
        "provider_form": top.get("dosage_form") or top.get("form"),
        "active_ingredient_set": sorted(ings),
        "chemical_form": chem,
        "dosage_form_family": fam,
        "route": route or "unknown_route",
        "strength_tokens": str_toks[:6],
        "strength_stratum": stratum,
        "typed_level": level,
        "ingredient_compatibility": i_compat,
        "form_compatibility": f_compat,
        "route_compatibility": r_compat,
        "strength_compatibility": s_compat,
        "positive_evidence": positive,
        "negative_evidence": negative,
        "hard_conflict": hard,
        "evidence_completeness": evidence_complete,
        "evidence_completeness_score": sum(1 for v in evidence_complete.values() if v),
        "episode_coverage": mapping.get("episode_coverage") or profile.get("episode_coverage") or {},
        "evidence_hash": hashlib.sha256(f"{name}|{desc}|{top.get('provider_concept_id')}".encode()).hexdigest(),
    }


def classify_all_compatible(root: Path) -> list[dict[str, Any]]:
    maps = load_jsonl(root / V012_MAPPING)
    profs = {str(p["source_medicine_id"]): p for p in load_jsonl(root / V012_PROFILES)}
    compat = [m for m in maps if int(m.get("n_candidates") or 0) > 0]
    if len(compat) != EXPECTED_COMPATIBLE_CANDIDATES:
        raise ValueError(
            f"expected_{EXPECTED_COMPATIBLE_CANDIDATES}_compatible_got_{len(compat)}"
        )
    # exclude rejected pairs' medicines from capable use but still classify
    out = []
    for m in compat:
        p = profs.get(str(m["source_medicine_id"])) or {}
        out.append(classify_candidate(m, p))
    out.sort(
        key=lambda r: (
            -int((r.get("episode_coverage") or {}).get("n_episodes") or 0),
            r["source_medicine_id"],
        )
    )
    return out
