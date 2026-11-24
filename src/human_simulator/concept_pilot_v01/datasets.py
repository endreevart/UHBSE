"""Dataset construction for concept-bounded technical pilot."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from human_simulator.concept_pilot_v01.policy import (
    EPISODE_JSONL,
    PILOT_COHORTS,
    V01_OUTCOME_GRAINS,
    V014_CLUSTERS,
    VERSION,
)
from human_simulator.intervention_association_v01.models import load_episodes


def verify_predeclared_clusters(root: Path) -> dict[str, Any]:
    doc = json.loads((root / V014_CLUSTERS).read_text(encoding="utf-8"))
    by_id = {c["provider_neutral_concept_id"]: c for c in doc.get("clusters") or []}
    checks = []
    for coh in PILOT_COHORTS:
        cid = coh["provider_neutral_concept_id"]
        c = by_id.get(cid)
        ok = c is not None and c.get("cluster_key") == coh["cluster_key"]
        checks.append(
            {
                "cohort_id": coh["cohort_id"],
                "concept_id": cid,
                "found": c is not None,
                "key_match": ok,
                "capable_ids": list(coh["capable_source_medicine_ids"]),
            }
        )
    return {
        "ok": all(c["key_match"] for c in checks),
        "checks": checks,
        "n_v014_clusters": doc.get("n_clusters"),
    }


def build_cohort_dataset(root: Path, cohort: dict[str, Any]) -> dict[str, Any]:
    episodes = load_episodes(root / EPISODE_JSONL)
    mids = set(str(x) for x in cohort["capable_source_medicine_ids"])
    rows = []
    excluded = Counter()
    seen_eid: set[str] = set()
    for e in episodes:
        if str(e.get("medicine_id")) not in mids:
            continue
        if e.get("same_time_measurement_seen"):
            excluded["same_time"] += 1
            continue
        if e.get("post_value") is None or e.get("pre_value") is None:
            excluded["invalid_outcome"] += 1
            continue
        if not e.get("event_ts"):
            excluded["missing_event_ts"] += 1
            continue
        eid = str(e.get("episode_id") or "")
        if eid in seen_eid:
            excluded["duplicate_episode"] += 1
            continue
        if eid:
            seen_eid.add(eid)
        # sanitize row for private dataset (keep opaque keys only)
        rows.append(
            {
                "episode_id": eid,
                "opaque_subject_key": e["opaque_subject_key"],
                "source_medicine_id": str(e["medicine_id"]),
                "concept_hash": cohort["provider_neutral_concept_id"],
                "strength_stratum": cohort["strength_stratum"],
                "outcome": e["outcome"],
                "unit": e["unit"],
                "pre_value": float(e["pre_value"]),
                "post_value": float(e["post_value"]),
                "horizon_days": float(e.get("horizon_days") or 365),
                "event_to_outcome_days": float(
                    e.get("event_to_post_days") or e.get("horizon_days") or 365
                ),
                "n_prior_measurements": float(e.get("n_prior_measurements") or 0),
                "prior_slope": e.get("prior_slope"),
                "days_since_previous": e.get("days_since_previous"),
                "polypharmacy_flag": float(e.get("polypharmacy_flag") or 0),
                "concurrent_med_count": float(e.get("concurrent_med_count") or 1),
                "medication_event_locator_hash": e.get("medication_event_locator_hash"),
                "pre_locator_hash": e.get("pre_locator_hash"),
                "post_locator_hash": e.get("post_locator_hash"),
                "timestamp_hypothesis": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
                "appointment_is_not_administration": True,
            }
        )

    by_ou: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_ou[(r["outcome"], r["unit"])].append(r)

    grain_stats = []
    for outcome, unit in V01_OUTCOME_GRAINS:
        ge = by_ou.get((outcome, unit), [])
        grain_stats.append(
            {
                "outcome": outcome,
                "unit": unit,
                "n_episodes": len(ge),
                "n_subjects": len({x["opaque_subject_key"] for x in ge}),
            }
        )
    # primary technical outcome = max coverage among V01 grains
    primary = max(grain_stats, key=lambda g: (g["n_episodes"], g["n_subjects"])) if grain_stats else None

    return {
        "version": VERSION,
        "cohort_id": cohort["cohort_id"],
        "role": cohort["role"],
        "provider_neutral_concept_id": cohort["provider_neutral_concept_id"],
        "cluster_key": cohort["cluster_key"],
        "candidate_semantic_label": cohort["candidate_semantic_label"],
        "LABEL_STATUS": "CANDIDATE_SEMANTIC_LABEL",
        "capable_source_medicine_ids": list(cohort["capable_source_medicine_ids"]),
        "n_episodes": len(rows),
        "n_subjects": len({r["opaque_subject_key"] for r in rows}),
        "excluded_counts": dict(excluded),
        "outcome_grain_stats": grain_stats,
        "primary_technical_outcome": primary,
        "episodes": rows,
        "dataset_sha256": hashlib.sha256(
            json.dumps(
                [
                    {
                        "episode_id": r["episode_id"],
                        "concept": r["concept_hash"],
                        "medicine": r["source_medicine_id"],
                        "outcome": r["outcome"],
                        "unit": r["unit"],
                    }
                    for r in sorted(rows, key=lambda x: x["episode_id"])
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }


def write_sanitized_fixture(path: Path, dataset: dict[str, Any]) -> None:
    """Write episode fixture without raw clinical free text; opaque keys only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    slim = {
        k: v
        for k, v in dataset.items()
        if k != "episodes"
    }
    # Include capped episode rows for reproducibility (numeric only)
    slim["episodes"] = dataset["episodes"]
    path.write_text(json.dumps(slim, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
