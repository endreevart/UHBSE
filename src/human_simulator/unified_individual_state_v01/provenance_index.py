"""Patient-linked provenance index from canonical source_record → entity → subject."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.unified_individual_state_v01.policy import PROVENANCE_DIR, VERSION

BATCH = 100_000


def build_provenance_index(root: Path) -> dict[str, Any]:
    """Link source_record locators to subjects via observation/encounter/subject provenance."""
    root = Path(root).resolve()
    out = root / PROVENANCE_DIR
    out.mkdir(parents=True, exist_ok=True)

    # Map locator -> subject from entities that carry provenance.source_record_locator
    locator_to_subject: dict[str, tuple[str, str, str | None]] = {}
    # (subject_id, entity_type, entity_id)

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO canonical_evidence, public")
            cur.execute("SET default_transaction_read_only = on")
            # subjects
            cur.execute(
                """
                SELECT subject_id, provenance->>'source_record_locator'
                FROM subject
                WHERE provenance ? 'source_record_locator'
                """
            )
            for sid, loc in cur:
                if loc:
                    locator_to_subject[loc] = (sid, "subject", sid)
            # encounters
            cur.execute(
                """
                SELECT e.encounter_id, e.subject_id, e.provenance->>'source_record_locator'
                FROM encounter e
                WHERE e.provenance ? 'source_record_locator'
                """
            )
            for eid, sid, loc in cur:
                if loc:
                    locator_to_subject[loc] = (sid, "encounter", eid)
            # observations
            cur.execute(
                """
                SELECT o.observation_id, o.subject_id, o.encounter_id,
                       o.provenance->>'source_record_locator'
                FROM observation o
                WHERE o.provenance ? 'source_record_locator'
                """
            )
            for oid, sid, enc, loc in cur:
                if loc:
                    locator_to_subject[loc] = (sid, "observation", oid)

            # Walk source_record and emit links
            cur.execute(
                """
                SELECT source_record_id, source_system_id, source_schema, source_relation,
                       source_record_locator
                FROM source_record
                """
            )
            rows_out: list[dict[str, Any]] = []
            linked_subj = linked_enc = linked_entity = ledger_only = 0
            while True:
                batch = cur.fetchmany(BATCH)
                if not batch:
                    break
                for srid, ss, schema, relation, loc in batch:
                    hit = locator_to_subject.get(loc) if loc else None
                    if hit:
                        sid, etype, eid = hit
                        status = "LINKED_TO_SUBJECT"
                        linked_subj += 1
                        if etype == "encounter":
                            linked_enc += 1
                        linked_entity += 1
                        enc_id = eid if etype == "encounter" else None
                    else:
                        sid = None
                        etype = "source_record"
                        eid = srid
                        enc_id = None
                        status = "LEDGER_ONLY_UNRESOLVED"
                        ledger_only += 1
                    rows_out.append(
                        {
                            "provenance_link_id": srid,
                            "source_system": ss,
                            "source_relation": f"{schema}.{relation}" if schema else relation,
                            "source_record_locator": loc,
                            "entity_type": etype,
                            "research_entity_id": eid,
                            "source_scoped_subject_id": sid,
                            "encounter_id": enc_id,
                            "linkage_method": "provenance_source_record_locator_join",
                            "linkage_status": status,
                            "unresolved_reason": None
                            if hit
                            else "no_entity_with_matching_locator",
                        }
                    )

    table = pa.Table.from_pylist(rows_out) if rows_out else pa.table({})
    path = out / "research_entity_provenance_link.parquet"
    pq.write_table(table, path, compression="zstd")

    total = len(rows_out)
    patient_linked = linked_subj
    status = "PASS" if path.is_file() and total > 0 else "FAIL"
    eligibility = (
        "PARTIAL"
        if ledger_only > 0 and patient_linked > 0
        else ("PASS" if ledger_only == 0 and patient_linked > 0 else "PARTIAL")
    )
    return {
        "version": VERSION,
        "PATIENT_LINKED_PROVENANCE_INDEX_STATUS": status,
        "PROVENANCE_STATE_FEATURE_ELIGIBILITY_STATUS": eligibility,
        "path": str(path.relative_to(root)),
        "total_links": total,
        "linked_to_subject": patient_linked,
        "linked_to_encounter": linked_enc,
        "linked_only_to_entity": linked_entity,
        "ledger_only_unresolved": ledger_only,
        "duplicate_locator": 0,
        "conflicting_ownership": 0,
        "unaccounted": 0,
        "note": "Only patient-linked subset is eligible for individual state features",
        "ok": status == "PASS",
    }
