"""Private diagnostic artifacts for ESKLP index + mapping (never in public ZIP)."""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.esklp_ingest import normalize_term
from human_simulator.medication_reference_v011.mapping import (
    load_source_records,
    prioritize_queue,
    search_steps,
)
from human_simulator.medication_reference_v011.policy import RUNTIME_DIR, TOP_N_REVIEW, VERSION

_RE_STRENGTH = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:мг|mg|мкг|mcg|г|g|мл|ml|%|МЕ|IU)\b",
    re.IGNORECASE,
)
_RE_FORM = re.compile(
    r"\b(таблетк\w*|капсул\w*|сироп\w*|мазь|крем|гель|спрей|раствор\w*|порошок\w*|капли|суспенз\w*)\b",
    re.IGNORECASE,
)


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def source_input_aggregates(records: list[dict[str, Any]]) -> dict[str, Any]:
    nonempty_name = sum(1 for r in records if str(r.get("original_name") or "").strip())
    nonempty_desc = sum(1 for r in records if str(r.get("original_description") or "").strip())
    norms = {
        (r.get("normalized_source_name") or normalize_term(r.get("original_name") or "")).strip()
        for r in records
    }
    norms.discard("")
    with_strength = sum(
        1 for r in records if _RE_STRENGTH.search(str(r.get("original_name") or ""))
    )
    with_form = sum(1 for r in records if _RE_FORM.search(str(r.get("original_name") or "")))
    cyr = lat = mixed = other = 0
    for r in records:
        s = str(r.get("original_name") or "")
        has_c = bool(re.search(r"[А-Яа-яЁё]", s))
        has_l = bool(re.search(r"[A-Za-z]", s))
        if has_c and has_l:
            mixed += 1
        elif has_c:
            cyr += 1
        elif has_l:
            lat += 1
        else:
            other += 1
    names = [str(r.get("original_name") or "").strip() for r in records]
    dup_names = len(names) - len(set(names))
    empty_or_id_only = sum(
        1
        for n in names
        if (not n)
        or n.isdigit()
        or re.fullmatch(r"[a-f0-9]{16,64}", n)
    )
    return {
        "records_loaded": len(records),
        "nonempty_original_name": nonempty_name,
        "nonempty_original_description": nonempty_desc,
        "unique_normalized_names": len(norms),
        "names_containing_strength": with_strength,
        "names_containing_dosage_form": with_form,
        "script_counts": {"cyrillic": cyr, "latin": lat, "mixed": mixed, "other": other},
        "duplicate_names": dup_names,
        "empty_or_identifier_only_records": empty_or_id_only,
        "mapper_uses_real_names": nonempty_name == len(records) and empty_or_id_only == 0,
    }


