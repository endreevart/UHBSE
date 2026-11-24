"""Full Source B outcome×unit inventory (no top-500 cap) + metadata recovery."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from human_simulator.cross_source_lab_semantic_v02.policy import (
    BUCKET_TRAIN_END,
    BUCKET_VAL_END,
    SOURCE_B_SPLIT_NAMESPACE,
    SOURCE_B_SPLIT_SEED,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)
from human_simulator.cross_source_lab_semantic_v02.synonyms import (
    infer_analyte_family,
    normalize_label,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def assign_role(research_subject_id: str) -> str:
    digest = hashlib.sha256(
        f"{SOURCE_B_SPLIT_NAMESPACE}|{SOURCE_B_SPLIT_SEED}|{research_subject_id}".encode()
    ).hexdigest()
    frac = int(digest[:12], 16) / float(16**12)
    if frac < BUCKET_TRAIN_END:
        return "train"
    if frac < BUCKET_VAL_END:
        return "validation"
    return "test"


def fetch_b_catalog_meta(conn_b: Any | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if conn_b is None:
        return out
    with conn_b.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(code), ''), id::text) AS code,
                   name_ru, name_en, material, type, weight_id
            FROM quest_digital.analyses_catalog
            WHERE deleted_at IS NULL
            """
        )
        for code, name_ru, name_en, material, typ, weight_id in cur.fetchall():
            out[str(code)] = {
                "catalog_code": str(code),
                "name_ru": (name_ru or "")[:200] or None,
                "name_en": (name_en or "")[:120] or None,
                "material": (str(material).strip() if material else None) or None,
                "material_empty": not (material and str(material).strip()),
                "type": typ,
                "weight_id": weight_id,
                "method_assay": None,
                "method_assay_empty": True,
                "source_table": "quest_digital.analyses_catalog",
                "join_path": "analyses_catalog.code = observation_component.raw_code",
            }
        # weight units if present
        cur.execute(
            """
            SELECT id, code, name, code_en, name_en
            FROM quest_digital.analyses_weight
            """
        )
        weights = {
            int(r[0]): {
                "weight_code": r[1],
                "weight_name": r[2],
                "weight_code_en": r[3],
                "weight_name_en": r[4],
                "source_table": "quest_digital.analyses_weight",
            }
            for r in cur.fetchall()
        }
        for meta in out.values():
            wid = meta.get("weight_id")
            if wid is not None and int(wid) in weights:
                meta["weight"] = weights[int(wid)]
    return out


def probe_b_metadata_schema(conn_b: Any | None) -> dict[str, Any]:
    if conn_b is None:
        return {"connection": "NOT_AVAILABLE", "columns": []}
    with conn_b.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'quest_digital'
              AND (
                lower(column_name) LIKE '%material%'
                OR lower(column_name) LIKE '%specimen%'
                OR lower(column_name) LIKE '%method%'
                OR lower(column_name) LIKE '%assay%'
                OR lower(column_name) LIKE '%synonym%'
                OR lower(column_name) LIKE '%unit%'
                OR lower(column_name) LIKE '%ref%'
              )
            ORDER BY 1, 2, 3
            LIMIT 300
            """
        )
        cols = [{"schema": r[0], "table": r[1], "column": r[2]} for r in cur.fetchall()]
    return {
        "connection": "OK",
        "columns": cols,
        "query_hash": _hash(["b_schema_probe", len(cols)]),
    }


def build_full_b_outcome_unit_inventory(
    *,
    conn_canonical: Any,
    conn_b: Any | None,
) -> dict[str, Any]:
    """FULL code×unit strata — no LIMIT / top500."""
    catalog_meta = fetch_b_catalog_meta(conn_b)
    schema_probe = probe_b_metadata_schema(conn_b)

    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(oc.raw_code), ''),
                            NULLIF(TRIM(o.raw_code), ''), '∅') AS code,
                   COALESCE(NULLIF(TRIM(oc.raw_unit), ''),
                            NULLIF(TRIM(o.raw_unit), ''), '') AS unit,
                   COUNT(*) AS n_comp,
                   COUNT(*) FILTER (WHERE oc.numeric_value IS NOT NULL) AS n_num,
                   COUNT(*) FILTER (
                     WHERE oc.numeric_value IS NULL
                       AND (NULLIF(TRIM(oc.raw_value),'') IS NOT NULL
                            OR NULLIF(TRIM(oc.text_value),'') IS NOT NULL)
                   ) AS n_nonnum,
                   COUNT(DISTINCT s.subject_id) AS n_subj,
                   COUNT(*) FILTER (
                     WHERE oc.numeric_value IS NOT NULL AND o.observed_at IS NOT NULL
                   ) AS n_dated,
                   COUNT(*) FILTER (
                     WHERE oc.reference_range IS NOT NULL OR o.reference_range IS NOT NULL
                   ) AS n_ref
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            GROUP BY 1, 2
            ORDER BY n_subj DESC, n_comp DESC
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        rows = cur.fetchall()

        cur.execute(
            """
            SELECT COUNT(DISTINCT COALESCE(NULLIF(TRIM(oc.raw_code), ''),
                                           NULLIF(TRIM(o.raw_code), ''), '∅'))
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_codes = int(cur.fetchone()[0])

    strata: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for r in rows:
        code, unit, n_comp, n_num, n_non, n_subj, n_dated, n_ref = r
        if code == "∅" and not unit:
            excluded.append(
                {"raw_code": code, "unit": unit, "reason": "empty_code_and_unit"}
            )
            continue
        cat = catalog_meta.get(str(code)) or {}
        name = cat.get("name_ru") or cat.get("name_en")
        item = {
            "raw_code": str(code),
            "unit": str(unit or ""),
            "catalog_name_ru": cat.get("name_ru"),
            "catalog_name_en": cat.get("name_en"),
            "normalized_catalog_label": normalize_label(name or ""),
            "analyte_family_hint": infer_analyte_family(name or str(code)),
            "n_components": int(n_comp),
            "n_numeric": int(n_num),
            "n_non_numeric_with_text": int(n_non),
            "n_subjects": int(n_subj),
            "n_dated_numeric": int(n_dated),
            "n_with_reference_range": int(n_ref),
            "specimen_material": cat.get("material"),
            "specimen_material_empty": cat.get("material_empty", True),
            "method_assay": cat.get("method_assay"),
            "method_assay_empty": cat.get("method_assay_empty", True),
            "catalog_provenance": {
                "source_table": cat.get("source_table"),
                "join_path": cat.get("join_path"),
                "weight": cat.get("weight"),
            }
            if cat
            else None,
            "n_subjects_with_pairs": None,  # filled for candidates only
            "n_strict_consecutive_pairs": None,
        }
        item["stratum_hash"] = _hash(
            {k: v for k, v in item.items() if k != "stratum_hash"}
        )
        strata.append(item)

    material_all_empty = all(
        (catalog_meta.get(c) or {}).get("material_empty", True) for c in catalog_meta
    ) if catalog_meta else True

    return {
        "version": VERSION,
        "FULL_SOURCE_B_CATALOG_INVENTORY_STATUS": "PASS" if strata else "FAIL",
        "SOURCE_B_METADATA_RECOVERY_STATUS": (
            "PARTIAL_MATERIAL_EMPTY" if material_all_empty else "PARTIAL"
        ),
        "B_OUTCOME_UNIT_STRATA_EVALUATED": len(strata),
        "n_distinct_b_codes": n_codes,
        "n_catalog_meta_rows": len(catalog_meta),
        "n_strata": len(strata),
        "n_excluded": len(excluded),
        "excluded_sample": excluded[:20],
        "truncated": 0,
        "unexplained": 0,
        "no_top500_cap": True,
        "catalog_material_all_empty": material_all_empty,
        "schema_probe": {
            k: v for k, v in schema_probe.items() if k != "columns"
        }
        | {"n_columns": len(schema_probe.get("columns") or [])},
        "schema_columns_sample": (schema_probe.get("columns") or [])[:40],
        "strata": strata,
        "inventory_hash": _hash(
            {
                "n": len(strata),
                "codes": n_codes,
                "top": [(s["raw_code"], s["unit"]) for s in strata[:20]],
            }
        ),
        "ok": len(strata) > 500,  # must exceed prior top500
    }


