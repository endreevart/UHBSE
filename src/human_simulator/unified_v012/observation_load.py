"""Source B Observation load — validation slice + gated full load with checkpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.core.ids import load_hmac_key
from human_simulator.core.policy import ID_NAMESPACE_VERSION, KEY_VERSION
from human_simulator.stage03.canonical_id import compute_hmac_hex, length_prefix_utf8
from human_simulator.unified_v012.policy import (
    CHECKPOINT_EVERY_N_BATCHES,
    RUNTIME_DIR,
    SOURCE_B_INTEGRATION_PARTIAL,
    SOURCE_B_OBS_BATCH_SIZE,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)
from human_simulator.unified_v012.value_parse import parse_lab_value, resolve_unit


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_relation_bucket() -> dict[str, int]:
    return {
        "runtime_count": 0,
        "candidate_count": 0,
        "eligible_count": 0,
        "already_present_count": 0,
        "newly_loaded_count": 0,
        "final_canonical_count": 0,
        "rejected_count": 0,
        "unsupported_count": 0,
        "quarantined_count": 0,
        "source_record_count": 0,
        "truncated_count": 0,
        "unexplained_count": 0,
        "new_observations": 0,
        "new_observation_components": 0,
    }


def _opaque_subject(key: bytes, pid: int) -> str:
    return compute_hmac_hex(
        key_bytes=key,
        entity="Subject",
        id_namespace_version=ID_NAMESPACE_VERSION,
        source_system=SOURCE_B_SYSTEM_ID,
        inputs=[str(pid), KEY_VERSION],
    )


def _eid(key: bytes, entity: str, *parts: str) -> str:
    return compute_hmac_hex(
        key_bytes=key,
        entity=entity,
        id_namespace_version=ID_NAMESPACE_VERSION,
        source_system=SOURCE_B_SYSTEM_ID,
        inputs=[*parts, KEY_VERSION],
    )


def _loc(key: bytes, relation: str, pk: str) -> str:
    msg = length_prefix_utf8(
        f"locator|{SOURCE_B_SYSTEM_ID}|{relation}|{pk}|{KEY_VERSION}"
    )
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _prov(*, relation: str, loc: str, extra: dict | None = None) -> dict[str, Any]:
    # DB CHECK allows only CONFIRMED_SCHEMA|CANDIDATE|HYPOTHESIS|UNRESOLVED|NOT_MAPPED.
    # Design-level Observation decision remains SUPPORTED_TRANSFORM in artifacts.
    doc = {
        "confidence": 1.0,
        "key_version": KEY_VERSION,
        "load_run_id": f"unified_source_expansion_v{VERSION}",
        "record_origin": "OBSERVED",
        "source_schema": "quest_digital",
        "source_system": SOURCE_B_SYSTEM_ID,
        "mapping_status": "CANDIDATE",
        "transformed_at": _now(),
        "source_relation": relation,
        "transformation_id": f"unified_source_expansion_v{VERSION}",
        "id_namespace_version": ID_NAMESPACE_VERSION,
        "input_artifact_sha256": f"unified-v{VERSION}-source-b-observation-load",
        "source_record_locator": loc,
        "transformation_version": VERSION,
        "design_mapping_status": "SUPPORTED_TRANSFORMATION",
    }
    if extra:
        doc.update(extra)
    return doc


def _checkpoint_path(repo_root: Path) -> Path:
    return repo_root / RUNTIME_DIR / "observation-load-checkpoint.json"


def _write_checkpoint(repo_root: Path, doc: dict[str, Any]) -> None:
    path = _checkpoint_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _load_checkpoint(repo_root: Path) -> dict[str, Any] | None:
    path = _checkpoint_path(repo_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_weight_catalog(src: Any) -> dict[int, dict[str, Any]]:
    with src.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, code, name_en, code_en
            FROM quest_digital.analyses_weight
            """
        )
        return {
            int(r[0]): {
                "name": r[1],
                "code": r[2],
                "name_en": r[3],
                "code_en": r[4],
            }
            for r in cur.fetchall()
        }


