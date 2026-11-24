"""Append-only technical label registry. Review is view-only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v013.hashes import sha_obj
from human_simulator.integrated_research_runtime_v013.policy import LABEL_DIR, VERSION

LABEL_STATUSES = ("CANDIDATE_TECHNICAL_LABEL", "DOMAIN_ACCEPTED", "REJECTED", "SUPERSEDED")
TECHNICAL_LABEL_ID = "NEXT_RECORDED_SOURCE_SPECIFIC_OUTCOME_EXCURSION_WITHIN_HORIZON"


def append_label(registry: list[dict[str, Any]], rec: dict[str, Any]) -> list[dict[str, Any]]:
    rec = dict(rec)
    status = rec.get("status")
    if status not in LABEL_STATUSES:
        raise ValueError("illegal label status")
    if rec.get("clinical") and status != "DOMAIN_ACCEPTED":
        rec["clinical"] = False
        rec["technical"] = True
        rec["status"] = "CANDIDATE_TECHNICAL_LABEL"
        rec["blocked_clinical_without_domain_decision"] = True
    rec["timestamp"] = rec.get("timestamp") or datetime.now(UTC).isoformat()
    rec["reviewer"] = rec.get("reviewer") or "system-technical"
    rec["supersedes"] = rec.get("supersedes")
    rec["evidence_hash"] = sha_obj({k: rec[k] for k in rec if k != "evidence_hash"})
    registry.append(rec)
    return registry


def technical_cannot_become_clinical(registry: list[dict[str, Any]]) -> bool:
    for rec in registry:
        if rec.get("status") != "DOMAIN_ACCEPTED" and rec.get("clinical"):
            return False
        if rec.get("label_id") == TECHNICAL_LABEL_ID and rec.get("clinical"):
            return False
    return True


def persist_registry(root: Path, registry: list[dict[str, Any]]) -> Path:
    path = Path(root) / LABEL_DIR / "label-ontology-registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log = Path(root) / LABEL_DIR / "decision-log.jsonl"
    existing = log.read_text(encoding="utf-8") if log.is_file() else ""
    seen = {line for line in existing.splitlines() if line.strip()}
    with log.open("a", encoding="utf-8") as fh:
        for rec in registry:
            line = json.dumps(rec, sort_keys=True, default=str)
            if line not in seen:
                fh.write(line + "\n")
    return path


def load_registry(root: Path) -> list[dict[str, Any]]:
    path = Path(root) / LABEL_DIR / "label-ontology-registry.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def public_classifier_audit(root: Path) -> dict[str, Any]:
    registry = load_registry(root)
    if not registry:
        registry = append_label(
            [],
            {
                "label_id": TECHNICAL_LABEL_ID,
                "status": "CANDIDATE_TECHNICAL_LABEL",
                "technical": True,
                "clinical": False,
                "not_a_diagnosis": True,
                "reviewer": "system-technical",
            },
        )
        persist_registry(root, registry)
    public = [{k: v for k, v in rec.items() if k != "observable_evidence"} for rec in registry]
    return {
        "version": VERSION,
        "CLASSIFIER_LABEL_ONTOLOGY_STATUS": "PERSISTED",
        "CLASSIFIER_DECISION_LOG_STATUS": "REVIEW_VIEW_ONLY",
        "CLASSIFIER_DOMAIN_REVIEW_WORKBENCH_STATUS": "REVIEW_VIEW_ONLY",
        "TRAJECTORY_EVENT_CLASSIFIER_STATUS": "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_ACCEPTED",
        "not_retrained": True,
        "not_a_diagnosis": True,
        "registry_public": public,
        "append_only": True,
        "ok": True,
    }
