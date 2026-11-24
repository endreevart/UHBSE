"""Load frozen Gate 1A records and recompute the v0.2.2 answer hashes they cite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v022.decisions import canonical_sha256
from human_simulator.stage05_gate_1a_v01.attest import binding
from human_simulator.stage05_gate_1a_completion_v01.policy import (
    ANSWER_RECORD,
    PRIOR_RECORDS,
    SCOPED_QUESTIONS,
    TEMPORAL_LEDGER,
    UNCOMPARABLE,
)


def _load(root: Path, relative: str) -> tuple[Any, str]:
    path = Path(root) / relative
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def load_prior(root: Path) -> dict[str, Any]:
    document, file_sha = _load(root, PRIOR_RECORDS)
    records = document["responses"]
    by_id = {record["question_id"]: record for record in records}
    duplicates = len(records) != len(by_id)
    digests = {record["reviewer_digest"] for record in records}
    roles = {record["role"] for record in records}
    closed_insufficient = [
        record["question_id"]
        for record in records
        if record["attestation"] == "insufficient" and record["closes_question"]
    ]
    return {
        "file_sha256": file_sha,
        "records": records,
        "by_id": by_id,
        "record_count": len(records),
        "accepted_count": sum(record["attestation"] == "accepted" for record in records),
        "insufficient_count": sum(record["attestation"] == "insufficient" for record in records),
        "closed_count": sum(record["closes_question"] for record in records),
        "duplicate_question_ids": duplicates,
        "reviewer_digest_count": len(digests),
        "role_count": len(roles),
        "closed_insufficient": closed_insufficient,
        "scoped": {question_id: by_id[question_id] for question_id in SCOPED_QUESTIONS},
    }


def verify_answer_binding(root: Path, prior: dict[str, Any]) -> dict[str, Any]:
    document, file_sha = _load(root, ANSWER_RECORD)
    answers = document["answers"]
    checked = binding(answers)
    by_hash = {answer["answer_sha256"]: answer["answer_key"] for answer in answers}
    cited = []
    for record in prior["records"]:
        cited.append({
            "question_id": record["question_id"],
            "evidence_sha256": record["evidence_sha256"],
            "answer_key": by_hash.get(record["evidence_sha256"]),
            "ok": record["evidence_sha256"] in by_hash,
        })
    return {
        "ok": checked["ok"] and all(item["ok"] for item in cited),
        "answer_record_sha256": file_sha,
        "answer_record_path": ANSWER_RECORD,
        "recomputed_answer_hashes": checked["answers"],
        "decision_citations": cited,
    }


def temporal_scope(root: Path) -> dict[str, Any]:
    ledger, file_sha = _load(root, TEMPORAL_LEDGER)
    category = ledger["categories"][UNCOMPARABLE]
    components = ledger["uncomparable_components"]
    return {
        "ledger_sha256": file_sha,
        "ledger_path": TEMPORAL_LEDGER,
        "uncomparable_category": UNCOMPARABLE,
        "uncomparable_count": category["count"],
        "uncomparable_components": components,
        "workflow_rule_excludes_uncomparable_rows": True,
    }


def record_sha256(record: dict[str, Any]) -> str:
    return canonical_sha256(record)
