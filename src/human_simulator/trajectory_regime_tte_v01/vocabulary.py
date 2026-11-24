"""Train-only outcome vocabulary; held-out counts only for evidence tiers."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.trajectory_regime_tte_v01.policy import (
    MIN_TEST_SUBJECTS_EVAL,
    MIN_TRAIN_SUBJECTS,
    MIN_TRAIN_TARGETS,
    MIN_VAL_SUBJECTS_EVAL,
    RUNTIME_DIR,
    V0111_STATES_DIR,
    VERSION,
)

# Numeric/data-quality heuristics for inventory (not clinical)
_SUSPICIOUS_UNIT = re.compile(r"^(null|none|nan|n/?a|-|\s*)$", re.I)
_NON_NUMERIC_CODE_HINT = re.compile(r"(текст|comment|note|free.?text)", re.I)


def build_train_only_vocabulary(root: Path) -> dict[str, Any]:
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
            "target_value",
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
                "train_values": [],
            }
        role = r["split_role"]
        sid = r["source_scoped_subject_id"]
        if role == "train":
            by[key]["train_subjects"].add(sid)
            by[key]["train_targets"] += 1
            if r.get("target_value") is not None:
                by[key]["train_values"].append(float(r["target_value"]))
        elif role == "validation":
            by[key]["val_subjects"].add(sid)
            by[key]["val_targets"] += 1
        elif role == "test":
            by[key]["test_subjects"].add(sid)
            by[key]["test_targets"] += 1

    inventory: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    dq_flagged = 0

    for key, info in sorted(by.items()):
        unit = info["unit"] or ""
        n_tr_s = len(info["train_subjects"])
        n_va_s = len(info["val_subjects"])
        n_te_s = len(info["test_subjects"])
        dq_reasons = []
        if _SUSPICIOUS_UNIT.match(unit.strip() if unit else ""):
            dq_reasons.append("suspicious_unit")
        if _NON_NUMERIC_CODE_HINT.search(key):
            dq_reasons.append("non_numeric_code_hint")
        vals = info["train_values"]
        if vals:
            # constant / extreme sparsity of unique values
            uniq = len(set(round(v, 6) for v in vals))
            if uniq <= 1 and len(vals) >= 50:
                dq_reasons.append("constant_train_value")
        if dq_reasons:
            dq_flagged += 1

        entry = {
            "outcome_key": key,
            "unit": unit,
            "source_system": info["source_system"],
            "train_subjects": n_tr_s,
            "train_targets": info["train_targets"],
            "validation_subjects": n_va_s,
            "test_subjects": n_te_s,
            "data_quality_flags": dq_reasons,
            "evidence_tier": (
                "EVALUABLE_TECHNICAL_HELDOUT"
                if n_va_s >= MIN_VAL_SUBJECTS_EVAL and n_te_s >= MIN_TEST_SUBJECTS_EVAL
                else "DIAGNOSTIC_OR_INSUFFICIENT_HELDOUT"
            ),
        }
        inventory.append(entry)

        # Inclusion: TRAIN ONLY (+ namespace integrity). DQ flags keep in inventory but exclude from model vocab.
        reasons = []
        if not (key.startswith("A::") or key.startswith("B::")):
            reasons.append("invalid_namespace")
        if key.startswith("A::") and info["source_system"] != "magerya_api":
            reasons.append("a_namespace_source_mismatch")
        if key.startswith("B::") and info["source_system"] != "kgz_raw":
            reasons.append("b_namespace_source_mismatch")
        if n_tr_s < MIN_TRAIN_SUBJECTS:
            reasons.append(f"train_subjects<{MIN_TRAIN_SUBJECTS}")
        if info["train_targets"] < MIN_TRAIN_TARGETS:
            reasons.append(f"train_targets<{MIN_TRAIN_TARGETS}")
        if dq_reasons:
            reasons.append("data_quality_tier_excluded_from_model_vocab")

        if reasons:
            entry_ex = {**entry, "exclude_reasons": reasons}
            excluded.append(entry_ex)
        else:
            selected.append(entry)

    selected.sort(
        key=lambda e: (0 if e["outcome_key"].startswith("A::") else 1, e["outcome_key"])
    )
    order = [e["outcome_key"] for e in selected]
    vocab_hash = hashlib.sha256(
        json.dumps(order, separators=(",", ":")).encode()
    ).hexdigest()

    excluded_by_reason: dict[str, int] = defaultdict(int)
    for e in excluded:
        for r in e.get("exclude_reasons") or []:
            excluded_by_reason[r] += 1

    val_eval = sum(1 for e in selected if e["evidence_tier"] == "EVALUABLE_TECHNICAL_HELDOUT")
    # also count inventory for heldout
    val_eval_all = sum(
        1 for e in inventory if e["evidence_tier"] == "EVALUABLE_TECHNICAL_HELDOUT"
    )

    unexplained = len(by) - len(selected) - len(excluded)
    funnel = {
        "outcome_universe": len(by),
        "train_eligible_included_in_model_vocab": len(selected),
        "excluded": len(excluded),
        "excluded_by_reason": dict(excluded_by_reason),
        "data_quality_flagged_in_inventory": dq_flagged,
        "validation_evaluable_in_vocab": val_eval,
        "test_evaluable_in_vocab": val_eval,
        "validation_evaluable_in_universe": val_eval_all,
        "selected_a": sum(1 for e in selected if e["outcome_key"].startswith("A::")),
        "selected_b": sum(1 for e in selected if e["outcome_key"].startswith("B::")),
        "unexplained": unexplained,
    }

    doc = {
        "version": VERSION,
        "TRAIN_ONLY_OUTCOME_VOCABULARY_STATUS": "PASS" if selected and unexplained == 0 else "FAIL",
        "selection_on": "train_population_only",
        "heldout_used_only_for_evidence_tiers": True,
        "no_test_performance_selection": True,
        "no_a_b_semantic_merge": True,
        "no_unit_conversion": True,
        "vocabulary_order": order,
        "vocabulary_hash": vocab_hash,
        "selected": selected,
        "excluded_sample": excluded[:40],
        "excluded_count": len(excluded),
        "funnel": funnel,
        "thresholds": {
            "MIN_TRAIN_SUBJECTS": MIN_TRAIN_SUBJECTS,
            "MIN_TRAIN_TARGETS": MIN_TRAIN_TARGETS,
            "MIN_VAL_SUBJECTS_EVAL": MIN_VAL_SUBJECTS_EVAL,
            "MIN_TEST_SUBJECTS_EVAL": MIN_TEST_SUBJECTS_EVAL,
        },
        "ok": bool(selected) and unexplained == 0,
    }
    (out / "outcome-vocabulary-train-only.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
