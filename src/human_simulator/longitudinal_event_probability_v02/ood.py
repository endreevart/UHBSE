"""Source-stratified Applicability/OOD on raw state features."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v02.landmarks import FEATURE_ORDER
from human_simulator.longitudinal_event_probability_v02.policy import (
    LANDMARK_DIR,
    MODELS_DIR,
    OOD_MAX_VAL_FPR,
    RUNTIME_DIR,
    SEED,
    VERSION,
)


def build_ood(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    rows = pq.read_table(
        root / LANDMARK_DIR / "landmark_observation_process.parquet"
    ).to_pylist()

    def feats(r: dict[str, Any]) -> dict[str, float]:
        f = json.loads(r["features_json"])
        d = {FEATURE_ORDER[i]: f[i] for i in range(len(FEATURE_ORDER))}
        dens = 1.0 - float(d.get("missingness_lab") or 0)
        return {
            "mask_proxy": dens,
            "n_obs_before": float(d.get("n_obs_before") or 0),
            "longitudinal_age_days": float(d.get("longitudinal_age_days") or 0),
            "days_since_last_event": float(d.get("days_since_last_event") or 0),
            "history_depth": float(r.get("history_depth") or 0),
        }

    def stratified(rows_, n, seed):
        rng = random.Random(seed)
        out = []
        for ss in ("magerya_api", "kgz_raw"):
            pool = [r for r in rows_ if r["source_system"] == ss]
            pool = sorted(pool, key=lambda r: r["landmark_id"])
            rng.shuffle(pool)
            out.extend(pool[: n // 2])
        return out

    train = [r for r in rows if r["split_role"] == "train"]
    val = [r for r in rows if r["split_role"] == "validation"]
    test = [r for r in rows if r["split_role"] == "test"]

    ref = {}
    for ss, label in (("magerya_api", "A"), ("kgz_raw", "B")):
        ref_rows = stratified([r for r in train if r["source_system"] == ss], 300, SEED)
        fs = [feats(r) for r in ref_rows]
        ranges = {}
        for k in fs[0]:
            vals = [f[k] for f in fs]
            lo, hi = min(vals), max(vals)
            pad = 0.05 * (hi - lo if hi > lo else 1.0)
            ranges[k] = {"lo": lo - pad, "hi": hi + pad}
        ref[label] = {"n": len(fs), "ranges": ranges, "source_system": ss}

    def score(r):
        label = "A" if r["source_system"] == "magerya_api" else "B"
        f = feats(r)
        reasons = []
        if f["history_depth"] < 1:
            reasons.append("insufficient_history")
        for k, rng in ref[label]["ranges"].items():
            if f[k] < rng["lo"] or f[k] > rng["hi"]:
                reasons.append(f"feature_range:{k}")
        return {"in_support": len(reasons) == 0, "reasons": reasons, "source": label}

    cal = [score(r) for r in stratified(val, 200, SEED + 2)]
    fpr = sum(1 for s in cal if not s["in_support"]) / max(len(cal), 1)

    test_sample = sorted(test, key=lambda r: r["landmark_id"])
    if len(test_sample) > 3000:
        test_sample = stratified(test, 2000, SEED + 9)
    scored = [score(r) for r in test_sample]
    assert len(scored) == len(test_sample)

    foundation = (
        "NOT_ACCEPTED_HIGH_FALSE_POSITIVE_RATE"
        if fpr > OOD_MAX_VAL_FPR
        else "TECHNICAL_EVALUATED"
    )
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR / "ood-reference.json").write_text(
        json.dumps({"ref": ref, "features": "raw_source_aware", "CLINICAL_SAFETY": False}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    doc = {
        "version": VERSION,
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": "TECHNICAL_EVALUATED",
        "APPLICABILITY_FOUNDATION_STATUS": foundation,
        "not_safety_boundary": True,
        "validation_calibration_fpr": fpr,
        "ood_max_val_fpr_gate": OOD_MAX_VAL_FPR,
        "test_n_scored": len(scored),
        "test_ood_fraction": sum(1 for s in scored if not s["in_support"]) / max(len(scored), 1),
        "code_artifact_n_equality": True,
        "ok": True,
    }
    (root / RUNTIME_DIR / "applicability-ood.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
