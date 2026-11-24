"""Finite-sample permutation / shuffle probability correction."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_v012.policy import (
    SHUFFLE_FINITE_SAMPLE_FORMULA,
    SHUFFLE_PERMS,
    shuffle_finite_sample_p,
)


def correct_permutation_probability(
    *,
    n_extreme: int,
    n_permutations: int = SHUFFLE_PERMS,
) -> dict[str, Any]:
    """Apply p = (n_extreme + 1) / (n + 1); never report literal 0 for 0 extremes."""
    n_extreme = int(n_extreme)
    n_permutations = int(n_permutations)
    raw_fraction = (n_extreme / n_permutations) if n_permutations else None
    corrected = shuffle_finite_sample_p(n_extreme, n_permutations)
    return {
        "raw_extreme_count": n_extreme,
        "n_permutations": n_permutations,
        "raw_fraction": raw_fraction,
        "corrected_empirical_probability": corrected,
        "correction_method": SHUFFLE_FINITE_SAMPLE_FORMULA,
        "literal_zero_forbidden_when_extremes_zero": n_extreme == 0,
        "gate_le_0_05": corrected <= 0.05 if corrected is not None else False,
    }


def correct_from_v011_artifact(shuffle_doc: dict[str, Any]) -> dict[str, Any]:
    """Correct a published v0.1.1 shuffle control that reported probability 0.0."""
    n_perm = int(shuffle_doc.get("n_permutations") or SHUFFLE_PERMS)
    # Prefer explicit extreme count; fall back from fraction
    if "n_shuffles_with_mae_le_real" in shuffle_doc:
        n_extreme = int(shuffle_doc["n_shuffles_with_mae_le_real"])
    elif shuffle_doc.get("fraction_shuffles_le_real") is not None:
        n_extreme = int(round(float(shuffle_doc["fraction_shuffles_le_real"]) * n_perm))
    elif shuffle_doc.get("permutation_probability") == 0.0:
        n_extreme = 0
    else:
        n_extreme = 0
    fix = correct_permutation_probability(n_extreme=n_extreme, n_permutations=n_perm)
    prior_p = shuffle_doc.get("permutation_probability", shuffle_doc.get("fraction_shuffles_le_real"))
    return {
        "prior_reported_probability": prior_p,
        "prior_defect_literal_zero": prior_p == 0.0 and n_extreme == 0,
        **fix,
        "signal_gate_note": (
            "Signal status may remain supported only if all corrected gates pass "
            f"(corrected p={fix['corrected_empirical_probability']:.6f})."
        ),
    }