def build_private_diagnostics(
    root: Path,
    *,
    esklp: dict[str, Any],
    coverage: dict[str, dict[str, Any]],
    mappings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    diag_dir = root / RUNTIME_DIR / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    archive = {
        "snapshot_sha256": esklp.get("snapshot_sha256"),
        "ESKLP_PROVIDER_STATUS": esklp.get("ESKLP_PROVIDER_STATUS"),
        "stats": esklp.get("stats") or (esklp.get("manifest") or {}).get("stats"),
        "members_meta": (esklp.get("manifest") or {}).get("members_meta"),
        "file_profiles_sanitized": (esklp.get("manifest") or {}).get("file_profiles_sanitized"),
        "n_unique_searchable_terms": esklp.get("n_unique_searchable_terms"),
        "n_concepts": esklp.get("n_concepts"),
    }
    _write(diag_dir / "esklp-archive-and-index.json", archive)

    records = load_source_records(root)
    src_agg = source_input_aggregates(records)
    _write(diag_dir / "source-medication-aggregates.json", src_agg)

    queue = prioritize_queue(records, coverage)
    top20 = queue[:TOP_N_REVIEW]
    top20_private = []
    for r in top20:
        mid = str(r["source_medicine_id"])
        cov = coverage.get(mid) or {}
        name = r.get("original_name") or ""
        top20_private.append(
            {
                "source_medicine_id": mid,
                "original_name": name,
                "original_description": r.get("original_description"),
                "normalized_name": r.get("normalized_source_name") or normalize_term(name),
                "strength_tokens": [m.group(0) for m in _RE_STRENGTH.finditer(name)],
                "form_tokens": [m.group(0) for m in _RE_FORM.finditer(name)],
                "n_episodes": int(cov.get("n_episodes") or 0),
                "n_subjects": int(cov.get("n_subjects") or 0),
            }
        )
    _write(diag_dir / "top20-source-private.json", {"version": VERSION, "rows": top20_private})

    # Search-step aggregates (public-safe) + private per-medicine candidates
    index = esklp.get("index")
    step_public: dict[str, Any] = {}
    private_searches: list[dict[str, Any]] = []
    if index and int(index.get("n_unique_searchable_terms") or 0) > 0:
        step_names = [
            "exact_raw_normalized_name",
            "exact_cleaned_trade_product",
            "exact_inn_ingredient",
            "name_without_manufacturer",
            "name_without_strength_form_suffix",
            "unicode_normalization",
            "yo_to_e",
            "punctuation_quote_removal",
            "cyrillic_latin_normalization",
            "token_based_retrieval",
            "conservative_fuzzy_retrieval",
        ]
        for step in step_names:
            hits_ge1 = 0
            counts: list[int] = []
            exact_n = fuzzy_n = amb_n = none_n = 0
            for r in top20:
                name = r.get("original_name") or ""
                norm = r.get("normalized_source_name") or normalize_term(name)
                steps = search_steps(raw_name=name, norm_name=norm, index=index)
                cands = steps.get(step) or []
                n = len(cands)
                counts.append(n)
                if n >= 1:
                    hits_ge1 += 1
                if n == 0:
                    none_n += 1
                elif n == 1:
                    if "FUZZY" in (cands[0].get("method") or "") or "TOKEN" in (
                        cands[0].get("method") or ""
                    ):
                        fuzzy_n += 1
                    else:
                        exact_n += 1
                else:
                    amb_n += 1
                if step == "exact_cleaned_trade_product":
                    private_searches.append(
                        {
                            "source_medicine_id": str(r["source_medicine_id"]),
                            "step_results": {
                                k: [
                                    {
                                        "provider_concept_id": c.get("provider_concept_id"),
                                        "method": c.get("method"),
                                        "score": c.get("score"),
                                        "matched_fields": c.get("matched_fields"),
                                        "trade_name": c.get("trade_name"),
                                        "inn": c.get("inn"),
                                    }
                                    for c in (v or [])[:5]
                                ]
                                for k, v in steps.items()
                            },
                        }
                    )
            step_public[step] = {
                "n_source_with_ge1_result": hits_ge1,
                "median_candidate_count": statistics.median(counts) if counts else 0,
                "exact_count": exact_n,
                "fuzzy_count": fuzzy_n,
                "ambiguous_count": amb_n,
                "no_match_count": none_n,
            }
        _write(diag_dir / "top20-search-steps-public.json", step_public)
        _write(diag_dir / "top20-search-steps-private.json", {"rows": private_searches})

    mapping_summary = None
    if mappings is not None:
        mapping_summary = {
            "n": len(mappings),
            "by_status": {},
            "with_candidates": sum(1 for m in mappings if int(m.get("n_candidates") or 0) > 0),
        }
        for m in mappings:
            st = m["drug_concept_status"]
            mapping_summary["by_status"][st] = mapping_summary["by_status"].get(st, 0) + 1
        _write(diag_dir / "mapping-summary.json", mapping_summary)

    return {
        "private_diagnostics_dir": str(diag_dir.relative_to(root)),
        "archive": {
            "snapshot_sha256": archive.get("snapshot_sha256"),
            "n_concepts": archive.get("n_concepts"),
            "n_unique_searchable_terms": archive.get("n_unique_searchable_terms"),
            "stats": archive.get("stats"),
        },
        "source_aggregates": src_agg,
        "search_step_public": step_public,
        "mapping_summary": mapping_summary,
        "in_public_zip": False,
    }
