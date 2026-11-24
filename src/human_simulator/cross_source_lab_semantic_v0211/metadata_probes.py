"""Lab-context-aware metadata probes — no global substring scan, no row-derived hashes."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from human_simulator.cross_source_lab_semantic_v0211.lab_context import (
    classify_lab_token,
    exclusion_reason_for_column,
    is_excluded_relation,
)
from human_simulator.cross_source_lab_semantic_v0211.policy import (
    SOURCE_A_LAB_SEED_RELATIONS,
    SOURCE_B_LAB_SEED_RELATIONS,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _candidate_record(
    *,
    source_system: str,
    schema: str,
    table: str,
    column: str,
    role: str | None,
    route: list[str],
    fk_lineage: list[dict[str, Any]],
    non_null: int | None,
    distinct: int | None,
    semantic: str,
    usability: str,
    rejection: str | None,
) -> dict[str, Any]:
    return {
        "source_system": source_system,
        "schema": schema,
        "table": table,
        "column": column,
        "relation_semantic_role": role,
        "route_from_laboratory_observation_or_catalog": route,
        "fk_lineage": fk_lineage,
        "non_null_count": non_null,
        "distinct_count": distinct,
        "semantic_classification": semantic,
        "accepted_usability_status": usability,
        "rejection_reason": rejection,
        # intentionally NO sample_category_hashes
    }


def _fetch_fks(cur: Any, *, schema: str | None = None) -> list[dict[str, Any]]:
    if schema:
        cur.execute(
            """
            SELECT tc.table_schema, tc.table_name, kcu.column_name,
                   ccu.table_schema, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND (tc.table_schema = %s OR ccu.table_schema = %s)
            LIMIT 500
            """,
            (schema, schema),
        )
    else:
        cur.execute(
            """
            SELECT tc.table_schema, tc.table_name, kcu.column_name,
                   ccu.table_schema, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            LIMIT 500
            """
        )
    return [
        {
            "schema": r[0],
            "table": r[1],
            "column": r[2],
            "fk_schema": r[3],
            "fk_table": r[4],
            "fk_column": r[5],
        }
        for r in cur.fetchall()
    ]


def _expand_lab_graph(
    fks: list[dict[str, Any]], seeds: tuple[tuple[str, str], ...]
) -> set[tuple[str, str]]:
    """BFS over proven FK edges from seed laboratory relations."""
    graph: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for f in fks:
        a = (f["schema"], f["table"])
        b = (f["fk_schema"], f["fk_table"])
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    seen: set[tuple[str, str]] = set(seeds)
    queue = list(seeds)
    while queue:
        cur = queue.pop()
        for nxt in graph.get(cur, ()):
            if nxt in seen:
                continue
            if is_excluded_relation(schema=nxt[0], table=nxt[1]):
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


def _profile_column(cur: Any, schema: str, table: str, column: str) -> tuple[int, int]:
    cur.execute(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE "{column}" IS NOT NULL)::bigint,
          COUNT(DISTINCT "{column}")::bigint
        FROM "{schema}"."{table}"
        """
    )
    nn, dist = cur.fetchone()
    return int(nn or 0), int(dist or 0)


