"""Rebuild mapping universe with live A/B semantic profiles (no invented fields)."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.policy import (
    ACCEPTED_GS011_ARTIFACT_DIR,
    ACCEPTED_PRIVACY_XS_ARTIFACT_DIR,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)

# Same candidate generation as privacy stage (lineage). Catalog corrections applied in classify.
_KNOWN_CANDIDATES: dict[str, list[dict[str, Any]]] = {
    "т3св.": [{"raw_code": "53", "evidence": "prior_unified_t3_stratum"}],
    "т3св": [{"raw_code": "53", "evidence": "prior_unified_t3_stratum"}],
    "т4св.": [{"raw_code": "54", "evidence": "catalog_code_hypothesis"}],
    "т4св": [{"raw_code": "54", "evidence": "catalog_code_hypothesis"}],
    "ттг": [
        {"raw_code": "55", "evidence": "prior_privacy_hypothesis_lineage"},
        {"raw_code": "1", "evidence": "prior_privacy_hypothesis_lineage"},
    ],
}


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _norm(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    return re.sub(r"[\s_\-./]+", "", t)


def load_prior_lineage_public(root: Path) -> list[dict[str, Any]]:
    harm = json.loads(
        (
            Path(root)
            / ACCEPTED_PRIVACY_XS_ARTIFACT_DIR
            / "cross-source-outcome-harmonization.json"
        ).read_text(encoding="utf-8")
    )
    return list(harm.get("mappings_public") or [])


def load_a_providers(root: Path) -> list[dict[str, Any]]:
    reg = json.loads(
        (
            Path(root) / ACCEPTED_GS011_ARTIFACT_DIR / "global-provider-registry.json"
        ).read_text(encoding="utf-8")
    )
    return list(reg.get("providers") or [])


def load_b_inventory_catalog(root: Path) -> list[dict[str, Any]]:
    inv = json.loads(
        (
            Path(root)
            / ACCEPTED_PRIVACY_XS_ARTIFACT_DIR
            / "source-b-longitudinal-inventory.json"
        ).read_text(encoding="utf-8")
    )
    return list(inv.get("outcome_unit_catalog_top500") or [])


def fetch_b_catalog_meta(conn_b: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with conn_b.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(code), ''), id::text) AS code,
                   name_ru, material, type, weight_id
            FROM quest_digital.analyses_catalog
            WHERE deleted_at IS NULL
            """
        )
        for code, name_ru, material, typ, weight_id in cur.fetchall():
            out[str(code)] = {
                "catalog_code": str(code),
                "name_ru": (name_ru or "")[:200] or None,
                "material": (str(material).strip() if material is not None else None) or None,
                "material_empty": not (material and str(material).strip()),
                "type": typ,
                "weight_id": weight_id,
                "method_assay": None,
                "method_assay_empty": True,
            }
    return out


