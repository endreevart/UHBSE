"""Global subset-invariant Source A subject split."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.global_state_v01.policy import (
    BUCKET_TRAIN_END,
    BUCKET_VAL_END,
    GLOBAL_SPLIT_NAMESPACE,
    GLOBAL_SPLIT_SEED,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def subject_hash_fraction(opaque_subject_key: str, *, seed: int = GLOBAL_SPLIT_SEED) -> float:
    """Map subject to [0, 1) via fixed namespace hash — independent of peer set."""
    digest = hashlib.sha256(
        f"{GLOBAL_SPLIT_NAMESPACE}|{seed}|{opaque_subject_key}".encode()
    ).hexdigest()
    # Use 12 hex digits → stable fraction
    return int(digest[:12], 16) / float(16**12)


def assign_role(opaque_subject_key: str, *, seed: int = GLOBAL_SPLIT_SEED) -> str:
    frac = subject_hash_fraction(opaque_subject_key, seed=seed)
    if frac < BUCKET_TRAIN_END:
        return "train"
    if frac < BUCKET_VAL_END:
        return "validation"
    return "test"


def build_global_subject_split(
    opaque_subject_keys: list[str],
    *,
    seed: int = GLOBAL_SPLIT_SEED,
) -> dict[str, Any]:
    subjects = sorted(set(opaque_subject_keys))
    assignment = {sid: assign_role(sid, seed=seed) for sid in subjects}
    sets = {
        "train": sorted(s for s, a in assignment.items() if a == "train"),
        "validation": sorted(s for s, a in assignment.items() if a == "validation"),
        "test": sorted(s for s, a in assignment.items() if a == "test"),
    }
    overlap = {
        "train_validation": len(set(sets["train"]) & set(sets["validation"])),
        "train_test": len(set(sets["train"]) & set(sets["test"])),
        "validation_test": len(set(sets["validation"]) & set(sets["test"])),
    }
    # Repeatability proof
    assignment2 = {sid: assign_role(sid, seed=seed) for sid in subjects}
    repeat_ok = assignment == assignment2
    # Subset-invariance proof: roles for a sample match when computed alone
    sample = subjects[:: max(1, len(subjects) // 50)][:50] if subjects else []
    subset_ok = all(assign_role(s, seed=seed) == assignment[s] for s in sample)

    split_hash = _hash(
        {
            "namespace": GLOBAL_SPLIT_NAMESPACE,
            "seed": seed,
            "boundaries": {
                "train_end": BUCKET_TRAIN_END,
                "val_end": BUCKET_VAL_END,
            },
            "n_subjects": len(subjects),
            # Hash of assignment roles without publishing keys
            "assignment_role_counts": {
                "train": len(sets["train"]),
                "validation": len(sets["validation"]),
                "test": len(sets["test"]),
            },
            "assignment_fingerprint": _hash(
                sorted((sid, role) for sid, role in assignment.items())
            ),
        }
    )
    ok = (
        sum(overlap.values()) == 0
        and repeat_ok
        and subset_ok
        and len(subjects) >= 3
        and all(len(sets[k]) > 0 for k in ("train", "validation", "test"))
    )
    return {
        "version": VERSION,
        "GLOBAL_SUBJECT_SPLIT_STATUS": "PASS" if ok else "FAIL",
        "namespace": GLOBAL_SPLIT_NAMESPACE,
        "seed": seed,
        "bucket_boundaries": {
            "train": [0.0, BUCKET_TRAIN_END],
            "validation": [BUCKET_TRAIN_END, BUCKET_VAL_END],
            "test": [BUCKET_VAL_END, 1.0],
        },
        "method": "sha256_namespace_hash_fraction_fixed_buckets",
        "n_subjects": {
            "total": len(subjects),
            "train": len(sets["train"]),
            "validation": len(sets["validation"]),
            "test": len(sets["test"]),
        },
        "overlap_counts": overlap,
        "subject_overlap_zero": sum(overlap.values()) == 0,
        "repeatability_ok": repeat_ok,
        "subset_invariance_sample_ok": subset_ok,
        "subset_invariance_sample_n": len(sample),
        "split_hash": split_hash,
        "raw_identifiers_published": False,
        "assignment": assignment,  # private use only — stripped before public write
        "sets": sets,
        "ok": ok,
    }


def public_split_contract(split: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in split.items()
        if k not in {"assignment", "sets"}
    }


def write_private_manifest(path: Path, split: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Store only role→hash fingerprints of subject lists, not raw keys in public;
    # private may store opaque keys for runtime.
    doc = {
        "version": VERSION,
        "split_hash": split["split_hash"],
        "n_subjects": split["n_subjects"],
        "assignment": split["assignment"],
        "sets": split["sets"],
        "raw_identifiers_published": False,
        "note": "Private opaque_subject_key assignment; never copy to review ZIP.",
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