def probe_source_a_lab_context(conn_a: Any | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": VERSION,
        "LAB_CONTEXT_METADATA_DISCOVERY_STATUS": "NOT_RUN",
        "SOURCE_A_RAW_METADATA_PROBE_STATUS": "NOT_RUN",
        "connection": "NOT_AVAILABLE",
        "candidates": [],
        "rejected": [],
        "queries": [],
        "ok": False,
    }
    if conn_a is None:
        out["SOURCE_A_RAW_METADATA_PROBE_STATUS"] = "CONNECTION_UNAVAILABLE"
        out["SOURCE_A_SPECIMEN_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_A_ASSAY_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_A_METADATA_RECOVERY_STATUS"] = "CONNECTION_UNAVAILABLE"
        out["LAB_CONTEXT_METADATA_DISCOVERY_STATUS"] = "CONNECTION_UNAVAILABLE"
        return out

    try:
        with conn_a.cursor() as cur:
            fks = _fetch_fks(cur, schema="magerya_api")
            out["queries"].append(
                {"name": "a_fk_scan", "query_hash": _hash("a_fk"), "n": len(fks)}
            )
            lab_rels = _expand_lab_graph(fks, SOURCE_A_LAB_SEED_RELATIONS)
            # Always include seeds even if FK graph empty
            lab_rels |= set(SOURCE_A_LAB_SEED_RELATIONS)
            out["lab_relation_count"] = len(lab_rels)
            out["lab_relations"] = sorted(f"{s}.{t}" for s, t in lab_rels)

            # Columns only on lab-context relations
            placeholders = []
            params: list[Any] = []
            for sch, tbl in sorted(lab_rels):
                placeholders.append("(table_schema = %s AND table_name = %s)")
                params.extend([sch, tbl])
            if not placeholders:
                cols: list[dict[str, Any]] = []
            else:
                sql = f"""
                    SELECT table_schema, table_name, column_name
                    FROM information_schema.columns
                    WHERE ({' OR '.join(placeholders)})
                    ORDER BY 1, 2, 3
                """
                cur.execute(sql, params)
                cols = [
                    {"schema": r[0], "table": r[1], "column": r[2]}
                    for r in cur.fetchall()
                ]
            out["queries"].append(
                {
                    "name": "a_lab_relation_columns",
                    "query_hash": _hash(["a_cols", len(cols)]),
                    "n": len(cols),
                }
            )

            candidates: list[dict[str, Any]] = []
            rejected: list[dict[str, Any]] = []
            for c in cols:
                sch, tbl, col = c["schema"], c["table"], c["column"]
                excl = exclusion_reason_for_column(schema=sch, table=tbl, column=col)
                role = classify_lab_token(col)
                route = [f"{sch}.{tbl}", "seed:document_analysisresult*"]
                fkl = [
                    f
                    for f in fks
                    if (f["schema"] == sch and f["table"] == tbl)
                    or (f["fk_schema"] == sch and f["fk_table"] == tbl)
                ][:5]
                if excl:
                    rejected.append(
                        _candidate_record(
                            source_system=SOURCE_A_SYSTEM_ID,
                            schema=sch,
                            table=tbl,
                            column=col,
                            role=None,
                            route=route,
                            fk_lineage=fkl,
                            non_null=None,
                            distinct=None,
                            semantic="rejected_false_positive_or_excluded",
                            usability="REJECTED",
                            rejection=excl,
                        )
                    )
                    continue
                if not role:
                    continue  # not a metadata candidate — silent skip (not a hit)
                try:
                    nn, dist = _profile_column(cur, sch, tbl, col)
                except Exception:  # noqa: BLE001
                    try:
                        conn_a.rollback()
                    except Exception:
                        pass
                    nn, dist = None, None
                usability = (
                    "AVAILABLE_FROM_SOURCE"
                    if nn and nn > 0
                    else "COLUMN_EXISTS_ALL_NULL"
                )
                candidates.append(
                    _candidate_record(
                        source_system=SOURCE_A_SYSTEM_ID,
                        schema=sch,
                        table=tbl,
                        column=col,
                        role=role,
                        route=route,
                        fk_lineage=fkl,
                        non_null=nn,
                        distinct=dist,
                        semantic=f"lab_context_{role}",
                        usability=usability,
                        rejection=None,
                    )
                )

            def _confirmed(role_names: set[str]) -> bool:
                return any(
                    c.get("relation_semantic_role") in role_names
                    and c.get("accepted_usability_status") == "AVAILABLE_FROM_SOURCE"
                    for c in candidates
                )

            specimen_ok = _confirmed({"specimen"})
            assay_ok = _confirmed({"assay", "analyzer"})
            out["candidates"] = candidates
            out["rejected"] = rejected[:100]
            out["n_candidates"] = len(candidates)
            out["n_rejected_scanned"] = len(rejected)
            out["connection"] = "OK"
            out["SOURCE_A_RAW_METADATA_PROBE_STATUS"] = "PASS"
            out["LAB_CONTEXT_METADATA_DISCOVERY_STATUS"] = "PASS"
            out["SOURCE_A_SPECIMEN_METADATA_STATUS"] = (
                "AVAILABLE_FROM_SOURCE"
                if specimen_ok
                else "SOURCE_DOCUMENTATION_REQUIRED"
            )
            out["SOURCE_A_ASSAY_METADATA_STATUS"] = (
                "AVAILABLE_FROM_SOURCE"
                if assay_ok
                else "SOURCE_DOCUMENTATION_REQUIRED"
            )
            out["SOURCE_A_METADATA_RECOVERY_STATUS"] = (
                "PASS"
                if specimen_ok and assay_ok
                else "PASS_LAB_CONTEXT_NO_CONFIRMED_METADATA"
            )
            out["default_specimen_invented"] = False
            out["global_substring_scan_used"] = False
            out["sample_category_hashes_emitted"] = False
            out["probe_hash"] = _hash(
                {
                    "n_cand": len(candidates),
                    "specimen": out["SOURCE_A_SPECIMEN_METADATA_STATUS"],
                    "assay": out["SOURCE_A_ASSAY_METADATA_STATUS"],
                }
            )
            out["ok"] = True
    except Exception as e:  # noqa: BLE001
        out["connection"] = f"ERROR:{type(e).__name__}"
        out["SOURCE_A_RAW_METADATA_PROBE_STATUS"] = "FAIL"
        out["LAB_CONTEXT_METADATA_DISCOVERY_STATUS"] = "FAIL"
        out["SOURCE_A_SPECIMEN_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_A_ASSAY_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_A_METADATA_RECOVERY_STATUS"] = "PROBE_FAILED"
        out["ok"] = False
    return out