def estimate_strict_pairs(
    conn_canonical: Any, *, raw_code: str, unit: str
) -> dict[str, Any]:
    from datetime import datetime, timezone

    def _parse(ts: Any) -> datetime | None:
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return None

    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT s.subject_id::text, o.observed_at, oc.component_id::text
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND COALESCE(NULLIF(TRIM(oc.raw_code), ''), NULLIF(TRIM(o.raw_code), ''), '∅') = %s
              AND COALESCE(NULLIF(TRIM(oc.raw_unit), ''), NULLIF(TRIM(o.raw_unit), ''), '') = %s
              AND oc.numeric_value IS NOT NULL AND o.observed_at IS NOT NULL
            ORDER BY s.subject_id, o.observed_at, oc.component_id
            """,
            (SOURCE_B_SYSTEM_ID, raw_code, unit),
        )
        rows = cur.fetchall()

    by: dict[str, list] = defaultdict(list)
    for sid, ts, cid in rows:
        t = _parse(ts)
        if t:
            by[str(sid)].append((t, str(cid)))

    n_pairs = 0
    n_subj = 0
    for series in by.values():
        series.sort(key=lambda x: (x[0].isoformat(), x[1]))
        collapsed = []
        i = 0
        while i < len(series):
            j = i + 1
            while j < len(series) and series[j][0] == series[i][0]:
                j += 1
            collapsed.append(series[i][0])
            i = j
        if len(collapsed) < 2:
            continue
        n_subj += 1
        for k in range(len(collapsed) - 1):
            if (collapsed[k + 1] - collapsed[k]).total_seconds() > 0:
                n_pairs += 1
    return {"n_subjects_with_pairs": n_subj, "n_strict_consecutive_pairs": n_pairs}


def _enrich_b_from_inventory(
    *,
    code: str,
    preferred_unit: str,
    catalog_rows: list[dict[str, Any]],
    catalog_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    by_code = [r for r in catalog_rows if str(r.get("raw_code")) == code]
    b_row = next((r for r in by_code if str(r.get("unit") or "") == preferred_unit), None)
    if b_row is None and by_code:
        b_row = max(by_code, key=lambda r: int(r.get("n_subjects") or 0))
    unit = str((b_row or {}).get("unit") or preferred_unit)
    cat = catalog_meta.get(code) or {
        "name_ru": None,
        "material": None,
        "material_empty": True,
        "method_assay": None,
        "method_assay_empty": True,
    }
    return {
        "system": SOURCE_B_SYSTEM_ID,
        "raw_code": code,
        "unit": unit,
        "n_components": int((b_row or {}).get("n_components") or 0),
        "n_numeric": int((b_row or {}).get("n_numeric") or 0),
        "n_non_numeric_with_text": max(
            0,
            int((b_row or {}).get("n_components") or 0)
            - int((b_row or {}).get("n_numeric") or 0),
        ),
        "n_subjects": int((b_row or {}).get("n_subjects") or 0),
        "n_dated_numeric": int((b_row or {}).get("n_numeric") or 0),
        "n_subjects_with_ge2": None,
        "n_with_reference_range": 0,
        "unit_distribution_for_code": [
            {"unit": r.get("unit"), "n_components": r.get("n_components")} for r in by_code
        ],
        "specimen_material": cat.get("material"),
        "specimen_material_empty": cat.get("material_empty", True),
        "method_assay": cat.get("method_assay"),
        "method_assay_empty": cat.get("method_assay_empty", True),
        "catalog": {
            "name_ru": cat.get("name_ru"),
            "material": cat.get("material"),
            "material_empty": cat.get("material_empty", True),
            "method_assay": cat.get("method_assay"),
            "method_assay_empty": cat.get("method_assay_empty", True),
        },
        "invented_fields": False,
        "n_subjects_with_pairs": 0,
        "n_strict_consecutive_pairs": 0,
    }


def rebuild_mapping_universe(
    *,
    root: Path,
    conn_canonical: Any | None = None,
    conn_b: Any | None = None,
    pair_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Rebuild the 98-stratum universe from frozen A providers + prior candidate rules."""
    providers = load_a_providers(root)
    prior_public = load_prior_lineage_public(root)
    prior_lookup = {
        (m.get("a_outcome"), m.get("a_unit"), m.get("b_raw_code"), m.get("b_unit")): m
        for m in prior_public
    }
    catalog_rows = load_b_inventory_catalog(root)
    catalog_meta = fetch_b_catalog_meta(conn_b) if conn_b is not None else {}
    if not catalog_meta:
        # Honest defaults when catalog DB unavailable: material/method empty
        for code in {c["raw_code"] for cands in _KNOWN_CANDIDATES.values() for c in cands}:
            catalog_meta[code] = {
                "name_ru": None,
                "material": None,
                "material_empty": True,
                "method_assay": None,
                "method_assay_empty": True,
            }
        # Known catalog names from prior evidence (attachment only; not auto-accept)
        catalog_meta["53"] = {
            **catalog_meta.get("53", {}),
            "name_ru": "Трийодтиронин свободный (Т3 свободный)",
            "material_empty": True,
            "method_assay_empty": True,
        }
        catalog_meta["55"] = {
            **catalog_meta.get("55", {}),
            "name_ru": "Тироксин свободный (Т4 свободный)",
            "material_empty": True,
            "method_assay_empty": True,
        }
        catalog_meta["56"] = {
            **catalog_meta.get("56", {}),
            "name_ru": "Тиреотропный гормон",
            "material_empty": True,
            "method_assay_empty": True,
        }

    pair_codes = pair_codes or {"53", "55", "56", "54", "1"}
    pair_cache: dict[tuple[str, str], dict[str, Any]] = {}

    strata: list[dict[str, Any]] = []
    for p in providers:
        outcome = str(p.get("outcome") or "")
        unit = str(p.get("unit") or "")
        a_prof = {
            "system": SOURCE_A_SYSTEM_ID,
            "outcome": outcome,
            "unit": unit,
            "grain_id": p.get("grain_id"),
            "active_provider": p.get("active_provider"),
            "model_identity_hash": p.get("model_identity_hash"),
            "model_file_hash": p.get("model_file_hash"),
            "specimen_material": None,
            "specimen_material_empty": True,
            "method_assay": None,
            "method_assay_empty": True,
            "normalized_label": _norm(outcome),
            "provenance": "global_provider_registry_v0.1.1",
        }
        cands = _KNOWN_CANDIDATES.get(_norm(outcome)) or []
        if not cands:
            mid = _hash({"a": outcome, "au": unit, "b": None, "bu": None})
            strata.append(
                {
                    "mapping_id": mid,
                    "source_a": a_prof,
                    "source_b": None,
                    "prior_lineage_status": "UNKNOWN",
                    "has_b_candidate": False,
                    "candidate_evidence": None,
                    "coverage_rank_key": (0, 0, 0),
                }
            )
            continue
        for cand in cands:
            code = str(cand["raw_code"])
            b_prof = _enrich_b_from_inventory(
                code=code,
                preferred_unit=unit,
                catalog_rows=catalog_rows,
                catalog_meta=catalog_meta,
            )
            b_unit = str(b_prof["unit"])
            if conn_canonical is not None and code in pair_codes:
                key = (code, b_unit)
                if key not in pair_cache:
                    pair_cache[key] = estimate_strict_pairs(
                        conn_canonical, raw_code=code, unit=b_unit
                    )
                b_prof.update(pair_cache[key])

            prior_m = prior_lookup.get((outcome, unit, code, b_unit)) or prior_lookup.get(
                (outcome, unit, code, unit)
            )
            # Fall back: any prior public row matching outcome+code
            if prior_m is None:
                prior_m = next(
                    (
                        m
                        for m in prior_public
                        if m.get("a_outcome") == outcome
                        and m.get("b_raw_code") == code
                        and m.get("a_unit") == unit
                    ),
                    None,
                )
            mid = _hash({"a": outcome, "au": unit, "b": code, "bu": b_unit})
            # Preserve published lineage only; unpublished candidate rows stay UNKNOWN
            # (matches prior pin UNKNOWN 90 / HYPOTHESIS 8).
            prior_status = (prior_m or {}).get("mapping_status") or "UNKNOWN"
            strata.append(
                {
                    "mapping_id": mid,
                    "source_a": a_prof,
                    "source_b": b_prof,
                    "prior_lineage_status": prior_status,
                    "prior_evidence_hash": (prior_m or {}).get("evidence_hash"),
                    "has_b_candidate": True,
                    "candidate_evidence": cand.get("evidence"),
                    "coverage_rank_key": (
                        int(b_prof.get("n_subjects_with_pairs") or 0),
                        int(b_prof.get("n_strict_consecutive_pairs") or 0),
                        int(b_prof.get("n_subjects") or 0),
                    ),
                }
            )

    n = len(strata)
    # Expected accounting: 95 providers → 98 rows (multi-candidate for ТТГ)
    accounting_ok = n == 98
    return {
        "version": VERSION,
        "MAPPING_UNIVERSE_ACCOUNTING_STATUS": "PASS" if accounting_ok else "FAIL",
        "n_source_a_providers": len(providers),
        "n_mapping_strata": n,
        "n_with_b_candidate": sum(1 for s in strata if s.get("has_b_candidate")),
        "n_without_b_candidate": sum(1 for s in strata if not s.get("has_b_candidate")),
        "prior_lineage_status_counts": {
            st: sum(1 for s in strata if s.get("prior_lineage_status") == st)
            for st in sorted({str(s.get("prior_lineage_status")) for s in strata})
        },
        "catalog_material_all_empty": all(
            (catalog_meta.get(c) or {}).get("material_empty", True) for c in catalog_meta
        )
        if catalog_meta
        else True,
        "n_catalog_meta_entries": len(catalog_meta),
        "pair_estimates_computed_for": sorted({f"{a}|{b}" for a, b in pair_cache}),
        "strata": strata,
        "universe_hash": _hash({"n": n, "ids": sorted(s["mapping_id"] for s in strata)}),
        "ok": accounting_ok,
    }
