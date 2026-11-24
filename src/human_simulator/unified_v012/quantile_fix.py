"""Exclusive quantile assignment — fixes v0.1.1 overlapping q4 bug."""

from __future__ import annotations

from typing import Any, Sequence


def buggy_overlapping_quantile_assignment(
    values: Sequence[float],
) -> dict[str, list[int]]:
    """Reproduce the v0.1.1 defect: q4 uses ``x <= hi`` and absorbs the full set.

    Do not use in production — only for regression tests.
    """
    if not values:
        return {f"q{i}": [] for i in range(1, 5)}
    srt = sorted(values)
    qs = [0.0, 0.25, 0.5, 0.75, 1.0]
    cuts = [srt[min(len(srt) - 1, int(q * (len(srt) - 1)))] for q in qs]
    out: dict[str, list[int]] = {}
    for i in range(4):
        lo, hi = cuts[i], cuts[i + 1]
        rows = [
            idx
            for idx, v in enumerate(values)
            if (lo <= float(v) < hi) or (i == 3 and float(v) <= hi)
        ]
        out[f"q{i + 1}"] = rows
    return out


def assign_exclusive_quantiles(
    values: Sequence[float],
    *,
    n_bins: int = 4,
    row_indices: Sequence[int] | None = None,
) -> dict[str, list[int]]:
    """Mutually exclusive quantile bins by sorted (value, row_index).

    Each row appears in exactly one bin. Sum of bin sizes equals n.
    Ties broken by original row index for determinism.
    """
    n = len(values)
    if n == 0:
        return {f"q{i}": [] for i in range(1, n_bins + 1)}
    indices = list(row_indices) if row_indices is not None else list(range(n))
    if len(indices) != n:
        raise ValueError("row_indices length must match values")
    # Sort by starting value, then row index
    order = sorted(range(n), key=lambda i: (float(values[i]), int(indices[i])))
    # Contiguous rank partitions
    bins: dict[str, list[int]] = {f"q{i}": [] for i in range(1, n_bins + 1)}
    for rank, pos in enumerate(order):
        # rank in [0, n); map to bin [0, n_bins)
        bin_idx = min(n_bins - 1, (rank * n_bins) // n)
        bins[f"q{bin_idx + 1}"].append(int(indices[pos]))
    return bins


def quantile_assignment_report(
    values: Sequence[float],
    *,
    covered: Sequence[bool] | None = None,
) -> dict[str, Any]:
    """Exclusive assignment + optional per-bin coverage."""
    n = len(values)
    exclusive = assign_exclusive_quantiles(values)
    buggy = buggy_overlapping_quantile_assignment(values) if n else {}

    exclusive_counts = {k: len(v) for k, v in exclusive.items()}
    buggy_counts = {k: len(v) for k, v in buggy.items()} if buggy else {}

    # Set algebra
    sets = {k: set(v) for k, v in exclusive.items()}
    intersection = set.intersection(*sets.values()) if sets else set()
    union = set.union(*sets.values()) if sets else set()
    sum_counts = sum(exclusive_counts.values())

    coverage_by_q: dict[str, Any] = {}
    if covered is not None and len(covered) == n:
        cov_map = {i: bool(covered[i]) for i in range(n)}
        for q, idxs in exclusive.items():
            if not idxs:
                coverage_by_q[q] = {"n_pairs": 0, "coverage": None}
            else:
                hits = sum(1 for i in idxs if cov_map[i])
                coverage_by_q[q] = {
                    "n_pairs": len(idxs),
                    "coverage": hits / len(idxs),
                }

    buggy_sum = sum(buggy_counts.values()) if buggy_counts else 0
    return {
        "n": n,
        "exclusive_counts": exclusive_counts,
        "exclusive_sum": sum_counts,
        "exclusive_sum_equals_n": sum_counts == n,
        "pairwise_intersection_empty": len(intersection) == 0,
        "union_equals_full": union == set(range(n)),
        "each_row_exactly_once": sum_counts == n and len(union) == n,
        "coverage_by_starting_value_quantile": coverage_by_q,
        "buggy_v011_style_counts": buggy_counts,
        "buggy_sum": buggy_sum,
        "buggy_sum_exceeds_n": buggy_sum > n if n else False,
        "q4_bug_detected_in_legacy_method": bool(
            buggy_counts.get("q4", 0) == n and n > 0 and buggy_sum > n
        ),
    }


def detect_q4_bug_from_counts(counts: dict[str, int], *, n: int) -> dict[str, Any]:
    """Detect invalid published quantile counts (e.g. q4 == n while sum > n)."""
    total = sum(int(v) for v in counts.values())
    q4 = int(counts.get("q4") or 0)
    return {
        "published_counts": counts,
        "n": n,
        "sum": total,
        "sum_equals_n": total == n,
        "q4_equals_full_test": q4 == n and n > 0,
        "invalid": total != n or q4 == n,
        "regression_rejected": total != n or (q4 == n and total > n),
    }
