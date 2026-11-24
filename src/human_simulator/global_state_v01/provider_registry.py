"""Global-split frozen provider registry with full reload equality."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.global_state_v01.policy import VERSION
from human_simulator.scientific.models import FEATURE_ORDER
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def build_global_provider_registry(frozen_results: list[dict[str, Any]]) -> dict[str, Any]:
    providers = []
    for r in frozen_results:
        fr = r.get("frozen")
        if not fr:
            continue
        ridge = fr.get("ridge") or {}
        coef = ridge.get("coef") or []
        means = (ridge.get("scaler") or {}).get("means") or []
        stds = (ridge.get("scaler") or {}).get("stds") or []
        feat_n = len(fr.get("feature_order") or FEATURE_ORDER)
        dim_ok = len(coef) == feat_n and len(means) == feat_n and len(stds) == feat_n
        providers.append(
            {
                "grain_id": fr.get("grain_id"),
                "outcome": fr.get("outcome"),
                "unit": fr.get("unit"),
                "active_provider": fr.get("active_provider"),
                "global_split_hash": fr.get("global_split_hash"),
                "train_manifest_hash": fr.get("train_manifest_hash"),
                "model_file_hash": fr.get("model_file_hash"),
                "model_identity_hash": fr.get("model_identity_hash"),
                "active_uncertainty": fr.get("active_uncertainty"),
                "applicability_reference": fr.get("applicability_reference"),
                "feature_order": fr.get("feature_order"),
                "feature_schema_hash": fr.get("feature_schema_hash"),
                "dimension_equality_ok": dim_ok,
                "coef_dim": len(coef),
                "feature_dim": feat_n,
                "model_payload": {
                    "ridge": ridge,
                    "seed": fr.get("seed"),
                    "l2": fr.get("l2"),
                },
            }
        )
    providers.sort(key=lambda p: (str(p.get("outcome")), str(p.get("unit"))))
    return {
        "version": VERSION,
        "GLOBAL_PROVIDER_REGISTRY_STATUS": "PASS" if providers else "FAIL",
        "n_providers": len(providers),
        "all_dimension_equality_ok": all(p.get("dimension_equality_ok") for p in providers),
        "registry_hash": _hash(
            [
                {
                    "grain_id": p["grain_id"],
                    "model_file_hash": p["model_file_hash"],
                    "model_identity_hash": p["model_identity_hash"],
                    "interval_payload_hash": (p.get("active_uncertainty") or {}).get(
                        "interval_payload_hash"
                    ),
                    "global_split_hash": p.get("global_split_hash"),
                }
                for p in providers
            ]
        ),
        "providers": providers,
        "usable_without_clinical_db": True,
    }


def reload_all_providers_equality(registry: dict[str, Any]) -> dict[str, Any]:
    """Reload EVERY provider and compare predictions — not a sample of 20."""
    providers = registry.get("providers") or []
    frozen_like = []
    for p in providers:
        frozen_like.append(
            {
                "outcome": p["outcome"],
                "unit": p["unit"],
                "grain_id": p["grain_id"],
                "active_provider": p["active_provider"],
                "model_file_hash": p["model_file_hash"],
                "model_identity_hash": p["model_identity_hash"],
                "ridge": (p.get("model_payload") or {}).get("ridge"),
                "seed": (p.get("model_payload") or {}).get("seed"),
                "l2": (p.get("model_payload") or {}).get("l2"),
                "active_uncertainty": p.get("active_uncertainty"),
                "applicability_reference": p.get("applicability_reference"),
                "feature_order": p.get("feature_order"),
            }
        )

    # One component per provider
    snap = {
        "snapshot_id": "reload-all",
        "subject_id": "opaque-reload",
        "components": [
            {
                "outcome": p["outcome"],
                "unit": p["unit"],
                "numeric_value": 10.0,
                "n_prior_measurements": 2.0,
                "has_prior_history": 1.0,
                "prior_mean": 10.0,
                "prior_last_delta": 0.1,
                "days_since_first": 60.0,
            }
            for p in frozen_like
        ],
    }
    ens1 = SingleOutcomeTrajectoryEnsemble(frozen_like)
    pred1 = ens1.predict_snapshot(snap, horizon_days=30.0)
    blob = json.dumps(registry, sort_keys=True, default=str)
    reloaded = json.loads(blob)
    frozen2 = []
    for p in reloaded.get("providers") or []:
        frozen2.append(
            {
                "outcome": p["outcome"],
                "unit": p["unit"],
                "grain_id": p["grain_id"],
                "active_provider": p["active_provider"],
                "model_file_hash": p["model_file_hash"],
                "model_identity_hash": p["model_identity_hash"],
                "ridge": (p.get("model_payload") or {}).get("ridge"),
                "seed": (p.get("model_payload") or {}).get("seed"),
                "l2": (p.get("model_payload") or {}).get("l2"),
                "active_uncertainty": p.get("active_uncertainty"),
                "applicability_reference": p.get("applicability_reference"),
                "feature_order": p.get("feature_order"),
            }
        )
    ens2 = SingleOutcomeTrajectoryEnsemble(frozen2)
    pred2 = ens2.predict_snapshot(snap, horizon_days=30.0)
    h1 = _hash(pred1.get("predictions"))
    h2 = _hash(pred2.get("predictions"))

    # Per-provider smoke: each provider produces a prediction or typed refusal
    per_ok = 0
    for p in frozen_like:
        mini = SingleOutcomeTrajectoryEnsemble([p])
        snap1 = {
            "subject_id": "x",
            "components": [
                {
                    "outcome": p["outcome"],
                    "unit": p["unit"],
                    "numeric_value": 0.0,  # zero preservation
                    "n_prior_measurements": 2.0,
                    "has_prior_history": 1.0,
                    "prior_mean": 0.0,
                    "prior_last_delta": 0.0,
                    "days_since_first": 30.0,
                }
            ],
        }
        out = mini.predict_snapshot(snap1, horizon_days=30.0)
        if out.get("n_predictions", 0) + out.get("n_unsupported", 0) >= 1:
            per_ok += 1

    # Zero pad/truncate check
    zero_pad_ok = True
    for p in frozen_like:
        ridge = p.get("ridge") or {}
        coef = ridge.get("coef") or []
        feat_n = len(p.get("feature_order") or FEATURE_ORDER)
        if len(coef) != feat_n:
            zero_pad_ok = False
            break

    ok = (
        h1 == h2
        and len(providers) > 0
        and per_ok == len(frozen_like)
        and zero_pad_ok
        and all(p.get("model_file_hash") for p in providers)
    )
    return {
        "ok": ok,
        "n_providers": len(providers),
        "n_smoke_ok": per_ok,
        "predictions_hash_before": h1,
        "predictions_hash_after": h2,
        "equality": h1 == h2,
        "zero_pad_truncate_ok": zero_pad_ok,
        "all_file_hashes_present": all(p.get("model_file_hash") for p in providers),
    }


def write_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
