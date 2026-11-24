"""Runtime applicability assessment for Source A trajectory providers (v0.1.1)."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER
from human_simulator.trajectory_expansion_v011.policy import OOD_FRACTION_THRESHOLD, VERSION


def _feat(pair_or_features: dict[str, Any]) -> dict[str, Any]:
    if "model_features" in pair_or_features:
        return dict(pair_or_features["model_features"] or {})
    return dict(pair_or_features)


def assess_feature_vector(
    features: dict[str, Any],
    appl_ref: dict[str, Any],
    *,
    require_y0: bool = True,
) -> dict[str, Any]:
    """Return IN_SUPPORT | OUT_OF_SUPPORT | PARTIAL_SUPPORT | UNSUPPORTED_INPUT."""
    reasons: list[str] = []
    feats = _feat(features)

    if require_y0:
        if "y_t0" not in feats or feats.get("y_t0") is None:
            return {
                "applicability_status": "UNSUPPORTED_INPUT",
                "pass": False,
                "reasons": ["missing_required_y_t0"],
                "version": VERSION,
            }

    # Required feature slots
    missing_slots = [n for n in FEATURE_ORDER if n not in feats]
    if missing_slots:
        reasons.append(f"missing_feature_slots:{len(missing_slots)}")

    support = appl_ref.get("feature_support") or {}
    # Prefer embedded support; else horizon_quantiles from scientific_v02 ref
    horizon = float(feats.get("horizon_days") or 0.0)
    hq = appl_ref.get("horizon_quantiles") or {}
    h_lo = hq.get("p05")
    h_hi = hq.get("p95")
    if h_lo is None and "horizon_days" in support:
        h_lo = (support["horizon_days"] or {}).get("p05")
        h_hi = (support["horizon_days"] or {}).get("p95")
    horizon_ood = False
    if h_lo is not None and h_hi is not None:
        if horizon < float(h_lo) or horizon > float(h_hi):
            horizon_ood = True
            reasons.append("horizon_ood")

    ood_feats = []
    for name in FEATURE_ORDER:
        if name == "horizon_days":
            continue
        bounds = support.get(name) or {}
        lo = bounds.get("p01")
        hi = bounds.get("p99")
        if lo is None or hi is None:
            continue
        try:
            val = float(feats[name])
        except (TypeError, ValueError, KeyError):
            continue
        if val < float(lo) or val > float(hi):
            ood_feats.append(name)
    if ood_feats:
        reasons.append(f"feature_ood:{','.join(ood_feats[:5])}")

    thr = float(appl_ref.get("ood_fraction_threshold") or OOD_FRACTION_THRESHOLD)
    # Single-vector: treat any hard OOD as OUT/PARTIAL
    if "missing_required_y_t0" in reasons:
        status = "UNSUPPORTED_INPUT"
    elif missing_slots and (horizon_ood or ood_feats):
        status = "OUT_OF_SUPPORT"
    elif missing_slots:
        status = "PARTIAL_SUPPORT"
    elif horizon_ood and ood_feats:
        status = "OUT_OF_SUPPORT"
    elif horizon_ood or ood_feats:
        # single-feature OOD → OUT_OF_SUPPORT if beyond threshold semantics
        status = "OUT_OF_SUPPORT" if (horizon_ood or len(ood_feats) / max(len(FEATURE_ORDER), 1) >= thr) else "PARTIAL_SUPPORT"
        if len(ood_feats) == 1 and not horizon_ood:
            status = "PARTIAL_SUPPORT"
        if horizon_ood and not ood_feats:
            status = "OUT_OF_SUPPORT"
    else:
        status = "IN_SUPPORT"

    # Hash alone never implies support — explicit evaluation above
    return {
        "version": VERSION,
        "applicability_status": status,
        "pass": status == "IN_SUPPORT",
        "reasons": reasons,
        "horizon_ood": horizon_ood,
        "ood_features": ood_feats,
        "missing_feature_slots": missing_slots,
        "applicability_reference_hash_present": bool(
            appl_ref.get("applicability_reference_hash")
            or appl_ref.get("training_pair_manifest_hash")
        ),
        "hash_alone_not_sufficient": True,
    }


def assess_heldout_applicability(
    pairs: list[dict[str, Any]], appl_ref: dict[str, Any]
) -> dict[str, Any]:
    """Held-out Source A applicability sample (not Source B)."""
    if not pairs:
        return {
            "version": VERSION,
            "source_a_heldout_applicability_status": "INSUFFICIENT_DATA",
            "pass": False,
            "n_pairs": 0,
        }
    statuses = []
    horizon_ood_n = 0
    for p in pairs:
        r = assess_feature_vector(p, appl_ref)
        statuses.append(r["applicability_status"])
        if r.get("horizon_ood"):
            horizon_ood_n += 1
    n = len(statuses)
    in_n = sum(1 for s in statuses if s == "IN_SUPPORT")
    out_n = sum(1 for s in statuses if s == "OUT_OF_SUPPORT")
    part_n = sum(1 for s in statuses if s == "PARTIAL_SUPPORT")
    uns_n = sum(1 for s in statuses if s == "UNSUPPORTED_INPUT")
    ood_frac = horizon_ood_n / n
    thr = float(appl_ref.get("ood_fraction_threshold") or OOD_FRACTION_THRESHOLD)
    ok = ood_frac <= thr and uns_n == 0 and out_n / n <= thr
    return {
        "version": VERSION,
        "source_a_heldout_applicability_status": (
            "APPLICABILITY_CHECK_PASS" if ok else "APPLICABILITY_CHECK_FAIL"
        ),
        "pass": ok,
        "n_pairs": n,
        "in_support_fraction": in_n / n,
        "out_of_support_fraction": out_n / n,
        "partial_support_fraction": part_n / n,
        "unsupported_fraction": uns_n / n,
        "horizon_ood_fraction": ood_frac,
        "ood_fraction_threshold": thr,
        "note": "Source A held-out check; not Source B transfer.",
    }
