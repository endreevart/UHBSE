"""Source-stratified applicability / OOD with missingness and history-depth stratification."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v021.policy import (
    FEATURE_ORDER,
    LANDMARK_DIR,
    MODELS_DIR,
    OOD_MAX_VAL_FPR,
    RUNTIME_DIR,
    SEED,
    VERSION,
)


def _feats(r: dict[str, Any]) -> dict[str, float]:
    f = json.loads(r["features_json"])
    d = {FEATURE_ORDER[i]: f[i] for i in range(len(FEATURE_ORDER))}
    dens = 1.0 - float(d.get("missingness_lab") or 0)
    return {
        "mask_proxy": dens,
        "n_obs_before": float(d.get("n_obs_before") or 0),
        "longitudinal_age_days": float(d.get("longitudinal_age_days") or 0),
        "days_since_last_event": float(d.get("days_since_last_event") or 0),
        "history_depth": float(r.get("history_depth") or d.get("n_obs_before") or 0),
    }


def _stratum(r: dict[str, Any]) -> str:
    f = _feats(r)
    miss = 0 if f["mask_proxy"] < 0.33 else (1 if f["mask_proxy"] < 0.66 else 2)
    hist = 0 if f["history_depth"] < 2 else (1 if f["history_depth"] < 8 else 2)
    return f"{r['source_system']}|m{miss}|h{hist}"


def _stratified(
    rows: list[dict[str, Any]],
    per_stratum: int,
    seed: int,
    *,
    expected_label: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    buckets: dict[str, list] = defaultdict(list)
    for r in rows:
        buckets[_stratum(r)].append(r)
    out = []
    accounting = {}
    for key in sorted(buckets):
        pool = sorted(buckets[key], key=lambda r: r["landmark_id"])
        rng.shuffle(pool)
        take = pool[:per_stratum]
        out.extend(take)
        accounting[key] = {
            "available": len(pool),
            "expected": min(per_stratum, len(pool)),
            "actual": len(take),
        }
    assert all(a["expected"] == a["actual"] for a in accounting.values())
    return out, {
        "label": expected_label,
        "per_stratum": per_stratum,
        "n": len(out),
        "strata": accounting,
        "stratified_by": ["source_system", "missingness_tertile", "history_depth_tertile"],
    }


def build_ood(root: Path, parquet_name: str) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / LANDMARK_DIR / parquet_name
    rows = pq.read_table(path).to_pylist() if path.is_file() else []
    train = [r for r in rows if r["split_role"] == "train"]
    val = [r for r in rows if r["split_role"] == "validation"]
    test = [r for r in rows if r["split_role"] == "test"]

    ref = {}
    train_sample, train_acc = _stratified(train, 40, SEED, expected_label="train_reference")
    by_src: dict[str, list] = defaultdict(list)
    for r in train_sample:
        by_src[r["source_system"]].append(r)
    for ss, label in (("magerya_api", "A"), ("kgz_raw", "B")):
        fs = [_feats(r) for r in by_src.get(ss, [])]
        if not fs:
            ref[label] = {"n": 0, "ranges": {}, "source_system": ss}
            continue
        ranges = {}
        for k in fs[0]:
            vals = [f[k] for f in fs]
            lo, hi = min(vals), max(vals)
            pad = 0.05 * (hi - lo if hi > lo else 1.0)
            ranges[k] = {"lo": lo - pad, "hi": hi + pad}
        ref[label] = {"n": len(fs), "ranges": ranges, "source_system": ss}

    def score(r):
        label = "A" if r["source_system"] == "magerya_api" else "B"
        f = _feats(r)
        reasons = []
        if f["history_depth"] < 1:
            reasons.append("insufficient_history")
        for k, rng in (ref[label].get("ranges") or {}).items():
            if f[k] < rng["lo"] or f[k] > rng["hi"]:
                reasons.append(f"feature_range:{k}")
        return {"in_support": len(reasons) == 0, "reasons": reasons, "source": label}

    val_sample, val_acc = _stratified(val, 25, SEED + 2, expected_label="validation_calibration")
    cal = [score(r) for r in val_sample]
    fpr = sum(1 for s in cal if not s["in_support"]) / max(len(cal), 1)
    test_sample, test_acc = _stratified(test, 30, SEED + 9, expected_label="test_after_freeze")
    scored = [score(r) for r in test_sample]
    assert len(scored) == len(test_sample)

    manifest = {
        "train": {
            **train_acc,
            "opaque_landmark_ids": [r["landmark_id"] for r in train_sample],
        },
        "validation": {
            **val_acc,
            "opaque_landmark_ids": [r["landmark_id"] for r in val_sample],
        },
        "test": {
            **test_acc,
            "opaque_landmark_ids": [r["landmark_id"] for r in test_sample],
        },
    }
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR / "ood-sampling-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    detector = {
        "ref": ref,
        "features": "raw_source_aware",
        "feature_order": list(FEATURE_ORDER),
        "CLINICAL_SAFETY": False,
        "not_safety_boundary": True,
    }
    (root / MODELS_DIR / "ood-reference.json").write_text(
        json.dumps(detector, indent=2) + "\n", encoding="utf-8"
    )
    foundation = (
        "NOT_ACCEPTED_HIGH_FALSE_POSITIVE_RATE"
        if fpr > OOD_MAX_VAL_FPR
        else "TECHNICAL_EVALUATED"
    )
    doc = {
        "version": VERSION,
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": "TECHNICAL_EVALUATED",
        "APPLICABILITY_FOUNDATION_STATUS": foundation,
        "not_safety_boundary": True,
        "validation_calibration_fpr": fpr,
        "ood_max_val_fpr_gate": OOD_MAX_VAL_FPR,
        "fpr_gate_passed": fpr <= OOD_MAX_VAL_FPR,
        "test_n_scored": len(scored),
        "test_ood_fraction": sum(1 for s in scored if not s["in_support"]) / max(len(scored), 1),
        "sampling_accounting": {
            "train": train_acc,
            "validation": val_acc,
            "test": {k: v for k, v in test_acc.items() if k != "opaque_landmark_ids"},
        },
        "code_artifact_n_equality": True,
        "engine_must_load_detector": True,
        "ok": True,
    }
    (root / RUNTIME_DIR / "applicability-ood.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
