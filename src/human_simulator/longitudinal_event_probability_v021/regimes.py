"""t0-assignable regime methodology (option A). Not a runtime output."""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v021.policy import (
    REGIME_T0_FEATURE_NAMES,
    RUNTIME_DIR,
    SEED,
    TRAJ_TRANSITIONS,
    VERSION,
)


def _feat_t0_only(row: dict[str, Any]) -> list[float]:
    """Only features known at t0. No n_appeared / n_disappeared / mean_abs_delta_observed."""
    ctx = json.loads(row["context_t0_json"])
    return [
        float(row.get("history_depth_t0") or 0) / 20.0,
        float(row.get("mask_density_t0") or 0),
        float(ctx.get("n_medications_before") or 0) / 20.0,
        float(ctx.get("days_since_last_event") or 0) / 30.0,
        float(ctx.get("longitudinal_age_days") or 0) / 365.0,
    ]


def _standardize(X: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    d = len(X[0])
    means, scales = [], []
    for j in range(d):
        col = [row[j] for row in X]
        mu = sum(col) / len(col)
        var = sum((v - mu) ** 2 for v in col) / len(col)
        means.append(mu)
        scales.append(math.sqrt(var) if var > 1e-12 else 1.0)
    Xs = [[(row[j] - means[j]) / scales[j] for j in range(d)] for row in X]
    return Xs, means, scales


def _kmeans(X: list[list[float]], k: int, seed: int, iters: int = 12):
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


def _adjusted_rand_index(a: list[int], b: list[int]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    nij: dict[tuple[int, int], int] = defaultdict(int)
    ai: dict[int, int] = defaultdict(int)
    bj: dict[int, int] = defaultdict(int)
    for x, y in zip(a, b, strict=True):
        nij[(x, y)] += 1
        ai[x] += 1
        bj[y] += 1

    def comb2(x: int) -> int:
        return x * (x - 1) // 2

    sum_nij = sum(comb2(v) for v in nij.values())
    sum_ai = sum(comb2(v) for v in ai.values())
    sum_bj = sum(comb2(v) for v in bj.values())
    total = comb2(n)
    if total == 0:
        return 0.0
    expected = sum_ai * sum_bj / total
    max_index = 0.5 * (sum_ai + sum_bj)
    denom = max_index - expected
    if abs(denom) < 1e-12:
        return 0.0
    return (sum_nij - expected) / denom


def _silhouette(X: list[list[float]], assign: list[int], k: int) -> float:
    if len(X) < 10:
        return -1.0
    rng = random.Random(0)
    idx = list(range(len(X)))
    if len(idx) > 400:
        idx = rng.sample(idx, 400)
    scores = []
    for i in idx:
        own = [j for j in idx if assign[j] == assign[i] and j != i]
        if not own:
            continue
        a = sum(
            math.sqrt(sum((X[i][d] - X[j][d]) ** 2 for d in range(len(X[i]))))
            for j in own
        ) / len(own)
        b = float("inf")
        for c in range(k):
            if c == assign[i]:
                continue
            other = [j for j in idx if assign[j] == c]
            if not other:
                continue
            dist = sum(
                math.sqrt(sum((X[i][d] - X[j][d]) ** 2 for d in range(len(X[i]))))
                for j in other
            ) / len(other)
            b = min(b, dist)
        if b == float("inf"):
            continue
        scores.append((b - a) / max(a, b, 1e-9))
    return sum(scores) / max(len(scores), 1)


def correct_regimes(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    rows = pq.read_table(root / TRAJ_TRANSITIONS / "transitions.parquet").to_pylist()
    train = [r for r in rows if r["split_role"] == "train"]
    by_subj: dict[str, list] = defaultdict(list)
    for r in train:
        by_subj[r.get("source_scoped_subject_id") or r.get("overlap_group_id") or r["transition_id"]].append(r)
    rng = random.Random(SEED)
    sids = sorted(by_subj)
    rng.shuffle(sids)
    sample_rows = []
    for sid in sids:
        sample_rows.extend(by_subj[sid])
        if len(sample_rows) >= 1200:
            break
    sample = sorted(sample_rows[:1200], key=lambda r: r["transition_id"])
    Xraw = [_feat_t0_only(r) for r in sample]
    Xs, _means, _scales = _standardize(Xraw)
    meta = [{"source": r["source_system"], "mask_density": r["mask_density_t0"]} for r in sample]
    groups = [
        r.get("source_scoped_subject_id") or r.get("overlap_group_id") or r["transition_id"]
        for r in sample
    ]

    best_k, best_sil = 3, -2.0
    for k in (3, 4, 5):
        assign, _ = _kmeans(Xs, k, SEED + k)
        cnt = Counter(assign)
        if min(cnt.values()) < 30:
            continue
        sil = _silhouette(Xs, assign, k)
        if sil > best_sil:
            best_sil, best_k = sil, k

    assign, _centers = _kmeans(Xs, best_k, SEED)
    # Stability via subject/overlap-group subsamples, not only different seeds on same rows.
    aris = []
    uniq = sorted(set(groups))
    for s in (11, 22, 33):
        rng_s = random.Random(SEED + s)
        keep = set(rng_s.sample(uniq, max(2, int(0.7 * len(uniq)))))
        idx = [i for i, g in enumerate(groups) if g in keep]
        if len(idx) < 50:
            continue
        subX = [Xs[i] for i in idx]
        sub_assign_full = [assign[i] for i in idx]
        sub_new, _ = _kmeans(subX, best_k, SEED + s)
        aris.append(_adjusted_rand_index(sub_assign_full, sub_new))
    mean_ari = sum(aris) / len(aris) if aris else 0.0
    numerical_stable = mean_ari >= 0.5 and best_sil > 0.05

    src_labels = [0 if m["source"] == "magerya_api" else 1 for m in meta]
    dens_med = sorted(m["mask_density"] for m in meta)[len(meta) // 2]
    dens_labels = [0 if m["mask_density"] < dens_med else 1 for m in meta]
    src_ari = _adjusted_rand_index(assign, src_labels)
    dens_ari = _adjusted_rand_index(assign, dens_labels)
    confounded = src_ari >= 0.5 or dens_ari >= 0.5

    if confounded:
        foundation = "NOT_ACCEPTED_SOURCE_OR_MISSINGNESS_CONFOUNDED"
    elif not numerical_stable:
        foundation = "NOT_ACCEPTED_UNSTABLE"
    else:
        foundation = "NOT_ACCEPTED_RETROSPECTIVE_ONLY"

    doc = {
        "version": VERSION,
        "regime_contract": "t0_assignable",
        "NOT_AVAILABLE_AT_T0_features_removed": [
            "n_appeared",
            "n_disappeared",
            "mean_abs_delta_observed",
        ],
        "feature_names": list(REGIME_T0_FEATURE_NAMES),
        "engine_inference_forbidden": True,
        "REGIME_NUMERICAL_STABILITY_STATUS": "STABLE" if numerical_stable else "UNSTABLE",
        "REGIME_CONFOUNDING_STATUS": (
            "CONFOUNDED" if confounded else "NOT_SOURCE_OR_MISSINGNESS_DOMINATED"
        ),
        "REGIME_FOUNDATION_ACCEPTANCE_STATUS": foundation,
        "not_runtime_prediction": True,
        "no_regime_candidate_id_in_engine": True,
        "features_exclude_source_flag": True,
        "features_exclude_future_horizon": True,
        "features_exclude_transition_deltas": True,
        "stability_unit": "subject_or_overlap_group_subsample",
        "train_only_standardization": True,
        "k_selected_by_silhouette": best_k,
        "silhouette": best_sil,
        "stability_ari_mean": mean_ari,
        "true_adjusted_rand_index": True,
        "source_assignment_ari": src_ari,
        "missingness_assignment_ari": dens_ari,
        "ok": True,
    }
    (root / RUNTIME_DIR / "regime-methodology-correction.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
