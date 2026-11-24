"""Applicability of Source B pairs against frozen Source A feature contract."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER
from human_simulator.unified_v0121.policy import VERSION


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


def missingness_report(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    if not pairs:
        return {"n_pairs": 0, "fraction_prior_mean_missing": None}
    n = len(pairs)
    prior_miss = sum(
        1
        for p in pairs
        if float((p.get("model_features") or {}).get("prior_mean_missing_flag") or 0) >= 0.5
    )
    return {
        "n_pairs": n,
        "fraction_prior_mean_missing": prior_miss / n,
        "fraction_has_prior_history": sum(
            1
            for p in pairs
            if float((p.get("model_features") or {}).get("has_prior_history") or 0) >= 0.5
        )
        / n,
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
    max_ood_fraction: float = 0.35,
) -> dict[str, Any]:
    contract = check_feature_contract(b_pairs)
    miss = missingness_report(b_pairs)
    horizons = [float(p["horizon_days"]) for p in b_pairs]
    hz = horizon_vs_train_quantiles(horizons, a_train_horizons)
    ood = hz.get("ood_fraction")
    ood_ok = ood is None or float(ood) <= max_ood_fraction
    pass_gate = bool(contract["contract_ok"]) and ood_ok and len(b_pairs) > 0
    if not b_pairs:
        status = "INSUFFICIENT_DATA"
    elif hz.get("status") == "NO_A_TRAIN_REFERENCE" and pass_gate:
        status = "APPLICABILITY_CHECK_PARTIAL"
        pass_gate = True  # feature contract ok; OOD incomplete
    elif pass_gate:
        status = "APPLICABILITY_CHECK_PASS"
    else:
        status = "APPLICABILITY_CHECK_FAIL"
    return {
        "version": VERSION,
        "applicability_status": status,
        "feature_contract": contract,
        "missingness": miss,
        "horizon_ood": hz,
        "max_ood_fraction": max_ood_fraction,
        "ood_ok": ood_ok,
        "pass": pass_gate,
        "b_cannot_tune_a": True,
        "note": (
            "Range/missingness check only — not a production clinical OOD detector."
        ),
    }
