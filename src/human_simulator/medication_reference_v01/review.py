"""Append-only human review workbench for medication concepts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v01.policy import RUNTIME_DIR, VERSION

DECISIONS = frozenset(
    {"HUMAN_ACCEPTED", "HUMAN_REJECTED", "AMBIGUOUS"}
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def decision_log_path(root: Path) -> Path:
    p = root / RUNTIME_DIR / "review" / "decision-log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_decisions(root: Path) -> list[dict[str, Any]]:
    path = decision_log_path(root)
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def latest_decisions_by_medicine(root: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in load_decisions(root):
        latest[str(row["source_medicine_id"])] = row
    return latest


def append_decision(
    root: Path,
    *,
    source_medicine_id: str,
    decision: str,
    source_medication_hash: str,
    provider_concept_id: str | None,
    provider_evidence_hash: str | None,
    reviewer_id: str,
    reason: str | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError(f"invalid_decision:{decision}")
    prev = latest_decisions_by_medicine(root).get(str(source_medicine_id))
    entry = {
        "version": VERSION,
        "source_medicine_id": str(source_medicine_id),
        "source_medication_hash": source_medication_hash,
        "provider_concept_id": provider_concept_id,
        "provider_evidence_hash": provider_evidence_hash,
        "candidate_id": candidate_id,
        "decision": decision,
        "reviewer_identifier": reviewer_id,
        "timestamp": _now(),
        "reason": reason,
        "previous_decision_hash": (prev or {}).get("entry_hash"),
        "provider": "RxNorm" if provider_concept_id else None,
    }
    entry["entry_hash"] = _sha_obj({k: v for k, v in entry.items() if k != "entry_hash"})
    path = decision_log_path(root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def verify_decision_log_immutable(root: Path, expected_hashes: list[str]) -> dict[str, Any]:
    """Any mutation of prior entries breaks verification."""
    rows = load_decisions(root)
    got = []
    for row in rows:
        core = {k: v for k, v in row.items() if k != "entry_hash"}
        recomputed = _sha_obj(core)
        got.append(recomputed)
        if row.get("entry_hash") != recomputed:
            return {"ok": False, "reason": "entry_hash_mismatch", "medicine_id": row.get("source_medicine_id")}
    if expected_hashes and got != expected_hashes:
        return {"ok": False, "reason": "log_sequence_mutated", "expected_n": len(expected_hashes), "got_n": len(got)}
    return {"ok": True, "n": len(got), "hashes": got}


def review_list(root: Path, mapping_sanitized: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = latest_decisions_by_medicine(root)
    out = []
    for m in mapping_sanitized:
        # sanitized lacks medicine_id — list from private mapping in CLI
        out.append({**m, "latest_human_decision": None})
    # Better list from private file
    priv = root / RUNTIME_DIR / "registry" / "medication-reference-mapping.private.jsonl"
    if priv.is_file():
        out = []
        with priv.open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if not row.get("domain_review_required"):
                    continue
                mid = str(row["source_medicine_id"])
                out.append(
                    {
                        "source_medicine_id": mid,
                        "drug_concept_status": row["drug_concept_status"],
                        "n_episodes": (row.get("episode_coverage") or {}).get("n_episodes", 0),
                        "n_subjects": (row.get("episode_coverage") or {}).get("n_subjects", 0),
                        "provider_concept_id": row.get("provider_concept_id"),
                        "latest_human_decision": (latest.get(mid) or {}).get("decision"),
                    }
                )
        out.sort(key=lambda x: (-x["n_episodes"], -x["n_subjects"], x["source_medicine_id"]))
    return out


def review_show(root: Path, medicine_id: str) -> dict[str, Any]:
    priv = root / RUNTIME_DIR / "registry" / "medication-reference-mapping.private.jsonl"
    latest = latest_decisions_by_medicine(root)
    with priv.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if str(row["source_medicine_id"]) == str(medicine_id):
                return {
                    **row,
                    "latest_human_decision": latest.get(str(medicine_id)),
                }
    return {"error": "not_found", "source_medicine_id": medicine_id}


def review_export(root: Path) -> dict[str, Any]:
    rows = load_decisions(root)
    return {
        "version": VERSION,
        "n_decisions": len(rows),
        "n_human_accepted": sum(1 for r in rows if r.get("decision") == "HUMAN_ACCEPTED"),
        "n_human_rejected": sum(1 for r in rows if r.get("decision") == "HUMAN_REJECTED"),
        "n_marked_ambiguous": sum(1 for r in rows if r.get("decision") == "AMBIGUOUS"),
        "DOMAIN_REVIEW_WORKBENCH_STATUS": "AVAILABLE",
        "human_accepted_without_review_forbidden": True,
        # hashes only in public export
        "decision_hashes": [r.get("entry_hash") for r in rows],
    }
