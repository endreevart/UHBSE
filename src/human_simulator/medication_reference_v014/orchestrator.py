"""Orchestrator — Intervention Cohort Discovery v0.1.4."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v014.classify import (
    classify_all_compatible,
    verify_baseline,
)
from human_simulator.medication_reference_v014.cluster import (
    build_strict_clusters,
    clusters_to_jsonable,
)
from human_simulator.medication_reference_v014.discovery import (
    evaluate_readiness,
    ingest_typed_accepted,
    rank_top_clusters,
)
from human_simulator.medication_reference_v014.episodes import (
    load_episode_index,
    reconstruct_cluster_coverage,
)
from human_simulator.medication_reference_v014.packets import (
    write_provider_gaps,
    write_reviewer_packet,
)
from human_simulator.medication_reference_v014.policy import (
    ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def run_cohort_discovery_v014(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    baseline = verify_baseline(root)
    if not baseline.get("snapshot_ok") or not baseline.get("accounting_ok"):
        raise RuntimeError("baseline_failed")
    if not baseline.get("compatible_accounting_ok"):
        raise RuntimeError("compatible_candidate_accounting_failed")
    if not baseline.get("decision_log_ok"):
        raise RuntimeError("decision_log_failed")

    classified = classify_all_compatible(root)
    level_counts = dict(Counter(c["typed_level"] for c in classified))
    clusters = build_strict_clusters(classified)
    clusters_doc = clusters_to_jsonable(clusters)

    by_med, split_meta = load_episode_index(root)
    typed_accepted = ingest_typed_accepted(baseline.get("typed_decisions") or [])

    # Coverage for capable clusters + top family for gap context
    coverage_rows = []
    coverage_by_id = {}
    for c in clusters:
        ids = c.get("capable_source_medicine_ids") or []
        if not ids:
            # descriptive coverage for ranking family high-impact clusters
            ids = c.get("source_medicine_ids") or []
        cov = reconstruct_cluster_coverage(
            c, by_med=by_med, split_meta=split_meta, medicine_ids=ids
        )
        coverage_by_id[c["provider_neutral_concept_id"]] = cov
        coverage_rows.append(cov)

    readiness = evaluate_readiness(
        clusters,
        by_med=by_med,
        split_meta=split_meta,
        typed_accepted=typed_accepted,
    )
    top = rank_top_clusters(clusters, coverage_by_id, top_n=3)
    gaps = write_provider_gaps(classified, clusters)

    # Overall status
    min_sets = (readiness.get("provisional") or {}).get("minimum_honest_decision_sets")
    if readiness.get("authoritative", {}).get("any_READY"):
        status = "AUTHORITATIVE_INTERVENTION_COHORT_READY"
    elif min_sets:
        status = "STRICT_INTERVENTION_CONCEPT_CANDIDATES_FOUND"
        # also human review required
        status = "HUMAN_REVIEW_DECISIONS_REQUIRED"
    elif any(c["typed_level"] == "INGREDIENT_FAMILY_ONLY" for c in classified) and not any(
        c["n_capable"] > 0 for c in clusters
    ):
        status = "SUPPLEMENT_REFERENCE_REQUIRED"
    elif any(c["n_capable"] > 0 for c in clusters):
        status = "NO_CAPABLE_DECISION_SET_WITH_CURRENT_EVIDENCE"
    else:
        status = "NO_CAPABLE_DECISION_SET_WITH_CURRENT_EVIDENCE"

    # Prefer HUMAN_REVIEW if capable candidates exist even if gates not met? Spec says:
    # STRICT_INTERVENTION_CONCEPT_CANDIDATES_FOUND when candidates found
    # HUMAN_REVIEW_DECISIONS_REQUIRED when decisions needed
    # If capable clusters exist but min set null -> NO_CAPABLE_DECISION_SET
    if any(c["n_capable"] > 0 for c in clusters):
        if min_sets:
            status = "HUMAN_REVIEW_DECISIONS_REQUIRED"
        else:
            status = "NO_CAPABLE_DECISION_SET_WITH_CURRENT_EVIDENCE"
    elif sum(1 for c in classified if c["typed_level"] == "INGREDIENT_FAMILY_ONLY") > 20:
        status = "SUPPLEMENT_REFERENCE_REQUIRED"

    packet = write_reviewer_packet(
        root,
        classified=classified,
        clusters_doc=clusters_doc,
        coverage_rows=coverage_rows,
        readiness=readiness,
        top_clusters=top,
        gaps=gaps,
        baseline=baseline,
        status=status,
    )

    # 813/809 audit carry-forward
    audit_813_809 = {
        "813": "PRODUCT_IDENTITY_REVIEW_REQUIRED",
        "809": "PRODUCT_IDENTITY_CANDIDATE_TYPED_REVIEW_REQUIRED",
        "auto_accepted": False,
    }
    for c in classified:
        if c["source_medicine_id"] in {"813", "809"}:
            audit_813_809[c["source_medicine_id"] + "_typed_level"] = c["typed_level"]

    public = {
        "version": VERSION,
        "generated_at": _now(),
        "OVERALL_STATUS": status,
        "n_compatible_candidates": len(classified),
        "typed_candidate_counts": level_counts,
        "n_strict_clusters": len(clusters),
        "n_capable_clusters": sum(1 for c in clusters if c["n_capable"] > 0),
        "top_three_clusters": [
            {
                "provider_neutral_concept_id": t["provider_neutral_concept_id"],
                "cluster_key": t["cluster_key"],
                "n_subjects": t["n_subjects"],
                "n_episodes": t["n_episodes"],
                "n_test_subjects": t["n_test_subjects"],
                "n_capable": t["n_capable"],
                "n_grains_passing_gates": t["n_grains_passing_gates"],
            }
            for t in top
        ],
        "minimum_honest_decision_sets": min_sets,
        "authoritative_any_READY": readiness.get("authoritative", {}).get("any_READY"),
        "provisional_any_READY": False,
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": readiness.get("authoritative", {}).get(
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS"
        ),
        "scientifically_usable_accepted": baseline.get("scientifically_usable_accepted"),
        "historical_authoritative_accepted": baseline.get("historical_authoritative_accepted"),
        "audit_813_809": audit_813_809,
        "provider_gaps_top_n": len(gaps.get("top_by_episode_impact") or []),
        "private_review_pack": packet.get("pack_dir"),
        "private_packet_files": packet.get("files"),
        "no_model_training": True,
        "no_zip_published": True,
        "no_automatic_human_accepted": True,
        "v011_decision_log_unchanged": True,
        **policy_snapshot(),
    }

    _write(root / ARTIFACT_DIR / "cohort-discovery-summary.json", public)
    _write(root / RUNTIME_DIR / "diagnostics" / "baseline.json", baseline)
    _write(
        root / RUNTIME_DIR / "diagnostics" / "classified-85.private.json",
        classified,
    )
    _write(root / RUNTIME_DIR / "diagnostics" / "readiness.private.json", readiness)
    _write(
        root / RUNTIME_DIR / "review-pack" / "hierarchical-readiness-impact.json",
        readiness,
    )

    return {
        "ok": True,
        "public": public,
        "baseline": baseline,
        "classified": classified,
        "clusters": clusters,
        "top": top,
        "readiness": readiness,
        "packet": packet,
        "gaps": gaps,
    }
