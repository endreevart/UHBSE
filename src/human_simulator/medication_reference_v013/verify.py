"""Phase 0 baseline verification for acceptance semantics v0.1.3."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v013.policy import (
    EXPECTED_ESKLP_SNAPSHOT,
    EXPECTED_MEDICINE_IDS,
    EXPECTED_SNAPSHOT_SHA256,
    REGRESSION_REJECTS,
    V011_DECISION_LOG,
    V011_MAPPING,
)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    snap = root / EXPECTED_ESKLP_SNAPSHOT
    sha = _sha_file(snap) if snap.is_file() else None
    rows = []
    with (root / V011_MAPPING).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    log = []
    with (root / V011_DECISION_LOG).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                log.append(json.loads(line))
    rej = {
        (str(r["source_medicine_id"]), str(r.get("candidate_id") or r.get("provider_concept_id")))
        for r in log
        if r.get("decision") == "HUMAN_REJECTED"
    }
    v012_summary = (
        root
        / "artifacts/stage-03-medication-semantic-matcher-v0.1.2"
        / "semantic-matcher-summary.json"
    )
    no_train = True
    if v012_summary.is_file():
        s = json.loads(v012_summary.read_text(encoding="utf-8"))
        no_train = bool(s.get("no_model_training")) and s.get(
            "association_baseline_status"
        ) in {None, "NOT_RUN"}
    return {
        "snapshot_ok": sha == EXPECTED_SNAPSHOT_SHA256,
        "snapshot_sha256": sha,
        "n_source_medicines": len(rows),
        "accounting_ok": len(rows) == EXPECTED_MEDICINE_IDS,
        "status_counts": dict(Counter(r.get("drug_concept_status") for r in rows)),
        "human_accepted": sum(
            1 for r in rows if r.get("drug_concept_status") == "HUMAN_ACCEPTED"
        ),
        "historical_authoritative_accepted": sum(
            1
            for r in rows
            if r.get("drug_concept_status")
            in {"EXACT_PROVIDER_MATCH", "SUPPORTED_TRANSFORM", "HUMAN_ACCEPTED"}
        ),
        "decision_log_n": len(log),
        "decision_log_ok": set(REGRESSION_REJECTS) <= rej and len(log) == 6,
        "rejected_ids": sorted({a for a, _ in rej}),
        "v011_review_zip_exists": (
            root
            / "artifacts/external-review"
            / "stage-03-medication-provider-snapshot-reviewed-concepts-v0.1.1-review.zip"
        ).is_file(),
        "no_model_training_after_v012": no_train,
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
    }
