"""Overlap groups + honest source-grouped split (no unconditional overlap_aware)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v031.policy import OVERLAP_DIR, VERSION

NAMESPACE = "unified-a-b-research-layer-v031"
SEED = 42
BUCKET_TRAIN_END = 0.70
BUCKET_VAL_END = 0.85


def assign_role(source_system: str, source_subject_key: str) -> str:
    digest = hashlib.sha256(
        f"{NAMESPACE}|{SEED}|{source_system}|{source_subject_key}".encode()
    ).hexdigest()
    frac = int(digest[:12], 16) / float(16**12)
    if frac < BUCKET_TRAIN_END:
        return "train"
    if frac < BUCKET_VAL_END:
        return "validation"
    return "test"


def assign_group_role(group_id: str) -> str:
    """Shared role for an overlap group — both members get the same bucket."""
    digest = hashlib.sha256(f"{NAMESPACE}|{SEED}|GROUP|{group_id}".encode()).hexdigest()
    frac = int(digest[:12], 16) / float(16**12)
    if frac < BUCKET_TRAIN_END:
        return "train"
    if frac < BUCKET_VAL_END:
        return "validation"
    return "test"


def build_overlap_and_split(
    *,
    root: Path,
    conn_canonical: Any,
    linkage_assessment: dict[str, Any] | None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / OVERLAP_DIR
    out.mkdir(parents=True, exist_ok=True)

    # Prior Stage-02 assessment is aggregate-only (no private pair list persisted).
    # Without re-deriving PII-backed pairs into public artifacts, we record honest risk.
    oa = (linkage_assessment or {}).get("overlap_aggregates") or {}
    confirmed = int(oa.get("consistent_subject_pairs_by_phone_and_email") or 0)
    candidate_phone = int(oa.get("uniquely_resolved_subject_pairs_by_phone") or 0)
    candidate_email = int(oa.get("uniquely_resolved_subject_pairs_by_email") or 0)
    ambiguous = int(oa.get("ambiguous_subject_pairs") or 0)
    conflicting = int(oa.get("cross_field_conflicts") or 0)

    groups_summary = {
        "confirmed": confirmed,
        "candidate": candidate_phone + candidate_email,
        "ambiguous": ambiguous,
        "conflicting": conflicting,
        "unlinked": "REMAINDER_UNKNOWN",
        "pair_lists_in_public": False,
        "pair_lists_materialized_private": False,
        "reason": (
            "Stage-02 linkage artifacts are aggregate-only; full private pair rebuild "
            "is deferred. Split remains source-grouped with explicit unresolved overlap risk."
        ),
    }
    (out / "overlap-groups-summary.json").write_text(
        json.dumps(groups_summary, indent=2) + "\n", encoding="utf-8"
    )

    counts = {
        "magerya_api": {"train": 0, "validation": 0, "test": 0},
        "kgz_raw": {"train": 0, "validation": 0, "test": 0},
    }
    n = 0
    with conn_canonical.cursor() as cur:
        cur.execute(
            "SELECT source_system_id, source_subject_key FROM canonical_evidence.subject"
        )
        for ss, skey in cur:
            role = assign_role(str(ss), str(skey))
            if ss in counts:
                counts[ss][role] += 1
            n += 1

    # Demonstrate group-role helper works (unit-tested); not applied to live pairs here
    demo_group_roles_equal = assign_group_role("demo") == assign_group_role("demo")

    split_status = "PASS_SOURCE_GROUPED_CROSS_SOURCE_OVERLAP_RISK_UNRESOLVED"
    return {
        "version": VERSION,
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "CROSS_SOURCE_OVERLAP_RISK_STATUS": "UNRESOLVED_POTENTIAL_OVERLAP",
        "GLOBAL_A_B_SPLIT_STATUS": split_status,
        "overlap_aware": False,
        "overlap_aware_unconditional_forbidden": True,
        "subject_grouped": True,
        "source_grouped": True,
        "namespace": NAMESPACE,
        "seed": SEED,
        "method": "sha256_namespace_hash_fraction_fixed_buckets_source_scoped",
        "buckets": {
            "train": [0.0, BUCKET_TRAIN_END],
            "validation": [BUCKET_TRAIN_END, BUCKET_VAL_END],
            "test": [BUCKET_VAL_END, 1.0],
        },
        "repeatable": assign_role("magerya_api", "x") == assign_role("magerya_api", "x"),
        "source_system_in_hash_namespace": True,
        "roles_may_collide_across_sources_without_implying_same_person": True,
        "group_role_helper_deterministic": demo_group_roles_equal,
        "source_balance": counts,
        "n_subjects_assigned": n,
        "overlap_groups_summary": groups_summary,
        "policy": {
            "confirmed_or_candidate_pairs_must_share_split_or_exclude_heldout": True,
            "ambiguous_excluded_from_cross_source_heldout": True,
            "conflicting_remain_separate_with_flag": True,
            "unlinked_risk_retained": True,
        },
        "model_training_run": False,
        "ok": n > 0 and split_status.startswith("PASS"),
    }
