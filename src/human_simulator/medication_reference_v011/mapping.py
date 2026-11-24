"""Map 487 source medications against ESKLP provider index with ranked candidates."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.esklp_ingest import normalize_term
from human_simulator.medication_reference_v011.policy import (
    ACCEPTED_STATUSES,
    EXPECTED_MEDICINE_IDS,
    PRIOR_CONCEPT_REGISTRY,
    RUNTIME_DIR,
    TOP20_EPISODE_COVERAGE_PIN,
    TOP_N_REVIEW,
    TOTAL_EPISODES_PIN,
    VERSION,
)

_RE_STRENGTH = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>мг|mg|мкг|mcg|г|g|мл|ml|%|МЕ|IU)\b",
    re.IGNORECASE,
)
_RE_FORM = re.compile(
    r"\b(таблетк\w*|капсул\w*|сироп\w*|мазь|крем|гель|спрей|раствор\w*|порошок\w*|капли|суспенз\w*|ампул\w*)\b",
    re.IGNORECASE,
)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_source_records(root: Path) -> list[dict[str, Any]]:
    """Load real Source Medication records (names/descriptions), not hashes."""
    path = root / PRIOR_CONCEPT_REGISTRY
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def prioritize_queue(
    records: list[dict[str, Any]],
    coverage: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple:
        mid = str(r["source_medicine_id"])
        cov = coverage.get(mid) or {}
        return (
            -int(cov.get("n_episodes") or 0),
            -int(cov.get("n_subjects") or 0),
            -int(cov.get("n_outcomes") or 0),
            int(mid) if str(mid).isdigit() else mid,
        )

    return sorted(records, key=key)


def strip_manufacturer_paren(name: str) -> str:
    # Remove trailing parenthetical brand lists: "МНН (Бренд1, Бренд2)"
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def strip_strength_form_suffix(name: str) -> str:
    t = _RE_STRENGTH.sub(" ", name)
    t = _RE_FORM.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    return t


def extract_brand_tokens(name: str) -> list[str]:
    tokens: list[str] = []
    m = re.search(r"\(([^)]+)\)", name)
    if m:
        for part in re.split(r"[,;/]", m.group(1)):
            t = part.strip()
            if t:
                tokens.append(t)
    head = strip_manufacturer_paren(name)
    head = strip_strength_form_suffix(head)
    if head:
        tokens.append(head)
    # first whitespace token
    first = head.split()[0] if head.split() else ""
    if first and len(first) >= 3:
        tokens.append(first)
    # dedupe preserve order
    seen = set()
    out = []
    for t in tokens:
        nt = normalize_term(t)
        if nt and nt not in seen:
            seen.add(nt)
            out.append(t)
    return out


def _candidate_payload(c: dict[str, Any], *, method: str, score: float) -> dict[str, Any]:
    return {
        "provider_concept_id": c["provider_concept_id"],
        "method": method,
        "score": score,
        "trade_name": c.get("trade_name"),
        "inn": c.get("inn"),
        "form": c.get("form"),
        "strength": c.get("strength"),
        "ingredients": c.get("ingredients") or [],
        "source_file": c.get("source_file"),
        "matched_fields": [
            k
            for k, v in (
                ("trade_name", c.get("normalized_trade")),
                ("inn", c.get("normalized_inn")),
                ("form", c.get("form")),
                ("strength", c.get("strength")),
            )
            if v
        ],
    }


def search_steps(
    *,
    raw_name: str,
    norm_name: str,
    index: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Run diagnostic/search steps; return candidates per step (deduped lists)."""
    by_id = index.get("by_id") or {}
    by_trade = index.get("by_trade_name") or {}
    by_inn = index.get("by_inn") or {}
    by_token = index.get("by_token") or {}

    cleaned = normalize_term(strip_manufacturer_paren(raw_name))
    no_sf = normalize_term(strip_strength_form_suffix(strip_manufacturer_paren(raw_name)))
    unicode_norm = normalize_term(unicodedata.normalize("NFKC", raw_name))
    yo_norm = normalize_term(raw_name.replace("ё", "е").replace("Ё", "Е"))
    punct_norm = normalize_term(re.sub(r"[\"'`«»“”,.;:!?()\[\]{}]", " ", raw_name))

    steps: dict[str, list[str]] = {
        "exact_raw_normalized_name": [norm_name],
        "exact_cleaned_trade_product": [cleaned, no_sf],
        "exact_inn_ingredient": [norm_name, cleaned, no_sf],
        "name_without_manufacturer": [cleaned],
        "name_without_strength_form_suffix": [no_sf],
        "unicode_normalization": [unicode_norm],
        "yo_to_e": [yo_norm],
        "punctuation_quote_removal": [punct_norm],
        "cyrillic_latin_normalization": [norm_name, cleaned],
        "token_based_retrieval": [],
        "conservative_fuzzy_retrieval": [],
    }

    # token queries
    tokens = [t for t in cleaned.split() if len(t) >= 3]
    steps["token_based_retrieval"] = tokens
    for tok in extract_brand_tokens(raw_name):
        nt = normalize_term(tok)
        if nt and nt not in tokens:
            steps["token_based_retrieval"].append(nt)

    out: dict[str, list[dict[str, Any]]] = {}
    for step, queries in steps.items():
        found: dict[str, dict[str, Any]] = {}
        for q in queries:
            if not q:
                continue
            if step in {
                "exact_raw_normalized_name",
                "exact_cleaned_trade_product",
                "name_without_manufacturer",
                "name_without_strength_form_suffix",
                "unicode_normalization",
                "yo_to_e",
                "punctuation_quote_removal",
                "cyrillic_latin_normalization",
            }:
                for cid in by_trade.get(q, []):
                    found[cid] = _candidate_payload(by_id[cid], method=f"{step}:trade", score=1.0)
                for cid in by_inn.get(q, []):
                    found.setdefault(
                        cid,
                        _candidate_payload(by_id[cid], method=f"{step}:inn", score=0.95),
                    )
            elif step == "exact_inn_ingredient":
                for cid in by_inn.get(q, []):
                    found[cid] = _candidate_payload(by_id[cid], method=f"{step}", score=1.0)
            elif step == "token_based_retrieval":
                for cid in by_token.get(q, [])[:50]:
                    found.setdefault(
                        cid,
                        _candidate_payload(by_id[cid], method="TOKEN", score=0.6),
                    )
            elif step == "conservative_fuzzy_retrieval":
                # substring containment on trade/inn keys (bounded)
                checked = 0
                for nt, ids in by_trade.items():
                    if checked > 5000:
                        break
                    checked += 1
                    if q and len(q) >= 4 and (q in nt or nt in q):
                        for cid in ids[:3]:
                            found.setdefault(
                                cid,
                                _candidate_payload(
                                    by_id[cid], method="FUZZY_SUBSTRING:trade", score=0.4
                                ),
                            )
                checked = 0
                for ni, ids in by_inn.items():
                    if checked > 5000:
                        break
                    checked += 1
                    if q and len(q) >= 4 and (q in ni or ni in q):
                        for cid in ids[:3]:
                            found.setdefault(
                                cid,
                                _candidate_payload(
                                    by_id[cid], method="FUZZY_SUBSTRING:inn", score=0.35
                                ),
                            )
        out[step] = list(found.values())
    return out


