"""Phase 2–3 — ingredient-first semantic matcher + provider routing."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.esklp_ingest import load_esklp_index
from human_simulator.medication_reference_v012.ingredients import (
    alias_lookup_keys,
    detect_ingredients,
    form_compatible,
    hard_veto_explanation,
    identity_tokens,
    ingredient_sets_compatible,
    normalize_term,
    provider_text_ingredients,
    route_compatible,
    strength_compatible,
)
from human_simulator.medication_reference_v012.policy import (
    EXPECTED_SNAPSHOT_SHA256,
    REGRESSION_REJECTS,
    RUNTIME_DIR,
    V011_RUNTIME_DIR,
    VERSION,
)


def _decision_log_pairs(root: Path) -> set[tuple[str, str]]:
    """Read v0.1.1 decision log without mutating it."""
    path = root / V011_RUNTIME_DIR / "review" / "decision-log.jsonl"
    pairs: set[tuple[str, str]] = set(REGRESSION_REJECTS)
    if not path.is_file():
        return pairs
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("decision") != "HUMAN_REJECTED":
                continue
            mid = str(row.get("source_medicine_id") or "")
            cid = str(row.get("candidate_id") or row.get("provider_concept_id") or "")
            if mid and cid:
                pairs.add((mid, cid))
    return pairs


def build_ingredient_postings(index: dict[str, Any]) -> dict[str, list[str]]:
    """Map canonical ingredient -> provider_concept_ids (bounded per ingredient)."""
    aliases = alias_lookup_keys()
    by_id = index.get("by_id") or {}
    postings: dict[str, set[str]] = defaultdict(set)
    # Prefer trade/inn lookup keys
    for field in ("by_trade_name", "by_inn"):
        for term, cids in (index.get(field) or {}).items():
            nt = normalize_term(term)
            if not nt or nt[:2].isdigit():
                continue
            for key, als in aliases.items():
                if any(a in nt or nt in a for a in als if len(a) >= 4):
                    for cid in cids[:80]:
                        postings[key].add(cid)
    # Cap
    return {k: sorted(v)[:400] for k, v in postings.items()}


def _candidate_evidence(
    profile: dict[str, Any],
    concept: dict[str, Any],
    *,
    method: str,
) -> dict[str, Any]:
    src_ings = list(profile.get("active_ingredient_tokens") or [])
    trade = concept.get("trade_name") or ""
    inn = concept.get("inn") or ""
    prov_ings = provider_text_ingredients(trade, inn, *(concept.get("ingredients") or []))
    # If provider INN is a SMNN code, rely on trade-detected ingredients only
    if not prov_ings and trade:
        prov_ings = detect_ingredients(trade)

    ing_c = ingredient_sets_compatible(src_ings, prov_ings)
    form_c = form_compatible(
        list(profile.get("dosage_form_tokens") or []), concept.get("form")
    )
    route_c = route_compatible(
        profile.get("route_hint"), concept.get("form"), concept.get("route")
    )
    str_c = strength_compatible(
        list(profile.get("strength_tokens") or []), concept.get("strength")
    )
    veto = hard_veto_explanation(
        src_ings=src_ings,
        prov_ings=prov_ings,
        route_c=route_c,
        form_c=form_c,
        strength_c=str_c,
    )
    positive: list[str] = []
    if ing_c == "COMPATIBLE":
        positive.append("ingredient_set_compatible")
    if form_c == "COMPATIBLE":
        positive.append("form_compatible")
    if route_c == "COMPATIBLE":
        positive.append("route_compatible")
    if str_c == "COMPATIBLE":
        positive.append("strength_compatible")
    trade_nt = normalize_term(trade)
    guess = normalize_term(profile.get("guessed_trade_name") or "")
    if guess and trade_nt and (guess == trade_nt or guess in trade_nt or trade_nt in guess):
        positive.append("trade_name_overlap")

    hard = bool(veto) or ing_c == "CONFLICT" or route_c == "CONFLICT"
    # Marketing-only overlap is never positive evidence of identity
    id_toks = set(identity_tokens(profile.get("original_name") or ""))
    trade_toks = set(identity_tokens(trade))
    only_marketingish = bool(id_toks & trade_toks) and not src_ings

    status = "HARD_CONFLICT" if hard else "CANDIDATE"
    if only_marketingish and "ingredient_set_compatible" not in positive:
        status = "HARD_CONFLICT"
        veto = list(veto) + ["marketing_token_only_no_ingredient_evidence"]

    explanation_parts = []
    if positive:
        explanation_parts.append("positive=" + ",".join(positive))
    if veto:
        explanation_parts.append("veto=" + ",".join(veto))
    explanation_parts.append(f"method={method}")

    return {
        "provider": "ESKLP",
        "provider_concept_id": concept["provider_concept_id"],
        "trade_name": trade,
        "inn": inn,
        "ingredients_detected": prov_ings,
        "strength": concept.get("strength"),
        "dosage_form": concept.get("form"),
        "route": concept.get("route"),
        "method": method,
        "positive_evidence": positive,
        "negative_evidence": veto,
        "ingredient_compatibility": ing_c,
        "salt_compatibility": "UNKNOWN",
        "route_compatibility": route_c,
        "form_compatibility": form_c,
        "strength_compatibility": str_c,
        "hard_conflict": hard or status == "HARD_CONFLICT",
        "status": status,
        "human_readable_explanation": "; ".join(explanation_parts),
        "source_file": concept.get("source_file"),
    }


def _gather_raw_candidates(
    profile: dict[str, Any],
    index: dict[str, Any],
    postings: dict[str, list[str]],
) -> list[tuple[str, str]]:
    """Return list of (concept_id, method) without marketing-token-only retrieval."""
    by_id = index.get("by_id") or {}
    by_trade = index.get("by_trade_name") or {}
    by_inn = index.get("by_inn") or {}
    found: dict[str, str] = {}

    src_ings = list(profile.get("active_ingredient_tokens") or [])
    if not src_ings:
        return []

    # 1) ingredient postings
    for ing in src_ings:
        for cid in postings.get(ing, [])[:120]:
            found.setdefault(cid, "ingredient_posting")

    # 2) identity trade/inn exact (marketing tokens stripped from query)
    guesses = []
    g = normalize_term(profile.get("guessed_trade_name") or "")
    if g:
        guesses.append(g)
    for tok in identity_tokens(profile.get("original_name") or ""):
        if len(tok) >= 4:
            guesses.append(tok)
    for q in guesses:
        for cid in by_trade.get(q, [])[:40]:
            found.setdefault(cid, "exact_trade_identity_tokens")
        for cid in by_inn.get(q, [])[:40]:
            found.setdefault(cid, "exact_inn_identity_tokens")

    # Drop unknown ids
    return [(cid, method) for cid, method in found.items() if cid in by_id]


def match_profile(
    profile: dict[str, Any],
    index: dict[str, Any],
    postings: dict[str, list[str]],
    *,
    rejected: set[tuple[str, str]],
    snapshot_hash: str,
) -> dict[str, Any]:
    mid = str(profile["source_medicine_id"])
    by_id = index.get("by_id") or {}
    src_ings = list(profile.get("active_ingredient_tokens") or [])

    base = {
        "version": VERSION,
        "source_medicine_id": mid,
        "original_name": profile.get("original_name"),
        "candidate_class": profile.get("candidate_class"),
        "active_ingredient_tokens": src_ings,
        "route_hint": profile.get("route_hint"),
        "provider": "ESKLP",
        "provider_snapshot_hash": snapshot_hash,
        "episode_coverage": profile.get("episode_coverage") or {},
    }

    if profile.get("candidate_class") == "INSUFFICIENT_SEMANTIC_DATA" or not src_ings:
        return {
            **base,
            "final_mapping_status": "INSUFFICIENT_SOURCE_DATA",
            "n_candidates": 0,
            "candidates": [],
            "routing": "insufficient_ingredient_evidence",
            "human_readable_explanation": (
                "No active-ingredient evidence — cannot create EXACT or SUPPORTED_TRANSFORM"
            ),
        }

    raw = _gather_raw_candidates(profile, index, postings)
    scored: list[dict[str, Any]] = []
    for cid, method in raw:
        if (mid, cid) in rejected:
            continue
        concept = by_id.get(cid)
        if not concept:
            continue
        ev = _candidate_evidence(profile, concept, method=method)
        if ev["hard_conflict"]:
            continue  # never propose hard conflicts as compatible candidates
        # Require ingredient compatibility at least PARTIAL/COMPATIBLE
        if ev["ingredient_compatibility"] not in {"COMPATIBLE", "PARTIAL"}:
            continue
        scored.append(ev)

    # Rank: COMPATIBLE ingredients first, then form, route, strength, trade
    def rank_key(c: dict[str, Any]) -> tuple:
        return (
            0 if c["ingredient_compatibility"] == "COMPATIBLE" else 1,
            0 if c["form_compatibility"] == "COMPATIBLE" else 1,
            0 if c["route_compatibility"] == "COMPATIBLE" else 1,
            0 if c["strength_compatibility"] == "COMPATIBLE" else 1,
            0 if "trade_name_overlap" in c["positive_evidence"] else 1,
            c["provider_concept_id"],
        )

    scored.sort(key=rank_key)
    # Dedup keep best
    scored = scored[:15]

    routing = "ESKLP"
    status = "NO_MATCH"
    if scored:
        top = scored[0]
        fully = (
            top["ingredient_compatibility"] == "COMPATIBLE"
            and top["form_compatibility"] in {"COMPATIBLE", "UNKNOWN"}
            and top["route_compatibility"] in {"COMPATIBLE", "UNKNOWN"}
            and top["strength_compatibility"] in {"COMPATIBLE", "UNKNOWN"}
            and "route_incompatible" not in top["negative_evidence"]
        )
        if len(scored) == 1 and fully and top["ingredient_compatibility"] == "COMPATIBLE":
            # Still do not auto-elevate to EXACT in v0.1.2 authoritative sense —
            # mark SUPPORTED_TRANSFORM only when form+strength also COMPATIBLE
            if (
                top["form_compatibility"] == "COMPATIBLE"
                and top["strength_compatibility"] == "COMPATIBLE"
            ):
                status = "SUPPORTED_TRANSFORM"
            else:
                status = "AMBIGUOUS"
        else:
            status = "AMBIGUOUS"
    else:
        if profile.get("candidate_class") == "DIETARY_SUPPLEMENT_CANDIDATE":
            status = "SUPPLEMENT_REFERENCE_REQUIRED"
            routing = "SUPPLEMENT_REFERENCE_REQUIRED"
        else:
            status = "PROVIDER_GAP" if src_ings else "NO_MATCH"
            routing = "PROVIDER_GAP" if src_ings else "NO_MATCH"

    top = scored[0] if scored else None
    return {
        **base,
        "final_mapping_status": status,
        "n_candidates": len(scored),
        "candidates": scored,
        "provider_concept_id": (top or {}).get("provider_concept_id"),
        "routing": routing,
        "positive_evidence": (top or {}).get("positive_evidence") or [],
        "negative_evidence": (top or {}).get("negative_evidence") or [],
        "human_readable_explanation": (top or {}).get("human_readable_explanation")
        or base.get("human_readable_explanation")
        or status,
        # Never auto-write HUMAN_ACCEPTED
        "authoritative_human_accepted": False,
    }


def run_matcher(
    root: Path,
    profiles: list[dict[str, Any]],
    *,
    snapshot_hash: str,
) -> dict[str, Any]:
    index = load_esklp_index(root)
    if not index:
        raise FileNotFoundError("esklp_index_missing")
    rejected = _decision_log_pairs(root)
    postings = build_ingredient_postings(index)

    mappings = [
        match_profile(
            p,
            index,
            postings,
            rejected=rejected,
            snapshot_hash=snapshot_hash,
        )
        for p in profiles
    ]

    counts = Counter(m["final_mapping_status"] for m in mappings)
    class_counts = Counter(m.get("candidate_class") for m in mappings)
    routing_counts = Counter(m.get("routing") for m in mappings)
    hard_conflict_skips = sum(
        1
        for m in mappings
        if m["final_mapping_status"]
        in {"NO_MATCH", "PROVIDER_GAP", "SUPPLEMENT_REFERENCE_REQUIRED", "INSUFFICIENT_SOURCE_DATA"}
    )

    out_dir = root / RUNTIME_DIR / "registry"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "semantic-mapping.private.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for m in mappings:
            fh.write(json.dumps(m, ensure_ascii=False, default=str) + "\n")

    return {
        "version": VERSION,
        "n_mappings": len(mappings),
        "status_counts": dict(counts),
        "candidate_class_counts": dict(class_counts),
        "routing_counts": dict(routing_counts),
        "n_rejected_pairs_excluded": len(rejected),
        "n_with_compatible_candidates": sum(1 for m in mappings if m["n_candidates"] > 0),
        "hard_conflict_or_gap_count": hard_conflict_skips,
        "mapping_path": str(path.relative_to(root)),
        "mappings": mappings,
        "index_n_concepts": index.get("n_concepts"),
        "snapshot_hash": snapshot_hash,
        "expected_snapshot_hash": EXPECTED_SNAPSHOT_SHA256,
    }
