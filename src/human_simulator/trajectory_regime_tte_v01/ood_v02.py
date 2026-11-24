"""Source-stratified Applicability/OOD v0.2."""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.trajectory_regime_tte_v01.denoising_encoder import predict_denoising
from human_simulator.trajectory_regime_tte_v01.evaluate import _remap_tensor_row
from human_simulator.trajectory_regime_tte_v01.policy import (
    CSR_TENSOR_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    SEED,
    VERSION,
)


def build_ood_v02(
    root: Path,
    model: dict[str, Any],
    csr_order: list[str],
    *,
    foundation_accepted: bool,
) -> dict[str, Any]:
    root = Path(root).resolve()
    order = model["outcome_keys"]
    tensors = [
        _remap_tensor_row(r, order, csr_order)
        for r in pq.read_table(root / CSR_TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
    ]
    train = [r for r in tensors if r["split_role"] == "train"]
    val = [r for r in tensors if r["split_role"] == "validation"]
    test = [r for r in tensors if r["split_role"] == "test"]

    def feats(row: dict[str, Any]) -> dict[str, Any]:
        if foundation_accepted:
            pred = predict_denoising(model, row)
            af = pred["applicability_features"]
            latent = pred["latent"]
        else:
            # raw source-aware features when encoder not accepted
            ctx = json.loads(row["context_json"])
            mask = json.loads(row["channels_json"])["mask"]
            dens = sum(mask) / max(len(mask), 1)
            latent = [
                float(ctx.get("longitudinal_age_days") or 0) / 365.0,
                dens,
                float(ctx.get("n_obs_before") or 0) / 50.0,
                float(ctx.get("days_since_last_event") or 0) / 30.0,
            ]
            af = {
                "mask_density": dens,
                "n_observed": sum(1 for m in mask if m > 0),
                "latent_l2": math.sqrt(sum(x * x for x in latent)),
                "source_is_a": ctx.get("source_is_a", 0),
                "source_is_b": ctx.get("source_is_b", 0),
                "longitudinal_age_days": ctx.get("longitudinal_age_days", 0),
                "n_obs_before": ctx.get("n_obs_before", 0),
                "days_since_last_event": ctx.get("days_since_last_event", 0),
            }
        return {**af, "latent": latent}

    def stratified_pick(rows: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
        rng = random.Random(seed)
        buckets: dict[str, list] = {"A": [], "B": []}
        for r in rows:
            buckets["A" if r["source_system"] == "magerya_api" else "B"].append(r)
        out = []
        per = max(1, n // 2)
        for src in ("A", "B"):
            pool = sorted(buckets[src], key=lambda x: x["state_id"])
            rng.shuffle(pool)
            # further by missingness
            lo = [r for r in pool if sum(json.loads(r["channels_json"])["mask"]) < 3]
            hi = [r for r in pool if r not in lo]
            take = []
            take.extend(lo[: per // 2])
            take.extend(hi[: per - len(take)])
            out.extend(take[:per])
        return sorted(out, key=lambda x: x["state_id"])

    ref_a = stratified_pick([r for r in train if r["source_system"] == "magerya_api"], 250, SEED)
    ref_b = stratified_pick([r for r in train if r["source_system"] == "kgz_raw"], 250, SEED + 1)
    # validation calibration set (separate)
    cal_a = stratified_pick([r for r in val if r["source_system"] == "magerya_api"], 80, SEED + 2)
    cal_b = stratified_pick([r for r in val if r["source_system"] == "kgz_raw"], 80, SEED + 3)

    def build_ref(ref_rows: list[dict[str, Any]]) -> dict[str, Any]:
        fs = [feats(r) for r in ref_rows]
        keys = ["mask_density", "n_observed", "latent_l2", "longitudinal_age_days", "days_since_last_event"]
        ranges = {}
        for k in keys:
            vals = [float(f[k]) for f in fs]
            lo, hi = min(vals), max(vals)
            pad = 0.05 * (hi - lo if hi > lo else 1.0)
            ranges[k] = {"lo": lo - pad, "hi": hi + pad}
        lat_dim = len(fs[0]["latent"])
        centroid = [sum(f["latent"][i] for f in fs) / len(fs) for i in range(lat_dim)]
        dists = [
            math.sqrt(sum((f["latent"][i] - centroid[i]) ** 2 for i in range(lat_dim)))
            for f in fs
        ]
        dists.sort()
        return {
            "n_ref": len(fs),
            "ranges": ranges,
            "latent_centroid": centroid,
            "latent_distance_p95": dists[int(0.95 * (len(dists) - 1))],
            "mask_density_p05": sorted(f["mask_density"] for f in fs)[
                int(0.05 * (len(fs) - 1))
            ],
        }

    ref = {"A": build_ref(ref_a), "B": build_ref(ref_b)}

    def score(row: dict[str, Any]) -> dict[str, Any]:
        src = "A" if row["source_system"] == "magerya_api" else "B"
        f = feats(row)
        r = ref[src]
        reasons = []
        for k, rng in r["ranges"].items():
            if float(f[k]) < rng["lo"] or float(f[k]) > rng["hi"]:
                reasons.append(f"feature_range:{k}")
        if f["mask_density"] < r["mask_density_p05"]:
            reasons.append("outcome_mask_pattern")
        if f["n_observed"] < 1:
            reasons.append("insufficient_history")
        lat_dim = len(r["latent_centroid"])
        d = math.sqrt(
            sum((f["latent"][i] - r["latent_centroid"][i]) ** 2 for i in range(lat_dim))
        )
        if d > r["latent_distance_p95"]:
            reasons.append("latent_distance")
        return {"in_support": len(reasons) == 0, "reasons": reasons, "source": src, "distance": d}

    # Validate FPR on in-distribution calibration
    cal_scores = [score(r) for r in cal_a + cal_b]
    fpr = sum(1 for s in cal_scores if not s["in_support"]) / max(len(cal_scores), 1)

    # Full test OR exact sampling manifest
    use_full_test = len(test) <= 5000
    if use_full_test:
        test_sample = sorted(test, key=lambda r: r["state_id"])
        sampling = {"mode": "full_test", "n": len(test_sample)}
    else:
        test_sample = stratified_pick(test, 2000, SEED + 9)
        ids = [r["state_id"] for r in test_sample]
        sampling = {
            "mode": "stratified_deterministic",
            "n": len(test_sample),
            "manifest_sha256": hashlib.sha256(
                json.dumps(ids, separators=(",", ":")).encode()
            ).hexdigest(),
            "seed": SEED + 9,
        }
    scored = [score(r) for r in test_sample]
    n_ood = sum(1 for s in scored if not s["in_support"])
    reason_counts: dict[str, int] = {}
    for s in scored:
        for r in s["reasons"]:
            reason_counts[r] = reason_counts.get(r, 0) + 1

    # Code/artifact equality invariant
    assert len(scored) == sampling["n"]

    reference_pub = {
        "A": {k: v for k, v in ref["A"].items() if k != "latent_centroid"}
        | {"latent_dim": len(ref["A"]["latent_centroid"])},
        "B": {k: v for k, v in ref["B"].items() if k != "latent_centroid"}
        | {"latent_dim": len(ref["B"]["latent_centroid"])},
        "thresholds_from": "train_fit_source_stratified",
        "validation_calibration_fpr": fpr,
        "features_basis": "denoising_encoder" if foundation_accepted else "raw_source_aware_state",
        "CLINICAL_SAFETY_DETECTOR": False,
        "not_safety_boundary": True,
    }
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR / "applicability-ood-v02-reference.json").write_text(
        json.dumps(
            {
                "ref": {
                    "A": {**ref["A"], "latent_centroid": ref["A"]["latent_centroid"]},
                    "B": {**ref["B"], "latent_centroid": ref["B"]["latent_centroid"]},
                },
                **reference_pub,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ok = (
        bool(ref["A"]["n_ref"])
        and bool(ref["B"]["n_ref"])
        and sampling["n"] > 0
        and len(scored) == sampling["n"]
    )
    doc = {
        "version": VERSION,
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": "TECHNICAL_EVALUATED" if ok else "FAIL",
        "not_clinical_ood": True,
        "not_safety_boundary": True,
        "test_n_scored": len(scored),
        "sampling": sampling,
        "code_artifact_n_equality": len(scored) == sampling["n"],
        "test_in_support": len(scored) - n_ood,
        "test_out_of_support": n_ood,
        "test_ood_fraction": n_ood / max(len(scored), 1),
        "ood_reason_counts": reason_counts,
        "validation_calibration_fpr": fpr,
        "reference_public": reference_pub,
        "ok": ok,
    }
    (root / RUNTIME_DIR / "applicability-ood-v02.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