def _strength_compatible(src_tokens: list[dict[str, str]], prov_strength: str | None) -> str:
    if not src_tokens or not prov_strength:
        return "UNKNOWN"
    pv = normalize_term(prov_strength)
    if any(normalize_term(h["value"]) in pv for h in src_tokens):
        return "COMPATIBLE"
    return "CONFLICT"


def _form_compatible(src_forms: list[str], prov_form: str | None) -> str:
    if not src_forms or not prov_form:
        return "UNKNOWN"
    pf = normalize_term(prov_form)
    for f in src_forms:
        nf = normalize_term(f)
        if nf and (nf in pf or pf in nf):
            return "COMPATIBLE"
    return "CONFLICT"


def match_against_esklp(
    record: dict[str, Any],
    index: dict[str, Any],
    *,
    snapshot_hash: str,
) -> dict[str, Any]:
    mid = str(record["source_medicine_id"])
    name = record.get("original_name") or ""
    desc = record.get("original_description") or ""
    # Require real source strings
    if not str(name).strip():
        raise ValueError(f"source_medicine_missing_original_name:{mid}")
    if name.isdigit() or re.fullmatch(r"[a-f0-9]{16,64}", name.strip()):
        raise ValueError(f"source_medicine_looks_like_hash_or_id:{mid}")

    norm_name = record.get("normalized_source_name") or normalize_term(name)
    source_hash = record.get("source_text_hash") or _sha(f"{name}|{desc}")

    steps = search_steps(raw_name=name, norm_name=norm_name, index=index)
    by_id = index.get("by_id") or {}

    # Ranked merge
    ranked: dict[str, dict[str, Any]] = {}
    priority = [
        ("exact_cleaned_trade_product", 100),
        ("exact_raw_normalized_name", 98),
        ("exact_inn_ingredient", 95),
        ("name_without_manufacturer", 90),
        ("name_without_strength_form_suffix", 88),
        ("yo_to_e", 85),
        ("unicode_normalization", 84),
        ("punctuation_quote_removal", 83),
        ("cyrillic_latin_normalization", 82),
        ("token_based_retrieval", 60),
        ("conservative_fuzzy_retrieval", 40),
    ]
    for step, base in priority:
        for cand in steps.get(step) or []:
            cid = cand["provider_concept_id"]
            score = base + float(cand.get("score") or 0)
            prev = ranked.get(cid)
            if prev is None or score > prev["rank_score"]:
                ranked[cid] = {**cand, "rank_score": score, "primary_step": step}

    strength_hits = [
        {"value": m.group("value"), "unit": m.group("unit")}
        for m in _RE_STRENGTH.finditer(f"{name} {desc}")
    ]
    form_hits = [m.group(0) for m in _RE_FORM.finditer(f"{name} {desc}")]

    candidates = sorted(ranked.values(), key=lambda x: -x["rank_score"])[:15]

    # Annotate compatibility
    for cand in candidates:
        full = by_id.get(cand["provider_concept_id"]) or {}
        cand["strength_compat"] = _strength_compatible(strength_hits, full.get("strength"))
        cand["form_compat"] = _form_compatible(form_hits, full.get("form"))
        if cand["strength_compat"] == "CONFLICT" or cand["form_compat"] == "CONFLICT":
            cand["rank_score"] -= 30

    candidates.sort(key=lambda x: -x["rank_score"])

    status = "NO_MATCH"
    conflict_reasons: list[str] = []
    ambiguity_reasons: list[str] = []
    chosen = None
    transform = None

    exact = [
        c
        for c in candidates
        if c.get("primary_step")
        in {
            "exact_cleaned_trade_product",
            "exact_raw_normalized_name",
            "exact_inn_ingredient",
            "name_without_manufacturer",
            "name_without_strength_form_suffix",
            "yo_to_e",
            "unicode_normalization",
            "punctuation_quote_removal",
            "cyrillic_latin_normalization",
        }
        and "FUZZY" not in (c.get("method") or "")
        and "TOKEN" not in (c.get("method") or "")
    ]
    # Stricter exact: method must start with exact_* or name_without / yo / unicode / punct
    exact = [
        c
        for c in candidates
        if any(
            (c.get("method") or "").startswith(p)
            for p in (
                "exact_cleaned_trade_product",
                "exact_raw_normalized_name",
                "exact_inn_ingredient",
                "name_without_manufacturer",
                "name_without_strength_form_suffix",
                "yo_to_e",
                "unicode_normalization",
                "punctuation_quote_removal",
                "cyrillic_latin_normalization",
            )
        )
    ]

    fuzzy_only = [
        c
        for c in candidates
        if "FUZZY" in (c.get("method") or "") or "TOKEN" in (c.get("method") or "")
    ]

    if len(exact) == 1:
        chosen = exact[0]
        if chosen.get("strength_compat") == "CONFLICT" or chosen.get("form_compat") == "CONFLICT":
            status = "CONFLICT"
            if chosen.get("strength_compat") == "CONFLICT":
                conflict_reasons.append("strength_conflict")
            if chosen.get("form_compat") == "CONFLICT":
                conflict_reasons.append("form_conflict")
        else:
            status = "EXACT_PROVIDER_MATCH"
            transform = chosen.get("method")
            if len(chosen.get("ingredients") or []) > 1:
                transform = f"{transform}|MULTI_INGREDIENT"
    elif len(exact) > 1:
        status = "AMBIGUOUS"
        ambiguity_reasons.append(f"multiple_exact:{len(exact)}")
        chosen = exact[0]
    elif len(candidates) == 1 and fuzzy_only:
        status = "CANDIDATE"
        chosen = candidates[0]
        ambiguity_reasons.append("fuzzy_or_token_only")
    elif len(candidates) > 1:
        status = "AMBIGUOUS" if len(exact) != 1 else "CANDIDATE"
        if not exact:
            status = "AMBIGUOUS" if len(candidates) > 1 else "CANDIDATE"
            ambiguity_reasons.append(f"multiple_fuzzy_or_token:{len(candidates)}")
        chosen = candidates[0]
    else:
        status = "NO_MATCH"

    # Fuzzy never becomes EXACT
    if status == "EXACT_PROVIDER_MATCH" and chosen and (
        "FUZZY" in (chosen.get("method") or "") or "TOKEN" in (chosen.get("method") or "")
    ):
        status = "CANDIDATE"
        transform = None

    evidence_hash = _sha(
        json.dumps(
            {
                "snapshot": snapshot_hash,
                "candidates": [
                    {"id": c["provider_concept_id"], "method": c.get("method")}
                    for c in candidates[:10]
                ],
                "status": status,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
    )

    step_counts = {k: len(v) for k, v in steps.items()}

    return {
        "version": VERSION,
        "source_medicine_id": mid,
        "source_medication_hash": source_hash,
        "source_text_hash": source_hash,
        "original_name": name,
        "original_description": desc,
        "normalized_source_name": norm_name,
        "provider": "ESKLP",
        "provider_snapshot_hash": snapshot_hash,
        "drug_concept_status": status,
        "provider_concept_id": (chosen or {}).get("provider_concept_id"),
        "candidates": candidates[:10],
        "n_candidates": len(candidates),
        "transformation_method": transform,
        "conflict_reasons": conflict_reasons,
        "ambiguity_reasons": ambiguity_reasons,
        "strength_tokens_observed": strength_hits,
        "form_tokens_observed": form_hits,
        "provider_evidence_hash": evidence_hash,
        "ingredients": (chosen or {}).get("ingredients") or [],
        "product_name": (chosen or {}).get("trade_name"),
        "inn": (chosen or {}).get("inn"),
        "form": (chosen or {}).get("form"),
        "strength": (chosen or {}).get("strength"),
        "search_step_counts": step_counts,
        "appointment_is_not_administration": True,
        "ddd_not_individual_dose": True,
        "domain_review_required": status
        in {"CANDIDATE", "AMBIGUOUS", "CONFLICT"}
        and len(candidates) > 0,
        "uses_source_name_not_hash": True,
    }


def apply_human_decision(mapping: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    if not decision:
        return mapping
    d = decision.get("decision")
    if d == "HUMAN_ACCEPTED":
        return {
            **mapping,
            "drug_concept_status": "HUMAN_ACCEPTED",
            "provider": decision.get("provider"),
            "provider_concept_id": decision.get("provider_concept_id"),
            "provider_evidence_hash": decision.get("provider_evidence_hash"),
            "human_decision_hash": decision.get("entry_hash"),
            "domain_review_required": False,
        }
    if d == "HUMAN_REJECTED":
        return {
            **mapping,
            "drug_concept_status": "HUMAN_REJECTED",
            "human_decision_hash": decision.get("entry_hash"),
            "domain_review_required": False,
        }
    if d == "AMBIGUOUS":
        return {
            **mapping,
            "drug_concept_status": "AMBIGUOUS",
            "human_decision_hash": decision.get("entry_hash"),
            "domain_review_required": True,
        }
    return mapping


def run_esklp_mapping(
    root: Path,
    *,
    index: dict[str, Any],
    snapshot_hash: str,
    coverage: dict[str, dict[str, Any]],
    human_decisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    records = load_source_records(root)
    if len(records) != EXPECTED_MEDICINE_IDS:
        raise ValueError(f"expected_{EXPECTED_MEDICINE_IDS}_got_{len(records)}")
    queue = prioritize_queue(records, coverage)
    human_decisions = human_decisions or {}
    mappings: list[dict[str, Any]] = []
    for rec in queue:
        mid = str(rec["source_medicine_id"])
        cov = coverage.get(mid) or {}
        m = match_against_esklp(rec, index, snapshot_hash=snapshot_hash)
        m["episode_coverage"] = {
            "n_episodes": int(cov.get("n_episodes") or 0),
            "n_subjects": int(cov.get("n_subjects") or 0),
            "n_outcomes": int(cov.get("n_outcomes") or 0),
        }
        m = apply_human_decision(m, human_decisions.get(mid))
        mappings.append(m)

    by_status: dict[str, int] = {}
    for m in mappings:
        st = m["drug_concept_status"]
        by_status[st] = by_status.get(st, 0) + 1

    accepted = sum(1 for m in mappings if m["drug_concept_status"] in ACCEPTED_STATUSES)
    unresolved = EXPECTED_MEDICINE_IDS - accepted
    with_candidates = sum(1 for m in mappings if int(m.get("n_candidates") or 0) > 0)
    cand_eps = sum(
        int((m.get("episode_coverage") or {}).get("n_episodes") or 0)
        for m in mappings
        if int(m.get("n_candidates") or 0) > 0
    )
    cand_subj = sum(
        int((m.get("episode_coverage") or {}).get("n_subjects") or 0)
        for m in mappings
        if int(m.get("n_candidates") or 0) > 0
    )

    top20 = mappings[:TOP_N_REVIEW]
    top20_eps = sum(int((m.get("episode_coverage") or {}).get("n_episodes") or 0) for m in top20)
    top20_with_cand = sum(1 for m in top20 if int(m.get("n_candidates") or 0) > 0)
    top20_cand_eps = sum(
        int((m.get("episode_coverage") or {}).get("n_episodes") or 0)
        for m in top20
        if int(m.get("n_candidates") or 0) > 0
    )

    priv_dir = root / RUNTIME_DIR / "registry"
    priv_dir.mkdir(parents=True, exist_ok=True)
    priv_path = priv_dir / "medication-reference-mapping.private.jsonl"
    with priv_path.open("w", encoding="utf-8") as fh:
        for m in mappings:
            fh.write(json.dumps(m, ensure_ascii=False, sort_keys=True) + "\n")

    sanitized = []
    for m in mappings:
        sanitized.append(
            {
                "source_medicine_id_hash": _sha(str(m["source_medicine_id"]))[:16],
                "source_medication_hash": m["source_medication_hash"],
                "drug_concept_status": m["drug_concept_status"],
                "provider": m.get("provider"),
                "provider_snapshot_hash": m.get("provider_snapshot_hash"),
                "provider_concept_id": m.get("provider_concept_id"),
                "n_candidates": m.get("n_candidates"),
                "transformation_method": m.get("transformation_method"),
                "conflict_reasons": m.get("conflict_reasons"),
                "ambiguity_reasons": m.get("ambiguity_reasons"),
                "provider_evidence_hash": m.get("provider_evidence_hash"),
                "n_episodes": (m.get("episode_coverage") or {}).get("n_episodes"),
                "n_subjects": (m.get("episode_coverage") or {}).get("n_subjects"),
                "domain_review_required": m.get("domain_review_required"),
            }
        )

    n_exact = int(by_status.get("EXACT_PROVIDER_MATCH") or 0)
    n_cand = int(by_status.get("CANDIDATE") or 0)
    n_amb = int(by_status.get("AMBIGUOUS") or 0)
    reviewable = n_exact + n_cand + n_amb + int(by_status.get("CONFLICT") or 0)

    accounting = {
        "total_source_medicines": len(mappings),
        "expected_source_medicines": EXPECTED_MEDICINE_IDS,
        "matches_expected": len(mappings) == EXPECTED_MEDICINE_IDS,
        "by_status": by_status,
        "DRUG_CONCEPT_ACCEPTED_COUNT": accepted,
        "DRUG_CONCEPT_UNRESOLVED_COUNT": unresolved,
        "unaccounted": 0,
        "source_records_with_ge1_candidate": with_candidates,
        "candidate_episode_coverage": cand_eps,
        "candidate_subject_coverage_sum": cand_subj,
        "top20_episode_coverage": top20_eps,
        "top20_episode_coverage_pin": TOP20_EPISODE_COVERAGE_PIN,
        "top20_coverage_reconciles_pin": top20_eps == TOP20_EPISODE_COVERAGE_PIN,
        "top20_with_ge1_candidate": top20_with_cand,
        "top20_candidate_episode_coverage": top20_cand_eps,
        "total_episodes_pin": TOTAL_EPISODES_PIN,
        "reviewable_mapping_count": reviewable,
    }
    return {
        "mappings": mappings,
        "sanitized": sanitized,
        "accounting": accounting,
        "private_registry": str(priv_path.relative_to(root)),
    }
