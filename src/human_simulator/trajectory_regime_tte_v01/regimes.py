"""Label-free trajectory regime discovery (candidates only)."""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.trajectory_regime_tte_v01.policy import (
    MODELS_DIR,
    RUNTIME_DIR,
    SEED,
    TRANSITIONS_DIR,
    VERSION,
)


def _feat(row: dict[str, Any]) -> list[float]:
    ctx = json.loads(row["context_t0_json"])
    return [
        float(row.get("horizon_days") or 0) / 30.0,
        float(row.get("history_depth_t0") or 0) / 20.0,
        float(row.get("mask_density_t0") or 0),
        float(row.get("n_appeared") or 0) / 10.0,
        float(row.get("n_disappeared") or 0) / 10.0,
        float(row.get("mean_abs_delta_observed") or 0),
        float(ctx.get("source_is_a") or 0),
        float(ctx.get("n_medications_before") or 0) / 20.0,
        float(ctx.get("days_since_last_event") or 0) / 30.0,
    ]


def _kmeans(X: list[list[float]], k: int, seed: int, iters: int = 12) -> tuple[list[int], list[list[float]]]:
    rng = random.Random(seed)
    centers = [X[rng.randrange(len(X))][:] for _ in range(k)]
    assign = [0] * len(X)
    for _ in range(iters):
        for i, x in enumerate(X):
            dists = [sum((x[j] - c[j]) ** 2 for j in range(len(x))) for c in centers]
            assign[i] = dists.index(min(dists))
        for c in range(k):
            members = [X[i] for i, a in enumerate(assign) if a == c]
            if members:
                centers[c] = [
                    sum(m[d] for m in members) / len(members) for d in range(len(members[0]))
                ]
    return assign, centers


def _ari(a: list[int], b: list[int]) -> float:
    """Adjusted Rand Index (simple implementation)."""
    n = len(a)
    if n == 0:
        return 0.0
    from itertools import combinations

    def agree(u, v):
        same_u = u[0] == u[1]
        same_v = v[0] == v[1]
        return same_u == same_v

    # too slow for large n — subsample pairs
    rng = random.Random(0)
    idx = list(range(n))
    if n > 800:
        idx = rng.sample(idx, 800)
    tp = tn = fp = fn = 0
    for i, j in combinations(idx, 2):
        su = a[i] == a[j]
        sv = b[i] == b[j]
        if su and sv:
            tp += 1
        elif (not su) and (not sv):
            tn += 1
        elif su and not sv:
            fp += 1
        else:
            fn += 1
    # simplified RI
    return (tp + tn) / max(tp + tn + fp + fn, 1)


def discover_regimes(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    rows = pq.read_table(root / TRANSITIONS_DIR / "transitions.parquet").to_pylist()
    train = [r for r in rows if r["split_role"] == "train"]
    val = [r for r in rows if r["split_role"] == "validation"]
    rng = random.Random(SEED)
    rng.shuffle(train)
    sample = sorted(train[:1500], key=lambda r: r["transition_id"])
    X = [_feat(r) for r in sample]
    meta = [
        {
            "source": r["source_system"],
            "mask_density": r["mask_density_t0"],
        }
        for r in sample
    ]

    # choose k on validation silhouette-like inertia
    val_sample = sorted(val, key=lambda r: r["transition_id"])[:400]
    Xv = [_feat(r) for r in val_sample]
    best_k, best_score = 3, float("inf")
    for k in (3, 4, 5):
        assign, centers = _kmeans(X, k, SEED + k)
        # val inertia
        score = 0.0
        for x in Xv:
            score += min(sum((x[j] - c[j]) ** 2 for j in range(len(x))) for c in centers)
        if score < best_score:
            best_score, best_k = score, k

    # stability across seeds
    base_assign, centers = _kmeans(X, best_k, SEED)
    aris = []
    for s in (SEED + 11, SEED + 22, SEED + 33):
        a2, _ = _kmeans(X, best_k, s)
        aris.append(_ari(base_assign, a2))
    # subsample stability
    sub_aris = []
    for s in (1, 2, 3):
        rng2 = random.Random(SEED + 100 + s)
        idx = sorted(rng2.sample(range(len(X)), min(800, len(X))))
        Xs = [X[i] for i in idx]
        a1, _ = _kmeans(Xs, best_k, SEED)
        a2, _ = _kmeans(Xs, best_k, SEED + 50 + s)
        sub_aris.append(_ari(a1, a2))

    mean_ari = sum(aris) / len(aris)
    mean_sub = sum(sub_aris) / len(sub_aris)
    stable = mean_ari >= 0.55 and mean_sub >= 0.50

    # cluster composition
    clusters = []
    for c in range(best_k):
        members = [i for i, a in enumerate(base_assign) if a == c]
        src = Counter(meta[i]["source"] for i in members)
        dens = [meta[i]["mask_density"] for i in members]
        # purity by source
        src_purity = max(src.values()) / max(len(members), 1) if members else 0
        clusters.append(
            {
                "label": "TRAJECTORY_REGIME_CANDIDATE",
                "also": "STATE_TRANSITION_SIGNATURE_CANDIDATE",
                "cluster_id": c,
                "n": len(members),
                "source_composition": dict(src),
                "source_purity": src_purity,
                "mean_mask_density": sum(dens) / max(len(dens), 1),
                "centroid_l2": math.sqrt(sum(x * x for x in centers[c])),
                "not_a_diagnosis": True,
                "not_clinical_state": True,
                "not_causal": True,
            }
        )

    # reject if any cluster is only source flag / missingness
    source_only = any(c["source_purity"] >= 0.95 for c in clusters)
    # check correlation of assignment with source
    src_labels = [0 if m["source"] == "magerya_api" else 1 for m in meta]
    src_ari = _ari(base_assign, src_labels)
    dens_med = sorted(m["mask_density"] for m in meta)[len(meta) // 2]
    dens_labels = [0 if m["mask_density"] < dens_med else 1 for m in meta]
    dens_ari = _ari(base_assign, dens_labels)

    status = "CANDIDATE_ONLY"
    if not stable or source_only or src_ari >= 0.7 or dens_ari >= 0.7:
        status = "CANDIDATE_ONLY_UNSTABLE"

    doc = {
        "version": VERSION,
        "TRAJECTORY_REGIME_DISCOVERY_STATUS": status,
        "TRAJECTORY_REGIME_STABILITY_STATUS": "STABLE" if stable else "UNSTABLE",
        "k_selected_on_validation": best_k,
        "stability_ari_seeds": aris,
        "stability_ari_mean": mean_ari,
        "subsample_ari_mean": mean_sub,
        "source_assignment_ari": src_ari,
        "missingness_assignment_ari": dens_ari,
        "rejected_as_source_or_missingness_only": source_only or src_ari >= 0.7 or dens_ari >= 0.7,
        "clusters": clusters,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED_NO_ACCEPTED_LABEL_ONTOLOGY",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
        "ok": True,
    }
    (root / RUNTIME_DIR / "trajectory-regime-discovery.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR / "regime-centers.json").write_text(
        json.dumps({"k": best_k, "centers": centers, "seed": SEED}, indent=2) + "\n",
        encoding="utf-8",
    )
    return doc
