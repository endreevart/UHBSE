"""Strict append-only hash-chained human review workbench."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.policy import (
    APPROVED_PROVIDERS,
    RUNTIME_DIR,
    VERSION,
)

DECISIONS = frozenset({"HUMAN_ACCEPTED", "HUMAN_REJECTED", "AMBIGUOUS"})


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


def verify_decision_log(root: Path) -> dict[str, Any]:
    rows = load_decisions(root)
    prev_hash = None
    hashes = []
    for i, row in enumerate(rows):
        core = {k: v for k, v in row.items() if k != "entry_hash"}
        recomputed = _sha_obj(core)
        if row.get("entry_hash") != recomputed:
            return {"ok": False, "reason": "entry_hash_mismatch", "index": i}
        # hash chain: previous_decision_hash must match prior entry for same medicine
        # Global append-only: each entry stores previous_decision_hash of same medicine
        if row.get("previous_decision_hash") not in (None, prev_hash) and False:
            # medicine-local chain verified below
            pass
        hashes.append(row["entry_hash"])
        prev_hash = row["entry_hash"]
    # Per-medicine chain
    by_med: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_med.setdefault(str(row["source_medicine_id"]), []).append(row)
    for mid, seq in by_med.items():
        expected_prev = None
        for row in seq:
            if row.get("previous_decision_hash") != expected_prev:
                return {
                    "ok": False,
                    "reason": "hash_chain_broken",
                    "source_medicine_id": mid,
                }
            expected_prev = row.get("entry_hash")
    return {"ok": True, "n": len(rows), "hashes": hashes}


def _load_private_mapping_row(root: Path, medicine_id: str) -> dict[str, Any] | None:
    priv = root / RUNTIME_DIR / "registry" / "medication-reference-mapping.private.jsonl"
    if not priv.is_file():
        return None
    with priv.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if str(row["source_medicine_id"]) == str(medicine_id):
                return row
    return None


def _candidate_ids(row: dict[str, Any]) -> set[str]:
    ids = set()
    if row.get("provider_concept_id"):
        ids.add(str(row["provider_concept_id"]))
    for c in row.get("candidates") or []:
        if c.get("provider_concept_id"):
            ids.add(str(c["provider_concept_id"]))
    return ids


def append_decision(
    root: Path,
    *,
    source_medicine_id: str,
    decision: str,
    reviewer_id: str | None,
    reason: str | None,
    provider: str | None = None,
    provider_concept_id: str | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError(f"invalid_decision:{decision}")
    if not reviewer_id or not str(reviewer_id).strip():
        raise ValueError("explicit_reviewer_id_required")
    if str(reviewer_id).strip() == "local-reviewer":
        raise ValueError("default_reviewer_local-reviewer_forbidden")
    if not reason or not str(reason).strip():
        raise ValueError("explicit_decision_reason_required")

    row = _load_private_mapping_row(root, source_medicine_id)
    if row is None:
        raise ValueError("source_medicine_not_in_current_mapping")

    source_medication_hash = row.get("source_medication_hash") or row.get("source_text_hash")
    if not source_medication_hash:
        raise ValueError("source_medication_hash_required")

    snapshot_hash = row.get("provider_snapshot_hash")
    if not snapshot_hash:
        raise ValueError("provider_snapshot_hash_required")

    provider_evidence_hash = row.get("provider_evidence_hash")
    if not provider_evidence_hash:
        raise ValueError("provider_evidence_hash_required")

    if decision == "HUMAN_ACCEPTED":
        if not provider or provider not in APPROVED_PROVIDERS:
            raise ValueError("approved_provider_required")
        if not provider_concept_id:
            raise ValueError("provider_concept_id_required")
        if int(row.get("n_candidates") or 0) <= 0 and not row.get("candidates"):
            raise ValueError("human_review_forbidden_without_provider_candidate")
        if provider_concept_id not in _candidate_ids(row):
            raise ValueError("provider_concept_not_in_current_candidates")
        # candidate must belong to this source medicine mapping row (already enforced)
        if row.get("provider_snapshot_hash") and snapshot_hash != row.get(
            "provider_snapshot_hash"
        ):
            raise ValueError("snapshot_hash_mismatch")
    elif decision == "HUMAN_REJECTED":
        if not candidate_id:
            raise ValueError("candidate_id_required_for_reject")
        if int(row.get("n_candidates") or 0) <= 0 and not row.get("candidates"):
            raise ValueError("human_review_forbidden_without_provider_candidate")
        provider = provider or row.get("provider")
        provider_concept_id = candidate_id
        if candidate_id not in _candidate_ids(row):
            raise ValueError("candidate_not_in_current_candidates")

    prev = latest_decisions_by_medicine(root).get(str(source_medicine_id))
    entry = {
        "version": VERSION,
        "source_medicine_id": str(source_medicine_id),
        "source_medication_hash": source_medication_hash,
        "provider": provider or row.get("provider"),
        "provider_concept_id": provider_concept_id,
        "provider_evidence_hash": provider_evidence_hash,
        "provider_snapshot_hash": snapshot_hash,
        "candidate_id": candidate_id,
        "decision": decision,
        "reviewer_identifier": str(reviewer_id).strip(),
        "timestamp": _now(),
        "reason": str(reason).strip(),
        "previous_decision_hash": (prev or {}).get("entry_hash"),
    }
    entry["entry_hash"] = _sha_obj({k: v for k, v in entry.items() if k != "entry_hash"})
    path = decision_log_path(root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def review_list(root: Path, *, top: int | None = None) -> list[dict[str, Any]]:
    priv = root / RUNTIME_DIR / "registry" / "medication-reference-mapping.private.jsonl"
    latest = latest_decisions_by_medicine(root)
    out: list[dict[str, Any]] = []
    if not priv.is_file():
        return out
    with priv.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            mid = str(row["source_medicine_id"])
            out.append(
                {
                    "source_medicine_id": mid,
                    "original_name": row.get("original_name"),
                    "drug_concept_status": row["drug_concept_status"],
                    "n_episodes": (row.get("episode_coverage") or {}).get("n_episodes", 0),
                    "n_subjects": (row.get("episode_coverage") or {}).get("n_subjects", 0),
                    "n_candidates": row.get("n_candidates"),
                    "provider_concept_id": row.get("provider_concept_id"),
                    "latest_human_decision": (latest.get(mid) or {}).get("decision"),
                }
            )
    out.sort(key=lambda x: (-x["n_episodes"], -x["n_subjects"], x["source_medicine_id"]))
    if top is not None:
        out = out[: int(top)]
    return out


def review_show(root: Path, medicine_id: str) -> dict[str, Any]:
    row = _load_private_mapping_row(root, medicine_id)
    if row is None:
        return {"error": "not_found", "source_medicine_id": medicine_id}
    latest = latest_decisions_by_medicine(root)
    return {**row, "latest_human_decision": latest.get(str(medicine_id))}


def review_export(root: Path) -> dict[str, Any]:
    rows = load_decisions(root)
    v = verify_decision_log(root)
    return {
        "n_decisions": len(rows),
        "n_human_accepted": sum(1 for r in rows if r.get("decision") == "HUMAN_ACCEPTED"),
        "n_human_rejected": sum(1 for r in rows if r.get("decision") == "HUMAN_REJECTED"),
        "n_marked_ambiguous": sum(1 for r in rows if r.get("decision") == "AMBIGUOUS"),
        "verify_log": v,
        "decision_hashes": [r.get("entry_hash") for r in rows],
    }