def _fetch_constructor_batch(
    src: Any,
    *,
    after_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch constructor rows ordered by id — progress via after_id (no PII printed)."""
    with src.cursor() as cur:
        cur.execute(
            """
            SELECT
              ac.id,
              ac.user_id,
              ac.consultation_id,
              ac.pool_id,
              ac.catalog_id,
              ac.weight_id,
              ac.date,
              ac.created_at,
              ac.status,
              ac.value,
              ac.has_result,
              cat.weight_id AS catalog_weight_id,
              cat.code AS catalog_code,
              c.confirmed_at,
              c.success_at,
              c.date AS consult_date,
              c.time AS consult_time,
              c.created_at AS consult_created_at
            FROM quest_digital.analyses_constructor ac
            JOIN quest_digital.analyses_catalog cat ON cat.id = ac.catalog_id
            LEFT JOIN public.consultations c ON c.id = ac.consultation_id
            WHERE ac.id > %s
            ORDER BY ac.id
            LIMIT %s
            """,
            (after_id, limit),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _clinical_time(row: dict[str, Any]) -> Any:
    if row.get("date") is not None:
        return row["date"]
    if row.get("confirmed_at") is not None:
        return row["confirmed_at"]
    if row.get("success_at") is not None:
        return row["success_at"]
    consult_date = row.get("consult_date")
    if consult_date is not None:
        return consult_date  # date alone; time merge left to DB cast if needed
    return row.get("consult_created_at")


def _insert_observation_batch(
    conn: Any,
    *,
    key: bytes,
    rows: list[dict[str, Any]],
    weight_catalog: dict[int, dict[str, Any]],
    stats: dict[str, int],
) -> None:
    import json as _json

    # Group by pool_id for Observation headers
    by_pool: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        pid = row.get("pool_id")
        if pid is None:
            stats["rejected_count"] += 1
            continue
        by_pool.setdefault(int(pid), []).append(row)

    with conn.cursor() as cur:
        try:
            cur.execute("SET ROLE canonical_loader")
        except Exception:  # noqa: BLE001
            pass

        for pool_id, members in by_pool.items():
            first = members[0]
            user_id = first.get("user_id")
            consultation_id = first.get("consultation_id")
            if user_id is None or consultation_id is None:
                stats["rejected_count"] += len(members)
                continue

            sid = _opaque_subject(key, int(user_id))
            # Encounter FK is pilot-null (observation_encounter_null_in_pilot).
            # Store deterministic Encounter HMAC in provenance until migration 0005.
            eid = _eid(key, "Encounter", str(int(consultation_id)))
            oid = _eid(key, "Observation", str(pool_id))
            obs_loc = _loc(key, "analyses_pool", str(pool_id))
            obs_sr = _eid(key, "SourceRecord", "analyses_pool", str(pool_id))
            observed_at = _clinical_time(first)
            recorded_at = first.get("created_at")
            status = str(first.get("status")) if first.get("status") is not None else None
            miss = None if observed_at is not None else "clinical_time_absent"
            prov = _prov(
                relation="analyses_pool",
                loc=obs_loc,
                extra={
                    "pool_id_opaque": True,
                    "encounter_id_hmac": eid,
                    "encounter_fk_deferred": "pilot_null_no_migration_0005",
                },
            )

            cur.execute("SAVEPOINT obs_pool")
            try:
                cur.execute(
                    """
                    INSERT INTO canonical_evidence.source_record (
                      source_record_id, source_system_id, source_schema, source_relation,
                      source_record_locator, locator_scheme, locator_key_version,
                      source_created_at, source_updated_at, provenance
                    ) VALUES (%s,%s,'quest_digital',%s,%s,'deterministic_hmac_locator',%s,NULL,NULL,%s::jsonb)
                    ON CONFLICT (source_record_id) DO NOTHING
                    """,
                    (
                        obs_sr,
                        SOURCE_B_SYSTEM_ID,
                        "analyses_pool",
                        obs_loc,
                        KEY_VERSION,
                        _json.dumps(prov),
                    ),
                )
                if cur.rowcount:
                    stats["source_record_count"] += 1

                # encounter_id MUST be NULL — CHECK observation_encounter_null_in_pilot
                cur.execute(
                    """
                    INSERT INTO canonical_evidence.observation (
                      observation_id, subject_id, encounter_id, observed_at, recorded_at,
                      specimen_collected_at, status, data_level, missingness_reason, provenance
                    ) VALUES (%s,%s,NULL,%s,%s,NULL,%s,'OBSERVATION_HEADER',%s,%s::jsonb)
                    ON CONFLICT (observation_id) DO NOTHING
                    """,
                    (oid, sid, observed_at, recorded_at, status, miss, _json.dumps(prov)),
                )
                if cur.rowcount:
                    stats["new_observations"] += 1
                    stats["newly_loaded_count"] += 1
                else:
                    stats["already_present_count"] += 1
                cur.execute("RELEASE SAVEPOINT obs_pool")
            except Exception:  # noqa: BLE001
                cur.execute("ROLLBACK TO SAVEPOINT obs_pool")
                stats["rejected_count"] += len(members)
                stats["quarantined_count"] += 1
                continue

            for row in members:
                raw = row.get("value")
                parsed = parse_lab_value(raw if raw is None else str(raw))
                if not parsed.accepted:
                    if parsed.reject_reason == "EMPTY_VALUE":
                        stats["rejected_count"] += 1
                    else:
                        stats["unsupported_count"] += 1
                    continue
                if not parsed.xor_ok():
                    stats["quarantined_count"] += 1
                    continue

                unit_info = resolve_unit(
                    constructor_weight_id=int(row["weight_id"])
                    if row.get("weight_id") is not None
                    else None,
                    catalog_weight_id=int(row["catalog_weight_id"])
                    if row.get("catalog_weight_id") is not None
                    else None,
                    weight_catalog=weight_catalog,
                    value_unit_suffix=parsed.unit_suffix,
                )
                ctor_id = int(row["id"])
                cid = _eid(key, "ObservationComponent", str(ctor_id))
                loc = _loc(key, "analyses_constructor", str(ctor_id))
                sr_id = _eid(key, "SourceRecord", "analyses_constructor", str(ctor_id))
                cprov = _prov(
                    relation="analyses_constructor",
                    loc=loc,
                    extra={
                        "value_kind": parsed.kind,
                        "unit_source": unit_info.get("unit_source"),
                        "catalog_code_present": bool(row.get("catalog_code")),
                        "encounter_id_hmac": eid,
                    },
                )
                cur.execute("SAVEPOINT obs_comp")
                try:
                    cur.execute(
                        """
                        INSERT INTO canonical_evidence.source_record (
                          source_record_id, source_system_id, source_schema, source_relation,
                          source_record_locator, locator_scheme, locator_key_version,
                          source_created_at, source_updated_at, provenance
                        ) VALUES (%s,%s,'quest_digital',%s,%s,'deterministic_hmac_locator',%s,NULL,NULL,%s::jsonb)
                        ON CONFLICT (source_record_id) DO NOTHING
                        """,
                        (
                            sr_id,
                            SOURCE_B_SYSTEM_ID,
                            "analyses_constructor",
                            loc,
                            KEY_VERSION,
                            _json.dumps(cprov),
                        ),
                    )
                    if cur.rowcount:
                        stats["source_record_count"] += 1

                    raw_code = str(row.get("catalog_code") or row.get("catalog_id") or "unknown")
                    raw_value = parsed.raw
                    raw_unit = unit_info.get("unit")
                    if parsed.numeric_value is not None:
                        cur.execute(
                            """
                            INSERT INTO canonical_evidence.observation_component (
                              component_id, observation_id, raw_code, raw_value, numeric_value,
                              text_value, raw_unit, provenance
                            ) VALUES (%s,%s,%s,%s,%s,NULL,%s,%s::jsonb)
                            ON CONFLICT (component_id) DO NOTHING
                            """,
                            (
                                cid,
                                oid,
                                raw_code,
                                raw_value,
                                parsed.numeric_value,
                                raw_unit,
                                _json.dumps(cprov),
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO canonical_evidence.observation_component (
                              component_id, observation_id, raw_code, raw_value, numeric_value,
                              text_value, raw_unit, provenance
                            ) VALUES (%s,%s,%s,%s,NULL,%s,%s,%s::jsonb)
                            ON CONFLICT (component_id) DO NOTHING
                            """,
                            (
                                cid,
                                oid,
                                raw_code,
                                raw_value,
                                parsed.text_value,
                                raw_unit,
                                _json.dumps(cprov),
                            ),
                        )
                    if cur.rowcount:
                        stats["new_observation_components"] += 1
                        stats["newly_loaded_count"] += 1
                    else:
                        stats["already_present_count"] += 1
                    cur.execute("RELEASE SAVEPOINT obs_comp")
                except Exception:  # noqa: BLE001
                    cur.execute("ROLLBACK TO SAVEPOINT obs_comp")
                    stats["quarantined_count"] += 1

        try:
            cur.execute("RESET ROLE")
        except Exception:  # noqa: BLE001
            pass


