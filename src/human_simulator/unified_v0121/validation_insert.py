"""Mandatory rollback validation insert for Observation / Component / SourceRecord."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.core.ids import load_hmac_key
from human_simulator.core.policy import ID_NAMESPACE_VERSION, KEY_VERSION
from human_simulator.stage03.canonical_id import compute_hmac_hex, length_prefix_utf8
from human_simulator.unified_v0121.policy import (
    SOURCE_B_SYSTEM_ID,
    VALIDATION_ID_PREFIX,
    VALIDATION_NONCE,
    VERSION,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def synthetic_entity_id(key: bytes, entity: str, nonce: str) -> str:
    """Deterministic HMAC-like ID from fixed seed material — cannot collide with production.

    Production IDs use source PK inputs; validation uses ``validation-slice-v0121|{nonce}``.
    """
    digest = compute_hmac_hex(
        key_bytes=key,
        entity=entity,
        id_namespace_version=ID_NAMESPACE_VERSION,
        source_system=SOURCE_B_SYSTEM_ID,
        inputs=[f"{VALIDATION_NONCE}|{nonce}", KEY_VERSION],
    )
    return f"{VALIDATION_ID_PREFIX}{digest[:48]}"


def _loc(key: bytes, relation: str, pk: str) -> str:
    msg = length_prefix_utf8(
        f"locator|{SOURCE_B_SYSTEM_ID}|{relation}|{pk}|{KEY_VERSION}"
    )
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _prov(*, relation: str, loc: str) -> dict[str, Any]:
    return {
        "confidence": 1.0,
        "key_version": KEY_VERSION,
        "load_run_id": f"unified_source_expansion_v{VERSION}_validation",
        "record_origin": "OBSERVED",
        "source_schema": "quest_digital",
        "source_system": SOURCE_B_SYSTEM_ID,
        "mapping_status": "CANDIDATE",
        "transformed_at": _now(),
        "source_relation": relation,
        "transformation_id": f"unified_source_expansion_v{VERSION}_validation",
        "id_namespace_version": ID_NAMESPACE_VERSION,
        "input_artifact_sha256": f"unified-v{VERSION}-validation-insert",
        "source_record_locator": loc,
        "transformation_version": VERSION,
        "validation_only": True,
    }


def _count_tables(conn: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in ("observation", "observation_component", "source_record"):
            cur.execute(f"SELECT COUNT(*)::bigint FROM canonical_evidence.{table}")
            out[table] = int(cur.fetchone()[0] or 0)
    return out


def _insert_once(cur: Any, *, key: bytes, subject_id: str) -> dict[str, str]:
    oid = synthetic_entity_id(key, "Observation", "obs-1")
    cid = synthetic_entity_id(key, "ObservationComponent", "comp-1")
    sr_obs = synthetic_entity_id(key, "SourceRecord", "sr-obs-1")
    sr_comp = synthetic_entity_id(key, "SourceRecord", "sr-comp-1")
    obs_loc = _loc(key, "analyses_pool", f"{VALIDATION_NONCE}|pool")
    comp_loc = _loc(key, "analyses_constructor", f"{VALIDATION_NONCE}|ctor")
    ts = datetime.now(UTC).replace(microsecond=0)

    prov_obs = _prov(relation="analyses_pool", loc=obs_loc)
    prov_comp = _prov(relation="analyses_constructor", loc=comp_loc)

    cur.execute(
        """
        INSERT INTO canonical_evidence.source_record (
          source_record_id, source_system_id, source_schema, source_relation,
          source_record_locator, locator_scheme, locator_key_version,
          source_created_at, source_updated_at, provenance
        ) VALUES (%s,%s,'quest_digital',%s,%s,'deterministic_hmac_locator',%s,NULL,NULL,%s::jsonb)
        ON CONFLICT (source_record_id) DO NOTHING
        """,
        (sr_obs, SOURCE_B_SYSTEM_ID, "analyses_pool", obs_loc, KEY_VERSION, json.dumps(prov_obs)),
    )
    sr_obs_rc = cur.rowcount
    cur.execute(
        """
        INSERT INTO canonical_evidence.observation (
          observation_id, subject_id, encounter_id, observed_at, recorded_at,
          specimen_collected_at, status, data_level, missingness_reason, provenance
        ) VALUES (%s,%s,NULL,%s,%s,NULL,'final','OBSERVATION_HEADER',NULL,%s::jsonb)
        ON CONFLICT (observation_id) DO NOTHING
        """,
        (oid, subject_id, ts, ts, json.dumps(prov_obs)),
    )
    obs_rc = cur.rowcount
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
            sr_comp,
            SOURCE_B_SYSTEM_ID,
            "analyses_constructor",
            comp_loc,
            KEY_VERSION,
            json.dumps(prov_comp),
        ),
    )
    sr_comp_rc = cur.rowcount
    cur.execute(
        """
        INSERT INTO canonical_evidence.observation_component (
          component_id, observation_id, raw_code, raw_value, numeric_value,
          text_value, raw_unit, provenance
        ) VALUES (%s,%s,%s,%s,%s,NULL,%s,%s::jsonb)
        ON CONFLICT (component_id) DO NOTHING
        """,
        (cid, oid, "53", "1.23", 1.23, "пмоль/л", json.dumps(prov_comp)),
    )
    comp_rc = cur.rowcount
    return {
        "observation_id_prefix": VALIDATION_ID_PREFIX,
        "component_id_prefix": VALIDATION_ID_PREFIX,
        "source_record_obs_rowcount": str(sr_obs_rc),
        "observation_rowcount": str(obs_rc),
        "source_record_comp_rowcount": str(sr_comp_rc),
        "component_rowcount": str(comp_rc),
    }


def run_validation_insert_rollback(repo_root: Path) -> dict[str, Any]:
    """INSERT then prove deltas, second INSERT proves ON CONFLICT, ROLLBACK proves restore."""
    root = Path(repo_root)
    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings

        key = load_hmac_key(root)
        with canonical_connection(load_canonical_settings()) as conn:
            # Pick any existing Source B subject for FK (aggregate-safe: id only, not printed as PII)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT subject_id FROM canonical_evidence.subject
                    WHERE source_system_id = %s
                    ORDER BY subject_id
                    LIMIT 1
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                row = cur.fetchone()
            if not row:
                return {
                    "status": "FAIL",
                    "insertion_rollback_validation_status": "FAIL",
                    "reason": "no_source_b_subject_for_fk",
                }
            subject_id = str(row[0])

            before = _count_tables(conn)
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    first = _insert_once(cur, key=key, subject_id=subject_id)
                mid = _count_tables(conn)
                deltas = {k: mid[k] - before[k] for k in before}
                # Second insert — ON CONFLICT DO NOTHING → rowcounts 0
                with conn.cursor() as cur:
                    second = _insert_once(cur, key=key, subject_id=subject_id)
                after_second = _count_tables(conn)
                idempotent = after_second == mid
                conn.rollback()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                return {
                    "status": "FAIL",
                    "insertion_rollback_validation_status": "FAIL",
                    "error_type": type(exc).__name__,
                }
            after = _count_tables(conn)
            restored = after == before
            first_inserted = all(
                int(first[k]) > 0
                for k in (
                    "observation_rowcount",
                    "component_rowcount",
                )
            )
            second_noop = all(
                int(second[k]) == 0
                for k in (
                    "observation_rowcount",
                    "component_rowcount",
                    "source_record_obs_rowcount",
                    "source_record_comp_rowcount",
                )
            )
            ok = (
                restored
                and first_inserted
                and second_noop
                and idempotent
                and deltas.get("observation", 0) >= 1
                and deltas.get("observation_component", 0) >= 1
            )
            return {
                "status": "PASS" if ok else "FAIL",
                "insertion_rollback_validation_status": "PASS" if ok else "FAIL",
                "rollback": True,
                "counts_before": before,
                "deltas_after_first_insert": deltas,
                "counts_after_rollback": after,
                "counts_unchanged_after_rollback": restored,
                "first_insert_rowcounts": first,
                "second_insert_rowcounts": second,
                "idempotency_on_conflict_proven": second_noop and idempotent,
                "encounter_id_null": True,
                "mapping_status": "CANDIDATE",
                "validation_id_prefix": VALIDATION_ID_PREFIX,
                "no_raw_ab_writes": True,
                "no_pii_in_artifact": True,
                "raw_subject_id_omitted": True,
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "FAIL",
            "insertion_rollback_validation_status": "FAIL",
            "error_type": type(exc).__name__,
        }
