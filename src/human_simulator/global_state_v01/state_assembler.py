"""IndividualBiologicalState assembler at a cutoff time."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from human_simulator.global_state_v01.policy import VERSION
from human_simulator.trajectory_expansion_v011.applicability_runtime import (
    assess_feature_vector,
)
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
    build_model_features_from_component,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _tie_key(obs: dict[str, Any]) -> tuple:
    """Deterministic same-time tie policy: clinical_time, then source_order, then component_id."""
    return (
        str(obs.get("clinical_time") or obs.get("ts") or ""),
        int(obs.get("source_order") or 0),
        str(obs.get("component_id") or ""),
    )


def assemble_individual_state(
    *,
    opaque_subject_key: str,
    cutoff: datetime | str,
    observations_by_ou: dict[tuple[str, str], list[dict[str, Any]]],
    ensemble: SingleOutcomeTrajectoryEnsemble | None,
    horizon_days: float = 30.0,
) -> dict[str, Any]:
    """Build IndividualBiologicalState at cutoff (data ≤ cutoff only)."""
    cut = _parse_ts(cutoff)
    if cut is None:
        raise ValueError("invalid_cutoff")

    components: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}

    for (outcome, unit), series in sorted(observations_by_ou.items()):
        eligible = []
        for obs in series:
            ts = _parse_ts(obs.get("clinical_time") or obs.get("ts"))
            if ts is None:
                continue
            if ts > cut:
                continue  # future forbidden
            eligible.append(obs)
        if not eligible:
            components.append(
                {
                    "outcome": outcome,
                    "unit": unit,
                    "state_status": "MISSING",
                    "numeric_value": None,
                    "missingness_flag": True,
                    "provider_available": (outcome, unit) in (ensemble.providers if ensemble else {}),
                }
            )
            status_counts["MISSING"] = status_counts.get("MISSING", 0) + 1
            continue

        eligible.sort(key=_tie_key)
        latest = eligible[-1]
        y0 = float(latest["value"])
        ts_latest = _parse_ts(latest.get("clinical_time") or latest.get("ts"))
        assert ts_latest is not None
        staleness_days = (cut - ts_latest).total_seconds() / 86400.0
        priors = eligible[:-1]
        n_prior = len(eligible)
        has_prior = 1.0 if len(priors) >= 1 else 0.0
        prior_mean = (
            sum(float(p["value"]) for p in priors) / len(priors) if priors else None
        )
        prior_last_delta = None
        if len(eligible) >= 2:
            prior_last_delta = float(eligible[-1]["value"]) - float(eligible[-2]["value"])
        first_ts = _parse_ts(eligible[0].get("clinical_time") or eligible[0].get("ts"))
        days_since_first = (
            (ts_latest - first_ts).total_seconds() / 86400.0 if first_ts else None
        )

        # Staleness heuristic: > p95 horizon of provider or > 365d
        stale = staleness_days > 365.0
        state_status = "STALE" if stale else "OBSERVED"

        pred_block = None
        appl_status = None
        provider_available = False
        if ensemble and (outcome, unit) in ensemble.providers:
            provider_available = True
            prov = ensemble.providers[(outcome, unit)]
            if n_prior < 1:
                state_status = "UNSUPPORTED_INPUT"
            else:
                comp = {
                    "outcome": outcome,
                    "unit": unit,
                    "numeric_value": y0,
                    "n_prior_measurements": float(n_prior),
                    "has_prior_history": has_prior,
                    "prior_mean": prior_mean,
                    "prior_last_delta": prior_last_delta,
                    "days_since_first": days_since_first if days_since_first is not None else 1.0,
                }
                built = build_model_features_from_component(comp, horizon_days=horizon_days)
                if not built.get("ok"):
                    state_status = "UNSUPPORTED_INPUT"
                else:
                    appl = assess_feature_vector(
                        built["features"], prov.get("applicability_reference") or {}
                    )
                    appl_status = appl["applicability_status"]
                    if appl_status == "UNSUPPORTED_INPUT":
                        state_status = "UNSUPPORTED_INPUT"
                    elif appl_status == "OUT_OF_SUPPORT":
                        state_status = "OUT_OF_SUPPORT"
                    else:
                        snap = {
                            "subject_id": opaque_subject_key,
                            "components": [comp],
                        }
                        # Predict only this outcome
                        mini = SingleOutcomeTrajectoryEnsemble([prov])
                        pred_doc = mini.predict_snapshot(snap, horizon_days=horizon_days)
                        if pred_doc.get("predictions"):
                            p0 = pred_doc["predictions"][0]
                            pred_block = {
                                "y_pred": p0["y_pred"],
                                "lower": p0["lower"],
                                "upper": p0["upper"],
                                "active_provider": p0.get("active_provider"),
                                "applicability_status": p0.get("applicability_status"),
                                "model_identity_hash": p0.get("model_identity_hash"),
                                "horizon_days": horizon_days,
                                "record_origin": "PREDICTED",
                            }
                            state_status = "PREDICTABLE"

        components.append(
            {
                "outcome": outcome,
                "unit": unit,
                "state_status": state_status,
                "numeric_value": y0,
                "observation_timestamp_hash": _hash(str(ts_latest)),
                "staleness_days": staleness_days,
                "n_prior_measurements": n_prior,
                "prior_mean": prior_mean,
                "prior_last_delta": prior_last_delta,
                "days_since_first": days_since_first,
                "prior_mean_missing_flag": prior_mean is None,
                "prior_last_delta_missing_flag": prior_last_delta is None,
                "missingness_flag": False,
                "provider_available": provider_available,
                "applicability_status": appl_status,
                "prediction": pred_block,
                "provenance_binding_hash": _hash(
                    {
                        "component_id": latest.get("component_id"),
                        "observation_id": latest.get("observation_id"),
                    }
                ),
            }
        )
        status_counts[state_status] = status_counts.get(state_status, 0) + 1

    state = {
        "version": VERSION,
        "INDIVIDUAL_STATE_ASSEMBLY_STATUS": "BUILT",
        "opaque_subject_key": opaque_subject_key,
        "cutoff_hash": _hash(cut.isoformat()),
        "horizon_days": horizon_days,
        "n_components": len(components),
        "status_counts": status_counts,
        "components": components,
        "not_current_state_classifier": True,
        "no_cross_outcome_imputation": True,
        "no_unit_conversion": True,
        "no_medication_rows": True,
    }
    state["state_hash"] = _hash(
        {
            "cutoff_hash": state["cutoff_hash"],
            "status_counts": status_counts,
            "n": len(components),
            "ou": sorted((c["outcome"], c["unit"], c["state_status"]) for c in components),
        }
    )
    return state
