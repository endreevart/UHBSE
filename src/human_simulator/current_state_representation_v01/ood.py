"""Technical Applicability / OOD detector (not clinical safety)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.current_state_representation_v01.encoder import predict_encoder
from human_simulator.current_state_representation_v01.policy import (
    MODELS_DIR,
    RUNTIME_DIR,
    TENSOR_DIR,
    VERSION,
)


def build_applicability_ood(root: Path, model: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    tensors = pq.read_table(root / TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
    train = [r for r in tensors if r.get("split_role") == "train"]
    val = [r for r in tensors if r.get("split_role") == "validation"]
    test = [r for r in tensors if r.get("split_role") == "test"]

    # Train/val reference — feature ranges, mask density, latent centroid
    def feats(row: dict[str, Any]) -> dict[str, float]:
        pred = predict_encoder(model, row)
        ctx = json.loads(row["context_json"])
        return {
            "mask_density": pred["applicability_features"]["mask_density"],
            "n_observed": float(pred["applicability_features"]["n_observed"]),
            "latent_l2": pred["applicability_features"]["latent_l2"],
            "longitudinal_age_days": float(ctx.get("longitudinal_age_days") or 0),
            "days_since_last_event": float(ctx.get("days_since_last_event") or 0),
            "source_is_a": float(ctx.get("source_is_a") or 0),
            "source_is_b": float(ctx.get("source_is_b") or 0),
            "latent": pred["latent"],
        }

    # Subsample train/val for reference
    ref_rows = (train[:300] + val[:100]) if train else val[:100]
    # Cache feats
    ref_feats = []
    for r in ref_rows:
        pred = predict_encoder(model, r)
        ctx = json.loads(r["context_json"])
        ref_feats.append(
            {
                "mask_density": pred["applicability_features"]["mask_density"],
                "n_observed": float(pred["applicability_features"]["n_observed"]),
                "latent_l2": pred["applicability_features"]["latent_l2"],
                "longitudinal_age_days": float(ctx.get("longitudinal_age_days") or 0),
                "days_since_last_event": float(ctx.get("days_since_last_event") or 0),
                "source_is_a": float(ctx.get("source_is_a") or 0),
                "source_is_b": float(ctx.get("source_is_b") or 0),
                "latent": pred["latent"],
            }
        )
    keys = [
        "mask_density",
        "n_observed",
        "latent_l2",
        "longitudinal_age_days",
        "days_since_last_event",
    ]
    ranges = {}
    for k in keys:
        vals = [f[k] for f in ref_feats]
        lo, hi = min(vals), max(vals)
        pad = 0.05 * (hi - lo if hi > lo else 1.0)
        ranges[k] = {"lo": lo - pad, "hi": hi + pad}

    # Latent centroid + radius (train/val only)
    lat_dim = len(ref_feats[0]["latent"])
    centroid = [
        sum(f["latent"][i] for f in ref_feats) / len(ref_feats) for i in range(lat_dim)
    ]
    dists = [
        math.sqrt(sum((f["latent"][i] - centroid[i]) ** 2 for i in range(lat_dim)))
        for f in ref_feats
    ]
    dists_sorted = sorted(dists)
    lat_thresh = dists_sorted[int(0.95 * (len(dists_sorted) - 1))]
    mask_density_min = sorted(f["mask_density"] for f in ref_feats)[
        int(0.05 * (len(ref_feats) - 1))
    ]
    history_min = 1.0  # insufficient-history if n_observed < 1

    reference = {
        "version": VERSION,
        "thresholds_from": "train_and_validation_only",
        "no_test_in_threshold": True,
        "feature_ranges": ranges,
        "latent_centroid": centroid,
        "latent_distance_p95": lat_thresh,
        "mask_density_p05": mask_density_min,
        "insufficient_history_n_observed_lt": history_min,
        "CLINICAL_SAFETY_DETECTOR": False,
        "label": "technical_applicability_ood",
    }
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR / "applicability-ood-reference.json").write_text(
        json.dumps(reference, indent=2) + "\n", encoding="utf-8"
    )

    def score(row: dict[str, Any]) -> dict[str, Any]:
        f = feats(row)
        reasons = []
        for k, rng in ranges.items():
            if f[k] < rng["lo"] or f[k] > rng["hi"]:
                reasons.append(f"feature_range:{k}")
        if f["mask_density"] < mask_density_min:
            reasons.append("outcome_mask_pattern")
        if f["n_observed"] < history_min:
            reasons.append("insufficient_history")
        # temporal horizon: extreme days_since
        if f["days_since_last_event"] > ranges["days_since_last_event"]["hi"]:
            reasons.append("temporal_horizon")
        d = math.sqrt(
            sum((f["latent"][i] - centroid[i]) ** 2 for i in range(lat_dim))
        )
        if d > lat_thresh:
            reasons.append("latent_distance")
        # source-specific: both flags off or both on is odd
        if f["source_is_a"] + f["source_is_b"] != 1.0:
            reasons.append("source_specific")
        in_support = len(reasons) == 0
        return {
            "in_support": in_support,
            "reasons": reasons,
            "latent_distance": d,
            "mask_density": f["mask_density"],
        }

    # Test report (aggregate only)
    test_sample = test[:400] if test else []
    scored = [score(r) for r in test_sample]
    n_ood = sum(1 for s in scored if not s["in_support"])
    reason_counts: dict[str, int] = {}
    for s in scored:
        for r in s["reasons"]:
            reason_counts[r] = reason_counts.get(r, 0) + 1

    doc = {
        "version": VERSION,
        "APPLICABILITY_REFERENCE_STATUS": "BUILT",
        "APPLICABILITY_OOD_DETECTOR_STATUS": "TECHNICAL_EVALUATED",
        "CLINICAL_OOD_VALIDATION_STATUS": "NOT_STARTED",
        "not_a_clinical_safety_detector": True,
        "test_n_scored": len(scored),
        "test_in_support": len(scored) - n_ood,
        "test_out_of_support": n_ood,
        "test_ood_fraction": n_ood / max(len(scored), 1),
        "ood_reason_counts": reason_counts,
        "abstention_behavior": "flag_out_of_support_do_not_claim_clinical_safety",
        "ok": True,
    }
    (root / RUNTIME_DIR / "applicability-ood-eval.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