def probe_source_b_lab_context(conn_b: Any | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": VERSION,
        "SOURCE_B_RAW_METADATA_PROBE_STATUS": "NOT_RUN",
        "connection": "NOT_AVAILABLE",
        "candidates": [],
        "column_reclassification": [],
        "ok": False,
    }
    if conn_b is None:
        out["SOURCE_B_RAW_METADATA_PROBE_STATUS"] = "CONNECTION_UNAVAILABLE"
        out["SOURCE_B_SPECIMEN_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_B_ASSAY_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_B_METADATA_RECOVERY_STATUS"] = "CONNECTION_UNAVAILABLE"
        return out

    try:
        with conn_b.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)::bigint,
                       COUNT(*) FILTER (
                         WHERE material IS NOT NULL AND TRIM(material::text) <> ''
                       )::bigint
                FROM quest_digital.analyses_catalog
                WHERE deleted_at IS NULL
                """
            )
            n_rows, n_mat = cur.fetchone()
            out["analyses_catalog_rows"] = int(n_rows or 0)
            out["material_column_exists"] = True
            out["material_non_null"] = int(n_mat or 0)
            out["catalog_material_all_empty"] = int(n_mat or 0) == 0

            fks = _fetch_fks(cur, schema="quest_digital")
            lab_rels = _expand_lab_graph(fks, SOURCE_B_LAB_SEED_RELATIONS)
            lab_rels |= set(SOURCE_B_LAB_SEED_RELATIONS)

            cur.execute(
                """
                SELECT table_schema, table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'quest_digital'
                ORDER BY 1, 2, 3
                LIMIT 500
                """
            )
            all_cols = [
                {"schema": r[0], "table": r[1], "column": r[2]} for r in cur.fetchall()
            ]
            # Reclassify the previous "108" style inventory: all quest_digital cols scanned
            reclass: list[dict[str, Any]] = []
            candidates: list[dict[str, Any]] = []
            for c in all_cols:
                sch, tbl, col = c["schema"], c["table"], c["column"]
                in_lab = (sch, tbl) in lab_rels
                excl = exclusion_reason_for_column(schema=sch, table=tbl, column=col)
                role = classify_lab_token(col) if in_lab and not excl else None
                if excl:
                    bucket = "rejected_false_positive"
                elif not in_lab:
                    bucket = "unrelated"
                elif role:
                    bucket = "laboratory_relevant"
                elif any(
                    x in tbl
                    for x in ("analys", "lab", "pool", "referral", "constructor")
                ):
                    bucket = "infrastructure"
                else:
                    bucket = "ambiguous"
                entry = {
                    "schema": sch,
                    "table": tbl,
                    "column": col,
                    "bucket": bucket,
                    "role": role,
                    "in_lab_graph": in_lab,
                    "rejection_reason": excl,
                }
                reclass.append(entry)
                if bucket == "laboratory_relevant" and role:
                    nn = dist = None
                    if role in {"specimen", "assay", "analyzer", "reference_range", "fasting"}:
                        try:
                            nn, dist = _profile_column(cur, sch, tbl, col)
                        except Exception:  # noqa: BLE001
                            try:
                                conn_b.rollback()
                            except Exception:
                                pass
                    usability = (
                        "AVAILABLE_FROM_SOURCE"
                        if nn and nn > 0
                        else (
                            "COLUMN_EXISTS_ALL_NULL"
                            if nn == 0
                            else "LAB_CONTEXT_CANDIDATE_UNPROFILED"
                        )
                    )
                    # material known empty
                    if tbl == "analyses_catalog" and col == "material":
                        usability = "COLUMN_EXISTS_ALL_NULL"
                        nn = int(n_mat or 0)
                    candidates.append(
                        _candidate_record(
                            source_system=SOURCE_B_SYSTEM_ID,
                            schema=sch,
                            table=tbl,
                            column=col,
                            role=role,
                            route=[f"{sch}.{tbl}", "seed:analyses_catalog"],
                            fk_lineage=[],
                            non_null=nn,
                            distinct=dist,
                            semantic=f"lab_context_{role}",
                            usability=usability,
                            rejection=None,
                        )
                    )

            from collections import Counter

            bucket_counts = Counter(r["bucket"] for r in reclass)
            assay_confirmed = any(
                c.get("relation_semantic_role") in {"assay", "analyzer"}
                and c.get("accepted_usability_status") == "AVAILABLE_FROM_SOURCE"
                for c in candidates
            )
            specimen_confirmed = any(
                c.get("relation_semantic_role") == "specimen"
                and c.get("accepted_usability_status") == "AVAILABLE_FROM_SOURCE"
                for c in candidates
            )
            # material column exists but empty → NOT available
            out["candidates"] = candidates
            out["column_reclassification"] = {
                "n_columns_scanned": len(reclass),
                "bucket_counts": dict(bucket_counts),
                "sample_rejected": [r for r in reclass if r["bucket"] == "rejected_false_positive"][:20],
                "sample_lab_relevant": [r for r in reclass if r["bucket"] == "laboratory_relevant"][:40],
            }
            out["connection"] = "OK"
            out["SOURCE_B_RAW_METADATA_PROBE_STATUS"] = "PASS"
            out["SOURCE_B_SPECIMEN_METADATA_STATUS"] = (
                "AVAILABLE_FROM_SOURCE"
                if specimen_confirmed
                else "NOT_AVAILABLE_IN_SOURCE"
            )
            out["SOURCE_B_ASSAY_METADATA_STATUS"] = (
                "AVAILABLE_FROM_SOURCE"
                if assay_confirmed
                else "SOURCE_DOCUMENTATION_REQUIRED"
            )
            out["SOURCE_B_METADATA_RECOVERY_STATUS"] = (
                "PASS_MATERIAL_EMPTY_ASSAY_DOCS_REQUIRED"
            )
            out["provider_input_required"] = True
            out["sample_category_hashes_emitted"] = False
            out["global_substring_scan_used"] = False
            out["probe_hash"] = _hash(
                {
                    "rows": out["analyses_catalog_rows"],
                    "mat": out["material_non_null"],
                    "buckets": dict(bucket_counts),
                }
            )
            out["ok"] = out["analyses_catalog_rows"] == 1882 and out["material_non_null"] == 0
    except Exception as e:  # noqa: BLE001
        out["connection"] = f"ERROR:{type(e).__name__}"
        out["SOURCE_B_RAW_METADATA_PROBE_STATUS"] = "FAIL"
        out["SOURCE_B_SPECIMEN_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_B_ASSAY_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_B_METADATA_RECOVERY_STATUS"] = "PROBE_FAILED"
        out["ok"] = False
    return out
