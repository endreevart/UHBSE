"""Actual Parquet integrity — metadata, FK, cardinality, privacy columns."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.unified_individual_state_v01.policy import (
    REQUIRED_V031_DATASETS,
    V031_MATERIALIZED_DIR,
    VERSION,
)

FORBIDDEN_COLS = frozenset(
    {
        "email",
        "phone",
        "_phone",
        "first_name",
        "last_name",
        "patronymic",
        "full_name",
        "passport",
        "address",
        "path",
        "description",
        "document",
        "raw_text",
        "text_value",
        "patient_id",
        "user_id",
    }
)


def _schema_hash(path: Path) -> str:
    schema = pq.read_schema(path)
    blob = json.dumps(
        [(f.name, str(f.type)) for f in schema], sort_keys=True
    ).encode()
    return hashlib.sha256(blob).hexdigest()


def audit_parquet_integrity(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    mat = root / V031_MATERIALIZED_DIR
    man_path = mat / "materialization-manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.is_file() else {}
    man_ds = man.get("datasets") or {}

    per_ds: dict[str, Any] = {}
    problems: list[str] = []

    subject_ids: set[str] = set()
    if (mat / "research_subject.parquet").is_file():
        st = pq.read_table(
            mat / "research_subject.parquet",
            columns=["research_entity_id", "source_scoped_subject_id"],
        )
        subject_ids = set(st["research_entity_id"].to_pylist())

    encounter_owner: dict[str, str] = {}
    if (mat / "research_encounter.parquet").is_file():
        et = pq.read_table(
            mat / "research_encounter.parquet",
            columns=["research_entity_id", "source_scoped_subject_id"],
        )
        for eid, sid in zip(
            et["research_entity_id"].to_pylist(),
            et["source_scoped_subject_id"].to_pylist(),
            strict=True,
        ):
            encounter_owner[eid] = sid

    for name in REQUIRED_V031_DATASETS:
        path = mat / f"{name}.parquet"
        if not path.is_file():
            problems.append(f"missing:{name}")
            per_ds[name] = {"exists": False, "ok": False}
            continue
        meta_rows = pq.read_metadata(path).num_rows
        man_rows = (man_ds.get(name) or {}).get("rows")
        sch = _schema_hash(path)
        schema_names = [f.name.lower() for f in pq.read_schema(path)]
        forbidden_hits = [c for c in schema_names if c in FORBIDDEN_COLS]

        # primary ID uniqueness
        cols = ["research_entity_id"]
        need_subj = "source_scoped_subject_id" in [f.name for f in pq.read_schema(path)]
        if need_subj:
            cols.append("source_scoped_subject_id")
        need_enc = "encounter_id" in [f.name for f in pq.read_schema(path)]
        if need_enc:
            cols.append("encounter_id")
        t = pq.read_table(path, columns=cols)
        ids = t["research_entity_id"].to_pylist()
        dup = meta_rows - len(set(ids))
        null_subj = 0
        orphan_subj = 0
        enc_mismatch = 0
        if need_subj:
            sids = t["source_scoped_subject_id"].to_pylist()
            null_subj = sum(1 for s in sids if s is None)
            # provenance may have all null subjects — expected for ledger
            if name != "research_provenance":
                for s in sids:
                    if s is not None and s not in subject_ids:
                        orphan_subj += 1
            if need_enc:
                eids = t["encounter_id"].to_pylist()
                for s, e in zip(sids, eids, strict=True):
                    if e is not None and e in encounter_owner and s != encounter_owner[e]:
                        enc_mismatch += 1

        ok = (
            man_rows == meta_rows
            and dup == 0
            and not forbidden_hits
            and (name == "research_provenance" or orphan_subj == 0)
            and enc_mismatch == 0
        )
        if not ok:
            problems.append(f"integrity:{name}")
        per_ds[name] = {
            "exists": True,
            "metadata_rows": meta_rows,
            "manifest_rows": man_rows,
            "rows_equal": man_rows == meta_rows,
            "schema_hash": sch,
            "duplicate_primary_ids": dup,
            "null_subject_id_count": null_subj,
            "orphan_subject_count": orphan_subj,
            "encounter_subject_mismatch": enc_mismatch,
            "forbidden_columns": forbidden_hits,
            "ok": ok,
        }

    # event FK to entity
    event_problems = []
    if (mat / "research_event.parquet").is_file():
        ev = pq.read_table(
            mat / "research_event.parquet",
            columns=["event_id", "event_type", "source_scoped_subject_id"],
        )
        # build entity id sets per type
        type_files = {
            "encounter": "research_encounter",
            "observation": "research_observation",
            "medication_appointment": "research_medication_record",
            "recommendation": "research_recommendation",
            "procedure": "research_procedure",
            "document_reference": "research_document_reference",
        }
        entity_sets = {}
        for et, fn in type_files.items():
            p = mat / f"{fn}.parquet"
            if p.is_file():
                entity_sets[et] = set(
                    pq.read_table(p, columns=["research_entity_id"])[
                        "research_entity_id"
                    ].to_pylist()
                )
        orphan_events = 0
        for eid, et, sid in zip(
            ev["event_id"].to_pylist(),
            ev["event_type"].to_pylist(),
            ev["source_scoped_subject_id"].to_pylist(),
            strict=True,
        ):
            s = entity_sets.get(et)
            if s is not None and eid not in s:
                orphan_events += 1
            if sid is not None and sid not in subject_ids:
                orphan_events += 1
        if orphan_events:
            event_problems.append(f"orphan_events={orphan_events}")
            problems.append("event_fk")

    # cardinality: 1 source recommendation -> <=1 research row (IDs unique already)
    card = {
        "recommendation_unique_ids": per_ds.get("research_recommendation", {}).get(
            "duplicate_primary_ids"
        )
        == 0,
        "document_unique_ids": per_ds.get("research_document_reference", {}).get(
            "duplicate_primary_ids"
        )
        == 0,
        "event_unique_ids": per_ds.get("research_event", {}).get("duplicate_primary_ids") == 0,
    }

    fk = {
        "version": VERSION,
        "subject_universe": len(subject_ids),
        "encounter_universe": len(encounter_owner),
        "event_problems": event_problems,
        "ok": not event_problems,
    }
    dup_orphan = {
        "version": VERSION,
        "per_dataset_duplicates": {
            k: v.get("duplicate_primary_ids") for k, v in per_ds.items()
        },
        "per_dataset_orphan_subjects": {
            k: v.get("orphan_subject_count") for k, v in per_ds.items()
        },
        "ok": all(
            (v.get("duplicate_primary_ids") or 0) == 0
            and (k == "research_provenance" or (v.get("orphan_subject_count") or 0) == 0)
            for k, v in per_ds.items()
            if v.get("exists")
        ),
    }

    integrity_ok = not problems and all(v.get("ok") for v in per_ds.values() if v.get("exists"))
    return {
        "version": VERSION,
        "PRIVATE_PARQUET_INTEGRITY_STATUS": "PASS" if integrity_ok else "FAIL",
        "RESEARCH_ENTITY_LINKAGE_STATUS": "PASS" if fk["ok"] and integrity_ok else "FAIL",
        "DUPLICATE_ORPHAN_AUDIT_STATUS": "PASS" if dup_orphan["ok"] else "FAIL",
        "datasets": per_ds,
        "foreign_key_integrity": fk,
        "duplicate_and_orphan_audit": dup_orphan,
        "source_row_to_research_row_cardinality": card,
        "problems": problems,
        "ok": integrity_ok,
    }
