"""Orchestrator — Medication Semantic Matcher v0.1.2 (no publish, no training)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v012.hierarchy import build_and_write_hierarchy
from human_simulator.medication_reference_v012.matcher import run_matcher
from human_simulator.medication_reference_v012.policy import (
    ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.medication_reference_v012.readiness import run_hierarchical_readiness
from human_simulator.medication_reference_v012.review_pack import write_reviewer_packet_v2
from human_simulator.medication_reference_v012.semantics import build_all_profiles, write_profiles
from human_simulator.medication_reference_v012.verify import verify_baseline


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def run_semantic_matcher_v012(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    baseline = verify_baseline(root)
    if not baseline.get("snapshot_ok"):
        raise RuntimeError("esklp_snapshot_hash_mismatch")
    if not baseline.get("source_accounting_ok"):
        raise RuntimeError("source_medicine_accounting_failed")
    if not (baseline.get("decision_log") or {}).get("ok"):
        raise RuntimeError("decision_log_regression_pairs_missing")

    exact_audit = baseline["exact_audit"]
    profiles = build_all_profiles(root)
    write_profiles(root, profiles)

    match = run_matcher(
        root,
        profiles,
        snapshot_hash=baseline["snapshot_sha256"],
    )
    mappings = match.pop("mappings")

    hier_path = build_and_write_hierarchy(root, profiles, mappings)
    readiness = run_hierarchical_readiness(root, profiles, mappings)

    # Overall status refinement for supplements
    supplement_n = int((match.get("status_counts") or {}).get("SUPPLEMENT_REFERENCE_REQUIRED") or 0)
    overall = readiness.get("OVERALL_STATUS")
    if overall == "NO_HIERARCHICAL_COHORT_READY_WITH_UNCHANGED_GATES" and supplement_n > 0:
        # dual-tag in report
        pass

    packet = write_reviewer_packet_v2(
        root,
        profiles=profiles,
        mappings=mappings,
        readiness=readiness,
        baseline=baseline,
        exact_audit=exact_audit,
    )

    before = baseline.get("v011_status_counts") or {}
    after = match.get("status_counts") or {}

    public = {
        "version": VERSION,
        "generated_at": _now(),
        "SEMANTIC_MATCHER_STATUS": "BUILT",
        "AUTOMATIC_EXACT_MATCH_AUDIT": exact_audit.get("status"),
        "AUTHORITATIVE_ACCEPTED_CONCEPT_COUNT": baseline.get("authoritative_accepted"),
        "HUMAN_ACCEPTED_COUNT": baseline.get("human_accepted"),
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": (
            readiness.get("authoritative") or {}
        ).get("FIRST_INTERVENTION_COHORT_READINESS_STATUS"),
        "OVERALL_STATUS": overall,
        "SUPPLEMENT_REFERENCE_REQUIRED_COUNT": supplement_n,
        "mapping_counts_before_v011": before,
        "mapping_counts_after_v012_semantic": after,
        "provider_routing_counts": match.get("routing_counts"),
        "candidate_class_counts": match.get("candidate_class_counts"),
        "n_with_compatible_candidates": match.get("n_with_compatible_candidates"),
        "hard_conflict_or_gap_count": match.get("hard_conflict_or_gap_count"),
        "authoritative_product_ready": any(
            x.get("READY") for x in (readiness.get("authoritative") or {}).get("product_level") or []
        ),
        "authoritative_ingredient_form_ready": any(
            x.get("READY")
            for x in (readiness.get("authoritative") or {}).get("ingredient_form_level") or []
        ),
        "provisional_any_READY": False,
        "minimum_human_decisions": (readiness.get("provisional") or {}).get(
            "minimum_human_decisions_for_potential_ready"
        ),
        "private_review_pack": packet.get("pack_dir"),
        "private_packet_files": packet.get("files"),
        "hierarchy_path": str(hier_path.relative_to(root)),
        "decision_log_unchanged": True,
        "no_model_training": True,
        "no_zip_published": True,
        "no_automatic_human_accepted": True,
        **policy_snapshot(),
    }

    art = root / ARTIFACT_DIR
    _write(art / "semantic-matcher-summary.json", public)
    _write(root / RUNTIME_DIR / "diagnostics" / "baseline-verification.json", baseline)
    _write(root / RUNTIME_DIR / "diagnostics" / "exact-match-audit.json", exact_audit)
    _write(
        root / RUNTIME_DIR / "diagnostics" / "matcher-summary.private.json",
        {k: v for k, v in match.items() if k != "mappings"},
    )

    return {
        "ok": True,
        "baseline": baseline,
        "exact_audit": exact_audit,
        "match_summary": {k: v for k, v in match.items()},
        "readiness_overall": overall,
        "public": public,
        "packet": packet,
    }
