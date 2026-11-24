"""Append-only decision log — ACCEPTED requires reviewer, reason, evidence hashes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.policy import (
    SCIENTIFICALLY_USABLE,
    TYPED_DECISIONS,
    VERSION,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def decision_log_path(runtime: Path) -> Path:
    return Path(runtime) / "decision-log.jsonl"


def load_decision_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def verify_append_only(path: Path, *, previous_bytes: bytes | None = None) -> dict[str, Any]:
    """If previous snapshot provided, require it to be a strict prefix of current file."""
    if not path.is_file():
        return {"ok": True, "empty": True, "append_only": True, "n": 0}
    cur = path.read_bytes()
    if previous_bytes is None:
        # structural: each line valid JSON with required keys
        rows = load_decision_log(path)
        for r in rows:
            if "mapping_id" not in r or "typed_decision" not in r:
                return {"ok": False, "reason": "malformed_entry"}
        return {"ok": True, "empty": len(rows) == 0, "append_only": True, "n": len(rows)}
    if not cur.startswith(previous_bytes):
        return {"ok": False, "reason": "prior_bytes_not_prefix", "append_only": False}
    if len(cur) < len(previous_bytes):
        return {"ok": False, "reason": "truncated", "append_only": False}
    return {
        "ok": True,
        "append_only": True,
        "n": len(load_decision_log(path)),
        "grew_by_bytes": len(cur) - len(previous_bytes),
    }


def validate_decision_entry(entry: dict[str, Any]) -> None:
    decision = entry.get("typed_decision")
    if decision not in TYPED_DECISIONS:
        raise ValueError(f"invalid_typed_decision:{decision}")
    if not entry.get("mapping_id"):
        raise ValueError("mapping_id_required")
    if decision in SCIENTIFICALLY_USABLE:
        if not str(entry.get("reviewer_id") or "").strip():
            raise ValueError("reviewer_id_required_for_accepted")
        if not str(entry.get("reason") or "").strip():
            raise ValueError("reason_required_for_accepted")
        hashes = entry.get("evidence_file_hashes") or entry.get("evidence_hashes")
        if not hashes:
            raise ValueError("evidence_hashes_required_for_accepted")
        if isinstance(hashes, dict) and not hashes:
            raise ValueError("evidence_hashes_required_for_accepted")
        if isinstance(hashes, list) and not hashes:
            raise ValueError("evidence_hashes_required_for_accepted")


def append_decision(
    path: Path,
    *,
    mapping_id: str,
    source_a_stratum: dict[str, Any],
    source_b_stratum: dict[str, Any] | None,
    typed_decision: str,
    reviewer_id: str | None,
    reviewer_role: str | None,
    reason: str | None,
    evidence_references: list[str] | None,
    evidence_file_hashes: dict[str, str] | list[str] | None,
) -> dict[str, Any]:
    entry = {
        "version": VERSION,
        "mapping_id": mapping_id,
        "source_a_stratum": source_a_stratum,
        "source_b_stratum": source_b_stratum,
        "typed_decision": typed_decision,
        "reviewer_id": reviewer_id,
        "reviewer_role": reviewer_role,
        "reason": reason,
        "evidence_references": evidence_references or [],
        "evidence_file_hashes": evidence_file_hashes or {},
        "timestamp": _now(),
    }
    validate_decision_entry(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return entry


def ingest_decisions(path: Path) -> dict[str, Any]:
    rows = load_decision_log(path)
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        latest[str(r["mapping_id"])] = r
    usable = [
        r
        for r in latest.values()
        if r.get("typed_decision") in SCIENTIFICALLY_USABLE
    ]
    # Rejected must not reappear as open candidates
    rejected_ids = {
        mid
        for mid, r in latest.items()
        if r.get("typed_decision") == "REJECTED"
    }
    return {
        "version": VERSION,
        "n_log_entries": len(rows),
        "n_mappings_with_decision": len(latest),
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": len(usable),
        "usable_accepted": [
            {
                "mapping_id": r["mapping_id"],
                "typed_decision": r["typed_decision"],
                "reviewer_id": r.get("reviewer_id"),
                "timestamp": r.get("timestamp"),
            }
            for r in usable
        ],
        "rejected_mapping_ids": sorted(rejected_ids),
        "DOMAIN_REVIEW_DECISION_STATUS": (
            "HAS_ACCEPTED"
            if usable
            else ("HAS_DECISIONS" if latest else "DOMAIN_REVIEW_DECISION_REQUIRED")
        ),
        "human_decisions_ingested": len(rows),
        "ok": True,
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
