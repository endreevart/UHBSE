"""Authoritative canonical subject resolution — no manual double-HMAC for Source B."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.core.ids import entity_id, load_hmac_key, opaque_subject_key
from human_simulator.core.policy import ID_NAMESPACE_VERSION, KEY_VERSION
from human_simulator.stage03.canonical_id import compute_hmac_hex
from human_simulator.unified_individual_state_v011.policy import (
    CANONICAL_MAP_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
)


def source_b_loader_subject_key(key: bytes, patient_id: int) -> str:
    """Exactly the opaque key used by Source B loader (_opaque_b / observation_load)."""
    return compute_hmac_hex(
        key_bytes=key,
        entity="Subject",
        id_namespace_version=ID_NAMESPACE_VERSION,
        source_system="kgz_raw",
        inputs=[str(int(patient_id)), KEY_VERSION],
    )


def source_a_loader_subject_key(key: bytes, patient_id: int) -> str:
    """Source A opaque key (source_subject_key); subject_id = entity_id(Subject, key)."""
    return opaque_subject_key(key, int(patient_id))


def build_canonical_subject_map(root: Path) -> dict[str, Any]:
    """Build (source_system_id, source_subject_key) → subject_id from canonical (RO)."""
    root = Path(root).resolve()
    out = root / CANONICAL_MAP_DIR
    out.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    with canonical_connection(load_canonical_settings()) as conn:
        with conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only=on")
            cur.execute("SET statement_timeout = '120s'")
            cur.execute("SET lock_timeout = '5s'")
            cur.execute(
                """
                SELECT source_system_id, source_subject_key, subject_id
                FROM canonical_evidence.subject
                WHERE source_system_id IN ('magerya_api', 'kgz_raw')
                """
            )
            for ss, skey, sid in cur:
                rows.append(
                    {
                        "source_system_id": str(ss),
                        "source_subject_key": str(skey),
                        "subject_id": str(sid),
                    }
                )

    pq.write_table(
        pa.Table.from_pylist(rows),
        out / "canonical-subject-map.parquet",
        compression="zstd",
    )

    a_map = {
        r["source_subject_key"]: r["subject_id"]
        for r in rows
        if r["source_system_id"] == "magerya_api"
    }
    b_map = {
        r["source_subject_key"]: r["subject_id"]
        for r in rows
        if r["source_system_id"] == "kgz_raw"
    }

    # Research subject universe
    subj = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_subject.parquet",
        columns=["research_entity_id", "source_system"],
    )
    research_ids = {
        sid
        for sid, ss in zip(
            subj["research_entity_id"].to_pylist(),
            subj["source_system"].to_pylist(),
            strict=True,
        )
    }

    # Regression fixtures (no raw PII — only hashes / existence booleans)
    key = load_hmac_key(root)
    fixtures: dict[str, Any] = {"version": VERSION, "cases": []}

    # Probe one A and one B via map consistency without printing raw IDs
    # Use deterministic first keys from maps for structural checks
    if a_map:
        skey_a, sid_a = next(iter(a_map.items()))
        double_wrong_a = entity_id(key, "Subject", sid_a)  # nonsense form
        fixtures["cases"].append(
            {
                "source": "magerya_api",
                "source_subject_key_present": True,
                "subject_id_in_research": sid_a in research_ids,
                "subject_id_equals_source_subject_key": sid_a == skey_a,
                "expected_subject_id_equals_source_subject_key": False,
                "wrong_double_form_in_research": double_wrong_a in research_ids,
            }
        )
    if b_map:
        skey_b, sid_b = next(iter(b_map.items()))
        wrong_double = entity_id(key, "Subject", skey_b)
        fixtures["cases"].append(
            {
                "source": "kgz_raw",
                "source_subject_key_present": True,
                "subject_id_in_research": sid_b in research_ids,
                "subject_id_equals_source_subject_key": sid_b == skey_b,
                "expected_subject_id_equals_source_subject_key": True,
                "wrong_double_hmac_in_research": wrong_double in research_ids,
                "wrong_double_hmac_must_be_absent": True,
            }
        )

    # Live raw→canonical resolution probes (IDs never written)
    from human_simulator.unified_research_layer_v03.connections import (
        connect_source_a,
        connect_source_b,
    )

    live: dict[str, Any] = {}
    ca = connect_source_a(root)
    if ca is not None:
        try:
            with ca.cursor() as cur:
                cur.execute("SET default_transaction_read_only=on")
                cur.execute(
                    "SELECT id FROM magerya_api.account_patient ORDER BY id LIMIT 1"
                )
                pid = int(cur.fetchone()[0])
            okey = source_a_loader_subject_key(key, pid)
            sid = a_map.get(okey)
            live["a"] = {
                "resolved": sid is not None,
                "in_research": bool(sid and sid in research_ids),
                "matches_entity_id_formula": sid == entity_id(key, "Subject", okey)
                if sid
                else False,
            }
        finally:
            try:
                ca.close()
            except Exception:
                pass
    cb = connect_source_b(root)
    if cb is not None:
        try:
            with cb.cursor() as cur:
                cur.execute("SET default_transaction_read_only=on")
                cur.execute(
                    """
                    SELECT u.id FROM public.users u
                    JOIN public.consultations c ON c.patient_id = u.id
                    ORDER BY u.id LIMIT 1
                    """
                )
                uid = int(cur.fetchone()[0])
            skey = source_b_loader_subject_key(key, uid)
            sid = b_map.get(skey)
            wrong = entity_id(key, "Subject", skey)
            live["b"] = {
                "resolved": sid is not None,
                "in_research": bool(sid and sid in research_ids),
                "no_second_entity_id": sid == skey if sid else False,
                "double_hmac_absent": wrong not in research_ids,
            }
        finally:
            try:
                cb.close()
            except Exception:
                pass

    ok = (
        len(a_map) > 0
        and len(b_map) > 0
        and bool((live.get("a") or {}).get("resolved"))
        and bool((live.get("b") or {}).get("resolved"))
        and bool((live.get("b") or {}).get("double_hmac_absent"))
        and all(c.get("subject_id_in_research") for c in fixtures["cases"])
        and all(
            (not c.get("wrong_double_hmac_in_research", False))
            for c in fixtures["cases"]
            if c.get("source") == "kgz_raw"
        )
    )
    summary = {
        "version": VERSION,
        "CANONICAL_SUBJECT_ID_RESOLUTION_STATUS": "PASS" if ok else "FAIL",
        "n_map_rows": len(rows),
        "n_a": len(a_map),
        "n_b": len(b_map),
        "fixtures": fixtures,
        "live_resolution": live,
        "ok": ok,
    }
    (out / "canonical-subject-resolution.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (out / "regression-fixtures.json").write_text(
        json.dumps(fixtures, indent=2) + "\n", encoding="utf-8"
    )
    return {
        **summary,
        "a_map": a_map,
        "b_map": b_map,
        "research_ids": research_ids,
    }


def load_maps(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    path = Path(root) / CANONICAL_MAP_DIR / "canonical-subject-map.parquet"
    t = pq.read_table(path)
    a_map: dict[str, str] = {}
    b_map: dict[str, str] = {}
    for ss, skey, sid in zip(
        t["source_system_id"].to_pylist(),
        t["source_subject_key"].to_pylist(),
        t["subject_id"].to_pylist(),
        strict=True,
    ):
        if ss == "magerya_api":
            a_map[str(skey)] = str(sid)
        elif ss == "kgz_raw":
            b_map[str(skey)] = str(sid)
    return a_map, b_map