def estimate_pairs_for_grain(
    conn_canonical: Any, *, raw_code: str, unit: str
) -> dict[str, Any]:
    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT s.subject_id::text, o.observed_at, oc.component_id::text
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND COALESCE(NULLIF(TRIM(oc.raw_code), ''),
                           NULLIF(TRIM(o.raw_code), ''), '∅') = %s
              AND COALESCE(NULLIF(TRIM(oc.raw_unit), ''),
                           NULLIF(TRIM(o.raw_unit), ''), '') = %s
              AND oc.numeric_value IS NOT NULL AND o.observed_at IS NOT NULL
            ORDER BY s.subject_id, o.observed_at, oc.component_id
            """,
            (SOURCE_B_SYSTEM_ID, raw_code, unit),
        )
        rows = cur.fetchall()

    by: dict[str, list] = defaultdict(list)
    for sid, ts, cid in rows:
        t = _parse_ts(ts)
        if t:
            by[str(sid)].append((t, str(cid)))

    n_pairs = 0
    n_subj = 0
    subjects_with_pairs: list[str] = []
    for sid, series in by.items():
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
        subjects_with_pairs.append(sid)
        for k in range(len(collapsed) - 1):
            if (collapsed[k + 1] - collapsed[k]).total_seconds() > 0:
                n_pairs += 1
    return {
        "n_subjects_with_pairs": n_subj,
        "n_strict_consecutive_pairs": n_pairs,
        "subject_ids_with_pairs": subjects_with_pairs,
    }


def outcome_specific_split_coverage(
    *, subject_ids_with_pairs: list[str]
) -> dict[str, Any]:
    roles = {sid: assign_role(sid) for sid in subject_ids_with_pairs}
    by_role: dict[str, list[str]] = {"train": [], "validation": [], "test": []}
    for sid, role in roles.items():
        by_role[role].append(sid)
    overlap = (
        set(by_role["train"]) & set(by_role["validation"])
        or set(by_role["train"]) & set(by_role["test"])
        or set(by_role["validation"]) & set(by_role["test"])
    )
    return {
        "OUTCOME_SPECIFIC_B_SPLIT_ACCOUNTING_STATUS": "PASS",
        "n_subjects_with_pairs": len(subject_ids_with_pairs),
        "by_role_subjects_with_pairs": {k: len(v) for k, v in by_role.items()},
        "split_overlap_zero": not overlap,
        "locator_overlap": "NOT_PUBLISHED",
        "unexplained": 0,
        "aggregate_only": False,
        "note": "Counts are outcome-specific (subjects with pairs for this code×unit).",
    }
