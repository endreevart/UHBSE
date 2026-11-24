"""Subject-level exploratory splits (v0.1.1)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from human_simulator.scientific.policy import (
    SEED,
    SPLIT_CLASS,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
)


def build_subject_split(
    subject_keys: list[str],
    *,
    seed: int = SEED,
) -> dict[str, Any]:
    """Deterministic subject-level split before outcome selection."""
    subjects = sorted(set(subject_keys))
    ranked = sorted(
        subjects,
        key=lambda sid: hashlib.sha256(f"split|{seed}|{sid}".encode()).hexdigest(),
    )
    n = len(ranked)
    n_train = max(1, int(n * SPLIT_TRAIN)) if n else 0
    n_val = max(1, int(n * SPLIT_VAL)) if n >= 3 else (1 if n == 2 else 0)
    if n_train + n_val >= n and n >= 3:
        n_val = max(1, n - n_train - 1)
    if n >= 3 and (n - n_train - n_val) < 1:
        if n_val > 1:
            n_val -= 1
        else:
            n_train = max(1, n_train - 1)
    assignment: dict[str, str] = {}
    for i, sid in enumerate(ranked):
        if i < n_train:
            assignment[sid] = "train"
        elif i < n_train + n_val:
            assignment[sid] = "validation"
        else:
            assignment[sid] = "test"

    sets = {
        "train": sorted(s for s, a in assignment.items() if a == "train"),
        "validation": sorted(s for s, a in assignment.items() if a == "validation"),
        "test": sorted(s for s, a in assignment.items() if a == "test"),
    }
    overlap = {
        "train_validation": sorted(set(sets["train"]) & set(sets["validation"])),
        "train_test": sorted(set(sets["train"]) & set(sets["test"])),
        "validation_test": sorted(set(sets["validation"]) & set(sets["test"])),
    }
    overlap_count = sum(len(v) for v in overlap.values())
    split_hash = hashlib.sha256(
        json.dumps({"seed": seed, "assignment": assignment}, sort_keys=True).encode()
    ).hexdigest()
    return {
        "seed": seed,
        "split_class": SPLIT_CLASS,
        "assignment": assignment,
        "sets": sets,
        "n_subjects": {k: len(v) for k, v in sets.items()} | {"total": n},
        "overlap_detail_counts": {k: len(v) for k, v in overlap.items()},
        "subject_overlap_zero": overlap_count == 0,
        "split_hash": split_hash,
        "ok": overlap_count == 0 and n >= 3,
    }


def assign_pairs_to_splits(
    pairs: list[dict[str, Any]],
    subject_split: dict[str, Any],
) -> dict[str, Any]:
    assignment = subject_split["assignment"]
    buckets: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    unknown = 0
    for p in pairs:
        split = assignment.get(p["opaque_subject_key"])
        if split is None:
            unknown += 1
            continue
        buckets[split].append(p)
    # locator overlap across splits
    def locators(name: str) -> set[str]:
        out: set[str] = set()
        for p in buckets[name]:
            prov = p.get("provenance") or {}
            for key in ("t0_component_id", "t1_component_id"):
                val = prov.get(key)
                if val:
                    out.add(str(val))
        return out

    loc_overlap = {
        "train_validation": len(locators("train") & locators("validation")),
        "train_test": len(locators("train") & locators("test")),
        "validation_test": len(locators("validation") & locators("test")),
    }
    manifest = {
        "seed": subject_split["seed"],
        "split_class": SPLIT_CLASS,
        "split_fractions": {"train": SPLIT_TRAIN, "validation": SPLIT_VAL, "test": SPLIT_TEST},
        "n_subjects_eligible_split": subject_split["n_subjects"],
        "n_subjects": {
            "train": len({p["opaque_subject_key"] for p in buckets["train"]}),
            "validation": len({p["opaque_subject_key"] for p in buckets["validation"]}),
            "test": len({p["opaque_subject_key"] for p in buckets["test"]}),
            "total": len({p["opaque_subject_key"] for p in pairs}),
        },
        "n_pairs": {
            "train": len(buckets["train"]),
            "validation": len(buckets["validation"]),
            "test": len(buckets["test"]),
            "total": len(pairs),
        },
        "contains_raw_subject_ids": False,
        "publishes_subject_hash_lists": False,
        "unknown_subjects_in_pairs": unknown,
    }
    verification = {
        "subject_overlap_zero": subject_split["subject_overlap_zero"],
        "locator_overlap_counts": loc_overlap,
        "locator_overlap_zero": all(v == 0 for v in loc_overlap.values()),
        "split_hash": subject_split["split_hash"],
        "split_status": SPLIT_CLASS,
        "ok": subject_split["ok"] and all(v == 0 for v in loc_overlap.values()),
    }
    return {
        "buckets": buckets,
        "manifest": manifest,
        "verification": verification,
        "subject_split": {
            "seed": subject_split["seed"],
            "split_hash": subject_split["split_hash"],
            "n_subjects": subject_split["n_subjects"],
            "split_class": SPLIT_CLASS,
            # do not embed full subject key lists in published verification
        },
    }


def build_splits(pairs: list[dict[str, Any]], *, seed: int = SEED) -> dict[str, Any]:
    """Legacy helper for tests: split from pairs' subjects then assign."""
    subjects = sorted({p["opaque_subject_key"] for p in pairs})
    subject_split = build_subject_split(subjects, seed=seed)
    return assign_pairs_to_splits(pairs, subject_split)


def assert_no_subject_overlap(train_ids: set[str], test_ids: set[str]) -> bool:
    return train_ids.isdisjoint(test_ids)
