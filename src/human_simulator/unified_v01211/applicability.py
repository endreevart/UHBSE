"""Applicability gate: PARTIAL/FAIL/INSUFFICIENT must not open transfer."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER
from human_simulator.unified_v01211.policy import (
    APPLICABILITY_MAX_OOD_FRACTION,
    VERSION,
)


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = int(q * (len(sorted_vals) - 1))
    return sorted_vals[idx]


def build_source_a_training_applicability_reference(
    train_pairs: list[dict[str, Any]],
    *,
    feature_schema_hash: str | None = None,
    training_population_manifest_hash: str | None = None,
) -> dict[str, Any]:
    """Rebuild A-train reference without refitting the Ridge model."""
    if not train_pairs:
        return {
            "version": VERSION,
            "applicability_reference_status": "UNAVAILABLE",
            "reason": "no_train_pairs",
        }

    horizons = [float(p["horizon_days"]) for p in train_pairs]
    hs = sorted(horizons)
    feature_stats: dict[str, Any] = {}
    for name in FEATURE_ORDER:
        vals: list[float] = []
        missing = 0
        for p in train_pairs:
            feats = p.get("model_features") or {}
            if name not in feats or feats[name] is None:
                missing += 1
                continue
            vals.append(float(feats[name]))
        vs = sorted(vals)
        feature_stats[name] = {
            "n": len(vals),
            "missingness_rate": missing / len(train_pairs),
            "min": vs[0] if vs else None,
            "max": vs[-1] if vs else None,
            "p01": _percentile(vs, 0.01),
            "p05": _percentile(vs, 0.05),
            "p25": _percentile(vs, 0.25),
            "p50": _percentile(vs, 0.50),
            "p75": _percentile(vs, 0.75),
            "p95": _percentile(vs, 0.95),
            "p99": _percentile(vs, 0.99),
        }

    return {
        "version": VERSION,
        "applicability_reference_status": "BUILT",
        "n_train_pairs": len(train_pairs),
        "horizon_quantiles": {
            "p01": _percentile(hs, 0.01),
            "p05": _percentile(hs, 0.05),
            "p25": _percentile(hs, 0.25),
            "p50": _percentile(hs, 0.50),
            "p75": _percentile(hs, 0.75),
            "p95": _percentile(hs, 0.95),
            "p99": _percentile(hs, 0.99),
            "min": hs[0],
            "max": hs[-1],
        },
        "feature_distributions": feature_stats,
        "feature_order": list(FEATURE_ORDER),
        "feature_schema_hash": feature_schema_hash,
        "training_population_manifest_hash": training_population_manifest_hash,
        "provenance_status": "SOURCE_A_TRAIN_PAIRS_NO_REFIT",
        "not_production_ood_detector": True,
        "thresholds_declared_before_transfer_metrics": True,
        "max_ood_fraction": APPLICABILITY_MAX_OOD_FRACTION,
    }


def check_feature_contract(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    missing = 0
    for p in pairs:
        feats = p.get("model_features") or {}
        for name in FEATURE_ORDER:
            if name not in feats:
                missing += 1
    return {
        "feature_order": list(FEATURE_ORDER),
        "n_pairs": len(pairs),
        "missing_feature_slots": missing,
        "contract_ok": missing == 0 and len(pairs) > 0,
    }


def horizon_vs_train_quantiles(
    b_horizons: list[float],
    a_train_horizons: list[float] | None,
) -> dict[str, Any]:
    if not b_horizons:
        return {"status": "INSUFFICIENT", "ood_fraction": None}
    if not a_train_horizons:
        return {
            "status": "NO_A_TRAIN_REFERENCE",
            "b_n": len(b_horizons),
            "ood_fraction": None,
        }
    srt = sorted(a_train_horizons)
    lo = srt[int(0.05 * (len(srt) - 1))]
    hi = srt[int(0.95 * (len(srt) - 1))]
    ood = sum(1 for h in b_horizons if h < lo or h > hi)
    frac = ood / len(b_horizons)
    return {
        "a_train_p05": lo,
        "a_train_p95": hi,
        "b_n": len(b_horizons),
        "ood_count": ood,
        "ood_fraction": frac,
        "status": "COMPUTED",
    }


def assess_applicability(
    *,
    b_pairs: list[dict[str, Any]],
    a_train_horizons: list[float] | None = None,
    max_ood_fraction: float = APPLICABILITY_MAX_OOD_FRACTION,
) -> dict[str, Any]:
    """
    Rules:
      APPLICABILITY_CHECK_PASS -> pass may be true
      APPLICABILITY_CHECK_PARTIAL -> pass must be false
      APPLICABILITY_CHECK_FAIL -> pass must be false
      INSUFFICIENT_DATA -> pass must be false
    ood_fraction=null does NOT imply ood_ok=true.
    """
    contract = check_feature_contract(b_pairs)
    horizons = [float(p["horizon_days"]) for p in b_pairs] if b_pairs else []
    hz = horizon_vs_train_quantiles(horizons, a_train_horizons)
    ood = hz.get("ood_fraction")

    if not b_pairs:
        status = "INSUFFICIENT_DATA"
        pass_gate = False
        ood_ok = False
    elif hz.get("status") == "NO_A_TRAIN_REFERENCE":
        status = "APPLICABILITY_CHECK_PARTIAL"
        pass_gate = False  # PARTIAL must not open gate
        ood_ok = False  # null ood ≠ ok
    elif ood is None:
        status = "APPLICABILITY_CHECK_PARTIAL"
        pass_gate = False
        ood_ok = False
    else:
        ood_ok = float(ood) <= max_ood_fraction
        if contract["contract_ok"] and ood_ok:
            status = "APPLICABILITY_CHECK_PASS"
            pass_gate = True
        else:
            status = "APPLICABILITY_CHECK_FAIL"
            pass_gate = False

    return {
        "version": VERSION,
        "applicability_status": status,
        "feature_contract": contract,
        "horizon_ood": hz,
        "max_ood_fraction": max_ood_fraction,
        "ood_ok": ood_ok,
        "pass": pass_gate,
        "applicability_gate_integrity_status": (
            "PASS"
            if not (
                status == "APPLICABILITY_CHECK_PARTIAL" and pass_gate
            )
            else "FAIL"
        ),
        "b_cannot_tune_a": True,
        "not_production_ood_detector": True,
        "note": (
            "Range/missingness check only — not a production clinical OOD detector. "
            "PARTIAL/FAIL/INSUFFICIENT never open the transfer gate."
        ),
    }
