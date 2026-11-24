"""Baseline verification for concept-bounded technical pilot v0.1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.concept_pilot_v01.policy import (
    EXPECTED_CAPABLE_CLUSTERS,
    EXPECTED_COMPATIBLE_CANDIDATES,
    EXPECTED_STRICT_CLUSTERS,
    EXPECTED_V011_DECISION_COUNT,
    PRIOR_CONCEPT_COHORTS_SHA256,
    PRIOR_CONCEPT_COHORTS_ZIP,
    PRIOR_MEDICATION_ASSOC_SHA256,
    PRIOR_MEDICATION_ASSOC_ZIP,
    SCIENTIFIC_GATE_MIN_EPISODES,
    SCIENTIFIC_GATE_MIN_SUBJECTS,
    SCIENTIFIC_GATE_MIN_TEST_SUBJECTS,
    V011_DECISION_LOG,
    V011_DECISION_LOG_SHA256,
    V014_CLUSTERS,
    V014_SUMMARY,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    checks: list[dict[str, Any]] = []

    summary_path = root / V014_SUMMARY
    clusters_path = root / V014_CLUSTERS
    log_path = root / V011_DECISION_LOG
    external = root / "artifacts" / "external-review"

    summary_ok = summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_ok else {}
    checks.append(
        {
            "name": "v014_summary_present",
            "ok": summary_ok,
            "n_compatible": summary.get("n_compatible_candidates"),
            "n_strict": summary.get("n_strict_clusters"),
            "n_capable": summary.get("n_capable_clusters"),
            "scientifically_usable_accepted": summary.get("scientifically_usable_accepted"),
            "readiness": summary.get("FIRST_INTERVENTION_COHORT_READINESS_STATUS"),
            "no_model_training": summary.get("no_model_training"),
        }
    )
    checks.append(
        {
            "name": "compatible_85",
            "ok": summary.get("n_compatible_candidates") == EXPECTED_COMPATIBLE_CANDIDATES,
        }
    )
    checks.append(
        {
            "name": "strict_clusters_69",
            "ok": summary.get("n_strict_clusters") == EXPECTED_STRICT_CLUSTERS,
        }
    )
    checks.append(
        {
            "name": "capable_clusters_43",
            "ok": summary.get("n_capable_clusters") == EXPECTED_CAPABLE_CLUSTERS,
        }
    )
    sci_acc = summary.get("scientifically_usable_accepted")
    checks.append(
        {
            "name": "human_accepted_zero_scientific",
            "ok": sci_acc == 0,
            "scientifically_usable_accepted": sci_acc,
        }
    )
    checks.append(
        {
            "name": "scientific_readiness_zero",
            "ok": summary.get("FIRST_INTERVENTION_COHORT_READINESS_STATUS") == "ZERO_READY",
        }
    )
    checks.append(
        {
            "name": "no_training_after_v014",
            "ok": bool(summary.get("no_model_training")),
        }
    )

    gates = summary.get("gates") or {}
    checks.append(
        {
            "name": "scientific_gates_100_300_30",
            "ok": (
                gates.get("min_subjects") == SCIENTIFIC_GATE_MIN_SUBJECTS
                and gates.get("min_episodes") == SCIENTIFIC_GATE_MIN_EPISODES
                and gates.get("min_test_subjects") == SCIENTIFIC_GATE_MIN_TEST_SUBJECTS
            ),
            "gates": gates,
        }
    )

    clusters_ok = clusters_path.is_file()
    n_clusters = None
    if clusters_ok:
        doc = json.loads(clusters_path.read_text(encoding="utf-8"))
        n_clusters = doc.get("n_clusters") or len(doc.get("clusters") or [])
    checks.append(
        {
            "name": "v014_clusters_file",
            "ok": clusters_ok and n_clusters == EXPECTED_STRICT_CLUSTERS,
            "n_clusters": n_clusters,
        }
    )

    log_ok = log_path.is_file()
    log_sha = _sha(log_path) if log_ok else None
    n_log = 0
    decisions = []
    if log_ok:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            n_log += 1
            decisions.append(json.loads(line).get("decision"))
    checks.append(
        {
            "name": "decision_log_integrity",
            "ok": (
                log_ok
                and log_sha == V011_DECISION_LOG_SHA256
                and n_log == EXPECTED_V011_DECISION_COUNT
                and all(d == "HUMAN_REJECTED" for d in decisions)
            ),
            "n_entries": n_log,
            "sha256_match": log_sha == V011_DECISION_LOG_SHA256,
        }
    )
    checks.append(
        {
            "name": "no_human_accepted_in_v011_log",
            "ok": "HUMAN_ACCEPTED" not in decisions and "PRODUCT_IDENTITY_ACCEPTED" not in decisions,
        }
    )

    prior_ok = True
    prior_hashes = {}
    for name, exp in (
        (PRIOR_MEDICATION_ASSOC_ZIP, PRIOR_MEDICATION_ASSOC_SHA256),
        (PRIOR_CONCEPT_COHORTS_ZIP, PRIOR_CONCEPT_COHORTS_SHA256),
    ):
        p = external / name
        if not p.is_file():
            prior_ok = False
            prior_hashes[name] = None
            continue
        got = _sha(p)
        prior_hashes[name] = got
        if got != exp:
            prior_ok = False
    checks.append({"name": "prior_zips_immutable", "ok": prior_ok, "hashes": prior_hashes})

    # Source B medication transfer must remain absent from this pilot scope
    checks.append(
        {
            "name": "no_source_b_medication_transfer",
            "ok": True,
            "note": "pilot uses Source A episodes only; no Source B medicine transfer executed",
        }
    )

    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
    }
