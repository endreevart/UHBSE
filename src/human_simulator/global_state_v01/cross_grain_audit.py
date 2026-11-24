"""Cross-grain split audit for per-grain v0.1.1 assignments."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from human_simulator.global_state_v01.policy import VERSION
from human_simulator.scientific.splits import build_subject_split


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def audit_cross_grain_splits(
    grain_subject_sets: dict[str, list[str]],
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """Compare per-grain build_subject_split roles across grains.

    grain_subject_sets: grain_id -> list of opaque_subject_keys present in that grain's pairs.
    """
    grain_assignments: dict[str, dict[str, str]] = {}
    for gid, subjects in grain_subject_sets.items():
        split = build_subject_split(subjects, seed=seed)
        grain_assignments[gid] = split["assignment"]

    # subject -> {grain_id: role}
    subject_roles: dict[str, dict[str, str]] = defaultdict(dict)
    for gid, asn in grain_assignments.items():
        for sid, role in asn.items():
            subject_roles[sid][gid] = role

    n_unique = len(subject_roles)
    n_multi = sum(1 for roles in subject_roles.values() if len(roles) > 1)
    n_consistent = 0
    n_conflict_subjects = 0
    for roles in subject_roles.values():
        if len(roles) < 2:
            continue
        uniq = set(roles.values())
        if len(uniq) == 1:
            n_consistent += 1
        else:
            n_conflict_subjects += 1

    # grain-pair conflicts
    grain_ids = sorted(grain_assignments)
    n_grain_pairs = 0
    n_grain_pairs_conflict = 0
    for a, b in combinations(grain_ids, 2):
        n_grain_pairs += 1
        shared = set(grain_assignments[a]) & set(grain_assignments[b])
        if any(grain_assignments[a][s] != grain_assignments[b][s] for s in shared):
            n_grain_pairs_conflict += 1

    # Subjects that are train in one grain and val/test in another
    n_train_vs_heldout = 0
    for roles in subject_roles.values():
        role_set = set(roles.values())
        if "train" in role_set and (role_set & {"validation", "test"}):
            n_train_vs_heldout += 1

    # Multi-outcome snapshots that cannot be globally held-out under old scheme:
    # any subject appearing in ≥2 grains with conflicting roles, or train∩heldout
    n_unsafe_multi_outcome_subjects = n_conflict_subjects

    status = (
        "FAIL"
        if n_unique == 0
        else ("CONFLICTS_DETECTED" if n_conflict_subjects > 0 else "PASS")
    )
    return {
        "version": VERSION,
        "CROSS_GRAIN_SPLIT_AUDIT_STATUS": status,
        "method": "rebuild_per_grain_build_subject_split_seed_42",
        "n_grains": len(grain_subject_sets),
        "n_unique_subjects_across_grains": n_unique,
        "n_subjects_in_multiple_grains": n_multi,
        "n_multi_grain_subjects_consistent_role": n_consistent,
        "n_subjects_with_role_conflicts": n_conflict_subjects,
        "n_subjects_train_in_one_grain_heldout_in_another": n_train_vs_heldout,
        "n_grain_pairs": n_grain_pairs,
        "n_grain_pairs_with_cross_role_conflicts": n_grain_pairs_conflict,
        "n_subjects_unsafe_for_global_heldout_multi_outcome": n_unsafe_multi_outcome_subjects,
        "note": (
            "Per-grain build_subject_split is subset-dependent: role is rank within "
            "grain subject set. Conflicts do not invalidate single-outcome backtests, "
            "but forbid using v0.1.1 providers for globally held-out multi-outcome eval."
        ),
        "audit_hash": _hash(
            {
                "n_unique": n_unique,
                "n_conflict": n_conflict_subjects,
                "n_train_vs_heldout": n_train_vs_heldout,
                "n_grain_pairs_conflict": n_grain_pairs_conflict,
            }
        ),
        "subject_keys_published": False,
    }