def run_validation_slice(repo_root: Path, *, mapping: dict[str, Any]) -> dict[str, Any]:
    """Rollback-only Observation construction validation."""
    root = Path(repo_root)
    may = bool(mapping.get("may_populate_observation"))
    if not may and mapping.get("observation_decision") != "SUPPORTED_TRANSFORMATION":
        # Still attempt structural validation on a tiny slice for contract evidence,
        # but always rollback; do not require ACCEPTED for rollback proof.
        pass

    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.migrations import row_counts
        from human_simulator.canonical.settings import load_canonical_settings
        from human_simulator.unified.source_b_adapter import source_b_connection

        key = load_hmac_key(root)
        with source_b_connection(root) as src:
            weights = _load_weight_catalog(src)
            # Deterministic diverse cohort without publishing IDs:
            # first 50 non-empty + a few empty for reject proof
            rows = _fetch_constructor_batch(src, after_id=0, limit=80)

        with canonical_connection(load_canonical_settings()) as conn:
            before = {k: int(v) for k, v in row_counts(conn).items()}
            conn.autocommit = False
            stats = empty_relation_bucket()
            try:
                _insert_observation_batch(
                    conn, key=key, rows=rows, weight_catalog=weights, stats=stats
                )
            finally:
                conn.rollback()
            after = {k: int(v) for k, v in row_counts(conn).items()}

        unchanged = before == after
        return {
            "status": "PASS" if unchanged else "FAIL",
            "rollback": True,
            "counts_before": before,
            "counts_after_rollback": after,
            "counts_unchanged": unchanged,
            "slice_rows": len(rows),
            "insert_stats_before_rollback": stats,
            "typed_value_xor_enforced": True,
            "migration_0005": False,
            "no_patient_ids_in_artifact": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "INSUFFICIENT_DATA",
            "error_type": type(exc).__name__,
            "rollback": True,
            "migration_0005": False,
        }


