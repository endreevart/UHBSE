"""Shared finite-sample permutation and tail-risk helpers."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def finite_sample_permutation_p(*, count_le_real: int, n_permutations: int) -> float:
    """(k+1)/(n+1); never returns literal 0.0 for finite n."""
    return (int(count_le_real) + 1) / (int(n_permutations) + 1)


def assert_permutation_p_not_literal_zero(p: float) -> None:
    if p == 0.0:
        raise ValueError("finite permutation p-value must not be serialized as literal 0.0")


def percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = min(len(sorted_vals) - 1, max(0, int(math.ceil(p * len(sorted_vals)) - 1)))
    return sorted_vals[idx]


def prediction_error_metrics(
    preds: list[dict[str, Any]],
    *,
    thresholds: tuple[float, ...] = (1.0, 2.0, 5.0),
) -> dict[str, Any]:
    if not preds:
        return {"n_pairs": 0, "n_subjects": 0}
    abs_err = [abs(float(p["y_pred"]) - float(p["y_true"])) for p in preds]
    sq = [(float(p["y_pred"]) - float(p["y_true"])) ** 2 for p in preds]
    bias = [float(p["y_pred"]) - float(p["y_true"]) for p in preds]
    by: dict[str, list[float]] = defaultdict(list)
    for p, e in zip(preds, abs_err, strict=True):
        by[str(p["opaque_subject_key"])].append(e)
    macro = sum(sum(v) / len(v) for v in by.values()) / len(by)
    subject_means = {s: sum(v) / len(v) for s, v in by.items()}
    worst = max(subject_means, key=subject_means.get)
    srt = sorted(abs_err)
    out: dict[str, Any] = {
        "n_pairs": len(preds),
        "n_subjects": len(by),
        "subject_macro_mae": macro,
        "pair_micro_mae": sum(abs_err) / len(abs_err),
        "mae": sum(abs_err) / len(abs_err),
        "rmse": math.sqrt(sum(sq) / len(sq)),
        "median_absolute_error": srt[len(srt) // 2],
        "p90_absolute_error": percentile(srt, 0.90),
        "p95_absolute_error": percentile(srt, 0.95),
        "p99_absolute_error": percentile(srt, 0.99),
        "maximum_absolute_error": srt[-1],
        "bias": sum(bias) / len(bias),
        "worst_subject_mean_absolute_error": subject_means[worst],
        "large_error_thresholds_prospective": list(thresholds),
    }
    for t in thresholds:
        out[f"large_error_rate_abs_gt_{t}"] = sum(1 for e in abs_err if e > t) / len(abs_err)
    return out


def map_relation_accounting(bucket: dict[str, int]) -> dict[str, int]:
    """Normalize load buckets to required publication field names."""
    candidate = int(bucket.get("candidate_count") or bucket.get("candidate_rows") or 0)
    inserted = int(bucket.get("loaded_count") or bucket.get("inserted_rows") or 0)
    rejected = int(bucket.get("rejected_count") or bucket.get("rejected_rows") or 0)
    unsupported = int(bucket.get("unsupported_count") or bucket.get("unsupported_rows") or 0)
    quarantined = int(bucket.get("quarantined_count") or bucket.get("quarantined_rows") or 0)
    truncated = int(bucket.get("truncated_count") or bucket.get("truncated_rows") or 0)
    unexplained = int(bucket.get("unaccounted_count") or bucket.get("unexplained_rows") or 0)
    # already_present inferred when candidate > inserted+rejected+unsupported+quarantined
    accounted = inserted + rejected + unsupported + quarantined
    already = max(0, candidate - accounted) if unexplained == 0 else int(
        bucket.get("already_present_rows") or 0
    )
    # Prefer explicit already_present if set
    if "already_present_rows" in bucket:
        already = int(bucket["already_present_rows"])
    return {
        "source_rows_considered": int(
            bucket.get("runtime_count") or bucket.get("source_rows_considered") or candidate
        ),
        "candidate_rows": candidate,
        "inserted_rows": inserted,
        "already_present_rows": already,
        "rejected_rows": rejected,
        "unsupported_rows": unsupported,
        "quarantined_rows": quarantined,
        "truncated_rows": truncated,
        "unexplained_rows": unexplained,
    }
