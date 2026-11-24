"""Train-only source-specific outcome vocabulary."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.current_state_representation_v01.policy import (
    MIN_TEST_SUBJECTS,
    MIN_TRAIN_SUBJECTS,
    MIN_TRAIN_TARGETS,
    MIN_VAL_SUBJECTS,
    RUNTIME_DIR,
    V0111_STATES_DIR,
    VERSION,
)


def build_outcome_vocabulary(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / RUNTIME_DIR
    out.mkdir(parents=True, exist_ok=True)
    tg = pq.read_table(
        root / V0111_STATES_DIR / "individual_state_target.parquet",
        columns=[
            "outcome_key",
            "unit",
            "source_system",
            "split_role",
            "source_scoped_subject_id",
            "opaque_target_id",
        ],
    )
    rows = tg.to_pylist()
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r["outcome_key"]
        if key not in by:
            by[key] = {
                "outcome_key": key,
                "unit": r.get("unit") or key.split("::")[-1],
                "source_system": r["source_system"],
                "train_subjects": set(),
                "val_subjects": set(),
                "test_subjects": set(),
                "train_targets": 0,
                "val_targets": 0,
                "test_targets": 0,
            }
        role = r["split_role"]
        sid = r["source_scoped_subject_id"]
        if role == "train":
            by[key]["train_subjects"].add(sid)
            by[key]["train_targets"] += 1
        elif role == "validation":
            by[key]["val_subjects"].add(sid)
            by[key]["val_targets"] += 1
        elif role == "test":
            by[key]["test_subjects"].add(sid)
            by[key]["test_targets"] += 1

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for key, info in sorted(by.items()):
        n_tr_s = len(info["train_subjects"])
        n_va_s = len(info["val_subjects"])
        n_te_s = len(info["test_subjects"])
        reasons = []
        if n_tr_s < MIN_TRAIN_SUBJECTS:
            reasons.append(f"train_subjects<{MIN_TRAIN_SUBJECTS}")
        if info["train_targets"] < MIN_TRAIN_TARGETS:
            reasons.append(f"train_targets<{MIN_TRAIN_TARGETS}")
        if n_va_s < MIN_VAL_SUBJECTS:
            reasons.append(f"val_subjects<{MIN_VAL_SUBJECTS}")
        if n_te_s < MIN_TEST_SUBJECTS:
            reasons.append(f"test_subjects<{MIN_TEST_SUBJECTS}")
        # namespace integrity
        if not (key.startswith("A::") or key.startswith("B::")):
            reasons.append("invalid_namespace")
        if key.startswith("A::") and info["source_system"] != "magerya_api":
            reasons.append("a_namespace_source_mismatch")
        if key.startswith("B::") and info["source_system"] != "kgz_raw":
            reasons.append("b_namespace_source_mismatch")
        entry = {
            "outcome_key": key,
            "unit": info["unit"],
            "source_system": info["source_system"],
            "train_subjects": n_tr_s,
            "train_targets": info["train_targets"],
            "validation_subjects": n_va_s,
            "test_subjects": n_te_s,
        }
        if reasons:
            entry["reject_reasons"] = reasons
            rejected.append(entry)
        else:
            selected.append(entry)

    # Stable order: A then B, then key
    selected.sort(
        key=lambda e: (0 if e["outcome_key"].startswith("A::") else 1, e["outcome_key"])
    )
    order = [e["outcome_key"] for e in selected]
    vocab_hash = hashlib.sha256(
        json.dumps(order, separators=(",", ":")).encode()
    ).hexdigest()

    funnel = {
        "all_outcomes_observed": len(by),
        "selected": len(selected),
        "rejected": len(rejected),
        "selected_a": sum(1 for e in selected if e["outcome_key"].startswith("A::")),
        "selected_b": sum(1 for e in selected if e["outcome_key"].startswith("B::")),
        "rejected_by_reason": defaultdict(int),
    }
    for e in rejected:
        for r in e.get("reject_reasons") or []:
            funnel["rejected_by_reason"][r] += 1
    funnel["rejected_by_reason"] = dict(funnel["rejected_by_reason"])

    doc = {
        "version": VERSION,
        "SOURCE_SPECIFIC_OUTCOME_VOCABULARY_STATUS": "PASS" if selected else "FAIL",
        "selection_on": "train_thresholds_plus_heldout_support",
        "no_test_performance_selection": True,
        "no_a_b_semantic_merge": True,
        "no_unit_conversion": True,
        "outcome_identity": "source + raw_code/analyte + unit",
        "vocabulary_order": order,
        "vocabulary_hash": vocab_hash,
        "selected": selected,
        "rejected_counts": len(rejected),
        "rejected_sample": rejected[:30],
        "funnel": funnel,
        "thresholds": {
            "MIN_TRAIN_SUBJECTS": MIN_TRAIN_SUBJECTS,
            "MIN_TRAIN_TARGETS": MIN_TRAIN_TARGETS,
            "MIN_VAL_SUBJECTS": MIN_VAL_SUBJECTS,
            "MIN_TEST_SUBJECTS": MIN_TEST_SUBJECTS,
        },
        "ok": bool(selected),
    }
    (out / "outcome-vocabulary.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
