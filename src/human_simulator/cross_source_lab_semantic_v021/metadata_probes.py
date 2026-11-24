"""Deep read-only Source A/B metadata probes — never invent specimen/assay."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.policy import VERSION


def _hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _field_report(
    *,
    schema: str,
    table: str,
    column: str,
    non_null: int | None,
    distinct: int | None,
    sample_category_hashes: list[str],
    usability: str,
    fk_lineage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": schema,
        "table": table,
        "column": column,
        "fk_lineage": fk_lineage or [],
        "non_null_count": non_null,
        "distinct_count": distinct,
        "sample_category_hashes": sample_category_hashes[:20],
        "accepted_usability_status": usability,
    }


def probe_source_a_raw_metadata(conn_a: Any | None) -> dict[str, Any]:
    """Full read-only schema/FK discovery for specimen/method/assay on Source A."""
    out: dict[str, Any] = {
        "version": VERSION,
        "SOURCE_A_RAW_METADATA_PROBE_STATUS": "NOT_RUN",
        "connection": "NOT_AVAILABLE",
        "fields": [],
        "queries": [],
        "SOURCE_A_SPECIMEN_METADATA_STATUS": "NOT_PROBED",
        "SOURCE_A_ASSAY_METADATA_STATUS": "NOT_PROBED",
        "ok": False,
    }
    if conn_a is None:
        out["SOURCE_A_RAW_METADATA_PROBE_STATUS"] = "CONNECTION_UNAVAILABLE"
        out["SOURCE_A_SPECIMEN_METADATA_STATUS"] = "NOT_AVAILABLE_IN_SOURCE"
        out["SOURCE_A_ASSAY_METADATA_STATUS"] = "SOURCE_DOCUMENTATION_REQUIRED"
        out["SOURCE_A_METADATA_RECOVERY_STATUS"] = "PROVIDER_REGISTRY_ONLY"
        return out

    try:
        with conn_a.cursor() as cur:
            q1 = """
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND (
                    lower(column_name) ~ '(specimen|material|biospecimen|sample_type|biomaterial)'
                    OR lower(column_name) ~ '(method|assay|analyzer|platform|instrument)'
                    OR lower(column_name) ~ '(ref.?range|reference_interval|norm)'
                    OR lower(column_name) ~ '(fasting|натощак)'
                    OR lower(column_name) ~ '(provider|laboratory|lab_id|catalog)'
                  )
                ORDER BY 1, 2, 3
                LIMIT 500
            """
            cur.execute(q1)
            cols = [
                {
                    "schema": r[0],
                    "table": r[1],
                    "column": r[2],
                    "data_type": r[3],
                }
                for r in cur.fetchall()
            ]
            out["queries"].append(
                {"name": "a_metadata_column_scan", "query_hash": _hash(q1), "n_hits": len(cols)}
            )

            q_fk = """
                SELECT
                  tc.table_schema, tc.table_name, kcu.column_name,
                  ccu.table_schema AS foreign_table_schema,
                  ccu.table_name AS foreign_table_name,
                  ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND (
                    lower(kcu.column_name) ~ '(lab|analy|test|catalog|method|specimen|material|provider)'
                    OR lower(ccu.table_name) ~ '(lab|analy|test|catalog|method|specimen|material|provider)'
                  )
                LIMIT 300
            """
            cur.execute(q_fk)
            fks = [
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
            out["queries"].append(
                {"name": "a_lab_fk_scan", "query_hash": _hash(q_fk), "n_hits": len(fks)}
            )

            fields: list[dict[str, Any]] = []
            # Profile up to 25 candidate columns for non-null/distinct (no values logged)
            for c in cols[:25]:
                sch, tbl, col = c["schema"], c["table"], c["column"]
                try:
                    cur.execute(
                        f"""
                        SELECT
                          COUNT(*) FILTER (WHERE "{col}" IS NOT NULL)::bigint,
                          COUNT(DISTINCT "{col}")::bigint
                        FROM "{sch}"."{tbl}"
                        """
                    )
                    nn, dist = cur.fetchone()
                    # category hashes only — never raw values
                    cur.execute(
                        f"""
                        SELECT md5(COALESCE("{col}"::text, '')) AS h, COUNT(*)::bigint
                        FROM "{sch}"."{tbl}"
                        WHERE "{col}" IS NOT NULL
                        GROUP BY 1
                        ORDER BY 2 DESC
                        LIMIT 5
                        """
                    )
                    hashes = [r[0] for r in cur.fetchall()]
                    usability = (
                        "AVAILABLE_FROM_SOURCE"
                        if nn and int(nn) > 0
                        else "COLUMN_EXISTS_ALL_NULL"
                    )
                    fields.append(
                        _field_report(
                            schema=sch,
                            table=tbl,
                            column=col,
                            non_null=int(nn or 0),
                            distinct=int(dist or 0),
                            sample_category_hashes=hashes,
                            usability=usability,
                            fk_lineage=[
                                f
                                for f in fks
                                if f["schema"] == sch
                                and f["table"] == tbl
                                and f["column"] == col
                            ],
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    fields.append(
                        {
                            "schema": sch,
                            "table": tbl,
                            "column": col,
                            "error": type(e).__name__,
                            "accepted_usability_status": "PROBE_ERROR",
                        }
                    )
                    conn_a.rollback()

            out["fields"] = fields
            out["connection"] = "OK"
            out["SOURCE_A_RAW_METADATA_PROBE_STATUS"] = "PASS"

            specimen_fields = [
                f
                for f in fields
                if any(
                    x in str(f.get("column") or "").lower()
                    for x in ("specimen", "material", "biospecimen", "sample_type")
                )
            ]
            assay_fields = [
                f
                for f in fields
                if any(
                    x in str(f.get("column") or "").lower()
                    for x in ("method", "assay", "analyzer", "platform", "instrument")
                )
            ]
            specimen_usable = any(
                f.get("accepted_usability_status") == "AVAILABLE_FROM_SOURCE"
                for f in specimen_fields
            )
            assay_usable = any(
                f.get("accepted_usability_status") == "AVAILABLE_FROM_SOURCE"
                for f in assay_fields
            )
            out["SOURCE_A_SPECIMEN_METADATA_STATUS"] = (
                "AVAILABLE_FROM_SOURCE"
                if specimen_usable
                else (
                    "NOT_AVAILABLE_IN_SOURCE"
                    if specimen_fields
                    else "SOURCE_DOCUMENTATION_REQUIRED"
                )
            )
            out["SOURCE_A_ASSAY_METADATA_STATUS"] = (
                "AVAILABLE_FROM_SOURCE"
                if assay_usable
                else (
                    "NOT_AVAILABLE_IN_SOURCE"
                    if assay_fields
                    else "SOURCE_DOCUMENTATION_REQUIRED"
                )
            )
            # Never invent serum/blood
            out["default_specimen_invented"] = False
            out["SOURCE_A_METADATA_RECOVERY_STATUS"] = (
                "PASS_WITH_GAPS"
                if not specimen_usable or not assay_usable
                else "PASS"
            )
            out["ok"] = True
            out["n_metadata_columns"] = len(cols)
            out["n_lab_fks"] = len(fks)
            out["probe_hash"] = _hash(
                {
                    "n_cols": len(cols),
                    "n_fks": len(fks),
                    "n_fields": len(fields),
                    "spec": out["SOURCE_A_SPECIMEN_METADATA_STATUS"],
                    "assay": out["SOURCE_A_ASSAY_METADATA_STATUS"],
                }
            )
    except Exception as e:  # noqa: BLE001
        out["connection"] = f"ERROR:{type(e).__name__}"
        out["SOURCE_A_RAW_METADATA_PROBE_STATUS"] = "FAIL"
        out["SOURCE_A_METADATA_RECOVERY_STATUS"] = "PROBE_FAILED"
        out["ok"] = False
    return out


def probe_source_b_raw_metadata(conn_b: Any | None) -> dict[str, Any]:
    """Continue Source B catalog/FK discovery; column existence ≠ data presence."""
    out: dict[str, Any] = {
        "version": VERSION,
        "SOURCE_B_RAW_METADATA_PROBE_STATUS": "NOT_RUN",
        "connection": "NOT_AVAILABLE",
        "fields": [],
        "queries": [],
        "analyses_catalog_rows": None,
        "material_column_exists": None,
        "material_non_null": None,
        "ok": False,
    }
    if conn_b is None:
        out["SOURCE_B_RAW_METADATA_PROBE_STATUS"] = "CONNECTION_UNAVAILABLE"
        out["SOURCE_B_METADATA_RECOVERY_STATUS"] = "CONNECTION_UNAVAILABLE"
        return out

    try:
        with conn_b.cursor() as cur:
            # analyses_catalog material (quest_digital — same as v0.2 inventory)
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
            out["queries"].append(
                {
                    "name": "b_analyses_catalog_material",
                    "query_hash": _hash("b_material_counts_quest_digital"),
                    "n_rows": int(n_rows or 0),
                    "n_material_nonempty": int(n_mat or 0),
                }
            )
            out["fields"].append(
                _field_report(
                    schema="quest_digital",
                    table="analyses_catalog",
                    column="material",
                    non_null=int(n_mat or 0),
                    distinct=None,
                    sample_category_hashes=[],
                    usability=(
                        "AVAILABLE_FROM_SOURCE"
                        if int(n_mat or 0) > 0
                        else "COLUMN_EXISTS_ALL_NULL"
                    ),
                )
            )

            q_cols = """
                SELECT table_schema, table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'quest_digital'
                  AND (
                    lower(table_name) ~ '(analys|lab_result|referral|service|panel|pool|constructor|method|analyzer|reference)'
                    OR lower(column_name) ~ '(material|specimen|method|assay|analyzer|platform|ref.?range|json)'
                  )
                ORDER BY 1, 2, 3
                LIMIT 400
            """
            cur.execute(q_cols)
            cols = [
                {"schema": r[0], "table": r[1], "column": r[2]} for r in cur.fetchall()
            ]
            out["queries"].append(
                {"name": "b_metadata_column_scan", "query_hash": _hash(q_cols), "n_hits": len(cols)}
            )

            q_fk = """
                SELECT
                  tc.table_schema, tc.table_name, kcu.column_name,
                  ccu.table_schema, ccu.table_name, ccu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'quest_digital'
                  AND (
                    lower(tc.table_name) ~ '(analys|lab|referral|service|panel|pool|constructor)'
                    OR lower(ccu.table_name) ~ '(analys|lab|referral|service|panel|pool|constructor)'
                  )
                LIMIT 300
            """
            cur.execute(q_fk)
            fks = [
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
            out["queries"].append(
                {"name": "b_lab_fk_scan", "query_hash": _hash(q_fk), "n_hits": len(fks)}
            )

            # Profile selected method/assay-like columns
            for c in cols[:30]:
                if not any(
                    x in c["column"].lower()
                    for x in (
                        "material",
                        "specimen",
                        "method",
                        "assay",
                        "analyzer",
                        "platform",
                        "range",
                    )
                ):
                    continue
                sch, tbl, col = c["schema"], c["table"], c["column"]
                try:
                    cur.execute(
                        f"""
                        SELECT
                          COUNT(*) FILTER (WHERE "{col}" IS NOT NULL)::bigint,
                          COUNT(DISTINCT "{col}")::bigint
                        FROM "{sch}"."{tbl}"
                        """
                    )
                    nn, dist = cur.fetchone()
                    cur.execute(
                        f"""
                        SELECT md5(COALESCE("{col}"::text, '')), COUNT(*)::bigint
                        FROM "{sch}"."{tbl}"
                        WHERE "{col}" IS NOT NULL
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 5
                        """
                    )
                    hashes = [r[0] for r in cur.fetchall()]
                    out["fields"].append(
                        _field_report(
                            schema=sch,
                            table=tbl,
                            column=col,
                            non_null=int(nn or 0),
                            distinct=int(dist or 0),
                            sample_category_hashes=hashes,
                            usability=(
                                "AVAILABLE_FROM_SOURCE"
                                if nn and int(nn) > 0
                                else "COLUMN_EXISTS_ALL_NULL"
                            ),
                            fk_lineage=[
                                f
                                for f in fks
                                if f["schema"] == sch
                                and f["table"] == tbl
                                and f["column"] == col
                            ],
                        )
                    )
                except Exception:  # noqa: BLE001
                    try:
                        conn_b.rollback()
                    except Exception:
                        pass

            material_all_empty = int(n_mat or 0) == 0
            assay_available = any(
                f.get("accepted_usability_status") == "AVAILABLE_FROM_SOURCE"
                and any(
                    x in str(f.get("column") or "").lower()
                    for x in ("method", "assay", "analyzer", "platform")
                )
                for f in out["fields"]
            )
            out["connection"] = "OK"
            out["SOURCE_B_RAW_METADATA_PROBE_STATUS"] = "PASS"
            out["catalog_material_all_empty"] = material_all_empty
            out["SOURCE_B_SPECIMEN_METADATA_STATUS"] = (
                "NOT_AVAILABLE_IN_SOURCE"
                if material_all_empty
                else "AVAILABLE_FROM_SOURCE"
            )
            out["SOURCE_B_ASSAY_METADATA_STATUS"] = (
                "AVAILABLE_FROM_SOURCE"
                if assay_available
                else "SOURCE_DOCUMENTATION_REQUIRED"
            )
            out["SOURCE_B_METADATA_RECOVERY_STATUS"] = (
                "PASS_MATERIAL_EMPTY_ASSAY_GAPS"
                if material_all_empty
                else "PASS"
            )
            out["provider_input_required"] = material_all_empty or not assay_available
            out["n_lab_fks"] = len(fks)
            out["n_metadata_columns"] = len(cols)
            out["ok"] = True
            out["probe_hash"] = _hash(
                {
                    "rows": out["analyses_catalog_rows"],
                    "mat": out["material_non_null"],
                    "fields": len(out["fields"]),
                }
            )
    except Exception as e:  # noqa: BLE001
        out["connection"] = f"ERROR:{type(e).__name__}"
        out["SOURCE_B_RAW_METADATA_PROBE_STATUS"] = "FAIL"
        out["SOURCE_B_METADATA_RECOVERY_STATUS"] = "PROBE_FAILED"
        out["ok"] = False
    return out
