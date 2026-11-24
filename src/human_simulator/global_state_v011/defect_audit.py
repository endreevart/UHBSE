"""v0.1 horizon-mismatch defect audit (does not rewrite prior metrics)."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from human_simulator.global_state_v011.policy import (
    ACCEPTED_V01_ARTIFACT_DIR,
    ACCEPTED_V01_RUNTIME_DIR,
    V01_FIXED_PREDICTION_HORIZON_DAYS,
    VERSION,
)
from human_simulator.global_state_v01.state_assembler import (
    assemble_individual_state,
    _parse_ts,
)
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)


def _med(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return float(s[len(s) // 2])


def audit_v01_horizon_defect(
    *,
    root: Path,
    subject_observations: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] | None = None,
    ensemble: SingleOutcomeTrajectoryEnsemble | None = None,
    provider_active: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    """Quantify fixed-30d prediction vs actual next-observation horizon in v0.1 private states."""
    priv = json.loads(
        (Path(root) / ACCEPTED_V01_RUNTIME_DIR / "heldout-states-private.json").read_text(
            encoding="utf-8"
        )
    )
    backtest_pub = json.loads(
        (
            Path(root)
            / ACCEPTED_V01_ARTIFACT_DIR
            / "real-heldout-multi-outcome-backtest.json"
        ).read_text(encoding="utf-8")
    )

    pred_h = float(V01_FIXED_PREDICTION_HORIZON_DAYS)
    actuals: list[float] = []
    exact = 0
    mismatch = 0
    by_provider = {
        "ridge": {"exact": 0, "mismatch": 0, "n": 0},
        "persistence": {"exact": 0, "mismatch": 0, "n": 0},
        "other": {"exact": 0, "mismatch": 0, "n": 0},
    }
    ridge_deltas: list[float] = []
    ridge_abs_deltas: list[float] = []
    n_ridge_recomputed = 0

    for st in priv.get("states") or []:
        sid = st["opaque_subject_key"]
        cut = _parse_ts(st.get("cutoff"))
        for t in st.get("targets") or []:
            actual = float(t["horizon_days"])
            actuals.append(actual)
            is_exact = abs(actual - pred_h) < 1e-9
            if is_exact:
                exact += 1
            else:
                mismatch += 1
            ou = (t["outcome"], t["unit"])
            ap = (provider_active or {}).get(ou, "other")
            bucket = ap if ap in by_provider else "other"
            by_provider[bucket]["n"] += 1
            if is_exact:
                by_provider[bucket]["exact"] += 1
            else:
                by_provider[bucket]["mismatch"] += 1

            # Ridge prediction change 30d → actual horizon (when obs + ensemble available)
            if (
                ap == "ridge"
                and ensemble is not None
                and subject_observations is not None
                and cut is not None
            ):
                obs_map = subject_observations.get(sid) or {}
                if ou not in obs_map:
                    continue
                s30 = assemble_individual_state(
                    opaque_subject_key=sid,
                    cutoff=cut,
                    observations_by_ou={ou: obs_map[ou]},
                    ensemble=ensemble,
                    horizon_days=pred_h,
                )
                sact = assemble_individual_state(
                    opaque_subject_key=sid,
                    cutoff=cut,
                    observations_by_ou={ou: obs_map[ou]},
                    ensemble=ensemble,
                    horizon_days=actual,
                )
                p30 = next((c.get("prediction") for c in s30["components"] if c.get("prediction")), None)
                pact = next(
                    (c.get("prediction") for c in sact["components"] if c.get("prediction")),
                    None,
                )
                if p30 and pact:
                    d = float(pact["y_pred"]) - float(p30["y_pred"])
                    ridge_deltas.append(d)
                    ridge_abs_deltas.append(abs(d))
                    n_ridge_recomputed += 1

    n = len(actuals)
    hist = Counter(int(h) for h in actuals)
    # coarse bins for audit
    bins = {
        "1_30": sum(1 for h in actuals if 1 <= h <= 30),
        "31_90": sum(1 for h in actuals if 30 < h <= 90),
        "91_180": sum(1 for h in actuals if 90 < h <= 180),
        "181_365": sum(1 for h in actuals if 180 < h <= 365),
        "gt_365": sum(1 for h in actuals if h > 365),
        "lt_1": sum(1 for h in actuals if h < 1),
    }

    status = "INVALID_FOR_HORIZON_ALIGNED_EVALUATION"
    return {
        "version": VERSION,
        "PRIOR_V01_BACKTEST_HORIZON_STATUS": status,
        "defect_statement": (
            "v0.1 built predictions with horizon_days=30 but compared them to the "
            "strict next observation at the actual horizon (1–923 days)."
        ),
        "prediction_horizon_days_v01": pred_h,
        "n_targets_audited": n,
        "n_exact_horizon_matches": exact,
        "frac_exact_horizon_matches": (exact / n) if n else None,
        "n_horizon_mismatches": mismatch,
        "frac_horizon_mismatches": (mismatch / n) if n else None,
        "actual_horizon_distribution": {
            "n": n,
            "min": min(actuals) if actuals else None,
            "max": max(actuals) if actuals else None,
            "median": _med(actuals),
            "bins": bins,
            "n_unique_integer_horizons": len(hist),
        },
        "mismatch_by_active_provider": by_provider,
        "ridge_prediction_change_30_to_actual": {
            "n_recomputed": n_ridge_recomputed,
            "median_delta": _med(ridge_deltas),
            "median_abs_delta": _med(ridge_abs_deltas),
            "mean_abs_delta": (
                sum(ridge_abs_deltas) / len(ridge_abs_deltas) if ridge_abs_deltas else None
            ),
            "frac_nonzero_abs_delta": (
                sum(1 for d in ridge_abs_deltas if d > 1e-12) / len(ridge_abs_deltas)
                if ridge_abs_deltas
                else None
            ),
        },
        "prior_v01_metrics_preserved_not_rewritten": True,
        "prior_v01_backtest_status_field": backtest_pub.get(
            "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS"
        ),
        "prior_v01_n_prediction_targets": backtest_pub.get("n_prediction_targets"),
        "prior_v01_n_outcomes_evaluated": backtest_pub.get("n_outcomes_evaluated"),
        "does_not_invalidate_global_split": True,
        "does_not_invalidate_frozen_providers": True,
        "does_not_invalidate_engine_technical_shadow": True,
        "audit_hash": hashlib.sha256(
            json.dumps(
                {
                    "n": n,
                    "exact": exact,
                    "mismatch": mismatch,
                    "bins": bins,
                    "ridge_n": n_ridge_recomputed,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }
