"""Applicability reference from exact v0.2 train pairs."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER
from human_simulator.scientific_v02.policy import MAX_OOD_FRACTION, VERSION


def _pct(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    return sorted_vals[int(q * (len(sorted_vals) - 1))]


def build_applicability_reference(
    train_pairs: list[dict[str, Any]],
    *,
    training_pair_manifest_hash: str,
    feature_schema_hash: str | None,
    scaler_fit_n_rows: int,
) -> dict[str, Any]:
    assert scaler_fit_n_rows == len(train_pairs)
    horizons = sorted(float(p["horizon_days"]) for p in train_pairs)
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
            "p01": _pct(vs, 0.01),
            "p05": _pct(vs, 0.05),
            "p25": _pct(vs, 0.25),
            "p50": _pct(vs, 0.50),
            "p75": _pct(vs, 0.75),
            "p95": _pct(vs, 0.95),
            "p99": _pct(vs, 0.99),
            "binary_support": sorted(set(vs)) if name.endswith("_flag") or name == "has_prior_history" else None,
        }
    return {
        "version": VERSION,
        "source_a_applicability_reference_status": "BUILT",
        "n_train_pairs": len(train_pairs),
        "scaler_fit_n_rows": scaler_fit_n_rows,
        "training_pair_manifest_hash": training_pair_manifest_hash,
        "feature_schema_hash": feature_schema_hash,
        "feature_order": list(FEATURE_ORDER),
        "horizon_quantiles": {
            k: _pct(horizons, q)
            for k, q in (
                ("p01", 0.01),
                ("p05", 0.05),
                ("p25", 0.25),
                ("p50", 0.50),
                ("p75", 0.75),
                ("p95", 0.95),
                ("p99", 0.99),
            )
        }
        | {"min": horizons[0], "max": horizons[-1]},
        "feature_distributions": feature_stats,
        "max_ood_fraction_declared_before_shadow_metrics": MAX_OOD_FRACTION,
        "not_production_ood_detector": True,
        "exploratory_applicability_profile": True,
        "equalities": {
            "scaler_fit_n_rows_eq_n_train_pairs": scaler_fit_n_rows == len(train_pairs),
            "manifest_hash_bound": True,
        },
    }


def assess_b_applicability(
    b_pairs: list[dict[str, Any]],
    reference: dict[str, Any],
    *,
    max_ood_fraction: float = MAX_OOD_FRACTION,
) -> dict[str, Any]:
    if not b_pairs:
        return {
            "version": VERSION,
            "source_b_applicability_status": "INSUFFICIENT_DATA",
            "pass": False,
            "max_ood_fraction": max_ood_fraction,
        }

    missing_slots = 0
    for p in b_pairs:
        feats = p.get("model_features") or {}
        for name in FEATURE_ORDER:
            if name not in feats:
                missing_slots += 1
    contract_ok = missing_slots == 0

    hz_ref = reference.get("horizon_quantiles") or {}
    lo = hz_ref.get("p05")
    hi = hz_ref.get("p95")
    horizons = [float(p["horizon_days"]) for p in b_pairs]
    if lo is None or hi is None:
        ood_frac = None
        hz_status = "NO_A_TRAIN_REFERENCE"
    else:
        ood = sum(1 for h in horizons if h < float(lo) or h > float(hi))
        ood_frac = ood / len(horizons)
        hz_status = "COMPUTED"

    # per-feature p05/p95 violations
    feat_ood = {}
    dist = reference.get("feature_distributions") or {}
    out_support_flags = [False] * len(b_pairs)
    for name in FEATURE_ORDER:
        stats = dist.get(name) or {}
        p05, p95 = stats.get("p05"), stats.get("p95")
        viol = 0
        for i, p in enumerate(b_pairs):
            v = (p.get("model_features") or {}).get(name)
            if v is None or p05 is None or p95 is None:
                continue
            if float(v) < float(p05) or float(v) > float(p95):
                viol += 1
                out_support_flags[i] = True
        feat_ood[name] = {"n_violations": viol, "fraction": viol / len(b_pairs)}

    if hz_status == "COMPUTED" and ood_frac is not None:
        for i, h in enumerate(horizons):
            if h < float(lo) or h > float(hi):
                out_support_flags[i] = True

    n_out = sum(1 for x in out_support_flags if x)
    frac_out = n_out / len(b_pairs)
    in_support = [p for p, flag in zip(b_pairs, out_support_flags) if not flag]
    out_support = [p for p, flag in zip(b_pairs, out_support_flags) if flag]

    ood_ok = ood_frac is not None and float(ood_frac) <= max_ood_fraction
    if not contract_ok:
        status = "APPLICABILITY_CHECK_FAIL"
        pass_gate = False
    elif hz_status != "COMPUTED" or ood_frac is None:
        status = "APPLICABILITY_CHECK_PARTIAL"
        pass_gate = False
    elif ood_ok and frac_out <= max_ood_fraction:
        status = "APPLICABILITY_CHECK_PASS"
        pass_gate = True
    else:
        status = "APPLICABILITY_CHECK_FAIL"
        pass_gate = False

    return {
        "version": VERSION,
        "source_b_applicability_status": status,
        "pass": pass_gate,
        "feature_contract_complete": contract_ok,
        "missing_feature_slots": missing_slots,
        "horizon_ood": {
            "status": hz_status,
            "a_train_p05": lo,
            "a_train_p95": hi,
            "ood_fraction": ood_frac,
        },
        "per_feature_ood": feat_ood,
        "fraction_pairs_outside_declared_support": frac_out,
        "n_in_support_pairs": len(in_support),
        "n_out_of_support_pairs": len(out_support),
        "n_subjects_in_support": len({p["opaque_subject_key"] for p in in_support}),
        "n_subjects_out_of_support": len({p["opaque_subject_key"] for p in out_support}),
        "max_ood_fraction": max_ood_fraction,
        "threshold_declared_before_shadow_metrics": True,
        "not_production_ood_detector": True,
        "not_clinical_ood_detector": True,
        "_runtime_in_support": in_support,
        "_runtime_out_support": out_support,
    }