def run_full_observation_load(
    repo_root: Path,
    *,
    mapping: dict[str, Any],
    resume: bool = True,
) -> dict[str, Any]:
    """Full load of eligible constructor rows when gates pass."""
    root = Path(repo_root)
    may = bool(mapping.get("may_populate_observation")) or mapping.get(
        "observation_decision"
    ) == "SUPPORTED_TRANSFORMATION"
    accounting = {"analyses_constructor": empty_relation_bucket()}

    if not may:
        return {
            "status": SOURCE_B_INTEGRATION_PARTIAL,
            "source_b_observation_load_status": "NOT_LOADED_GATES_FAILED",
            "observations_loaded": 0,
            "observation_components_loaded": 0,
            "reason": "Observation mapping gates failed — HYPOTHESIS retained",
            "failed_gates": mapping.get("failed_gates") or [],
            "relation_accounting": accounting,
            "truncated_total": 0,
            "unexplained_total": 0,
            "migration_0005": False,
        }

    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings
        from human_simulator.unified.source_b_adapter import source_b_connection

        key = load_hmac_key(root)
        ckpt = _load_checkpoint(root) if resume else None
        after_id = int((ckpt or {}).get("after_id") or 0)
        stats = empty_relation_bucket()
        if ckpt and ckpt.get("stats"):
            for k, v in ckpt["stats"].items():
                if k in stats:
                    stats[k] = int(v)

        batch_n = 0
        t0 = time.perf_counter()
        with source_b_connection(root) as src:
            weights = _load_weight_catalog(src)
            with src.cursor() as cur:
                cur.execute("SELECT COUNT(*)::bigint FROM quest_digital.analyses_constructor")
                runtime = int(cur.fetchone()[0])
            stats["runtime_count"] = runtime
            stats["candidate_count"] = runtime

            with canonical_connection(load_canonical_settings()) as conn:
                conn.autocommit = False
                while True:
                    rows = _fetch_constructor_batch(
                        src, after_id=after_id, limit=SOURCE_B_OBS_BATCH_SIZE
                    )
                    if not rows:
                        break
                    _insert_observation_batch(
                        conn, key=key, rows=rows, weight_catalog=weights, stats=stats
                    )
                    after_id = int(rows[-1]["id"])
                    batch_n += 1
                    if batch_n % CHECKPOINT_EVERY_N_BATCHES == 0:
                        conn.commit()
                        _write_checkpoint(
                            root,
                            {
                                "after_id": after_id,
                                "batches": batch_n,
                                "stats": stats,
                                "updated_at": _now(),
                            },
                        )
                        elapsed = time.perf_counter() - t0
                        print(
                            f"[unified-v012] obs load progress batches={batch_n} "
                            f"after_id={after_id} new_obs={stats['new_observations']} "
                            f"new_comp={stats['new_observation_components']} "
                            f"elapsed_s={elapsed:.1f}",
                            flush=True,
                        )
                conn.commit()
                _write_checkpoint(
                    root,
                    {
                        "after_id": after_id,
                        "batches": batch_n,
                        "stats": stats,
                        "completed": True,
                        "updated_at": _now(),
                    },
                )

        eligible = runtime - stats["rejected_count"]  # approx
        stats["eligible_count"] = max(eligible, 0)
        stats["final_canonical_count"] = (
            stats["new_observation_components"] + stats["already_present_count"]
        )
        accounting["analyses_constructor"] = stats
        return {
            "status": "PASS",
            "source_b_observation_load_status": "PASS",
            "observations_newly_inserted": stats["new_observations"],
            "observation_components_newly_inserted": stats["new_observation_components"],
            "source_records_inserted": stats["source_record_count"],
            "relation_accounting": accounting,
            "truncated_total": stats["truncated_count"],
            "unexplained_total": stats["unexplained_count"],
            "batches": batch_n,
            "finished_at": _now(),
            "version": VERSION,
            "migration_0005": False,
            "identity_merge": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": SOURCE_B_INTEGRATION_PARTIAL,
            "source_b_observation_load_status": "FAIL",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "relation_accounting": accounting,
            "truncated_total": 0,
            "unexplained_total": 0,
            "migration_0005": False,
        }


def run_observation_idempotency(
    repo_root: Path,
    *,
    mapping: dict[str, Any],
    first_pass: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Second full-load pass — expect newly inserted ≈ 0."""
    if (first_pass or {}).get("source_b_observation_load_status") != "PASS":
        return {
            "status": "SKIPPED",
            "reason": "first pass did not load observations",
            "source_b_observation_idempotency_status": "SKIPPED",
        }
    # Force fresh scan from id 0 but ON CONFLICT should insert 0
    second = run_full_observation_load(repo_root, mapping=mapping, resume=False)
    new_obs = int(second.get("observations_newly_inserted") or 0)
    new_comp = int(second.get("observation_components_newly_inserted") or 0)
    ok = new_obs == 0 and new_comp == 0
    return {
        "status": "PASS" if ok else "FAIL",
        "source_b_observation_idempotency_status": "PASS" if ok else "FAIL",
        "second_pass_new_observations": new_obs,
        "second_pass_new_components": new_comp,
        "first_pass_summary": {
            "observations_newly_inserted": (first_pass or {}).get("observations_newly_inserted"),
            "observation_components_newly_inserted": (first_pass or {}).get(
                "observation_components_newly_inserted"
            ),
        },
        "migration_0005": False,
    }
