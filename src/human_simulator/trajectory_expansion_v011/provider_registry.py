"""Serialized frozen provider registry with reload equality checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)
from human_simulator.trajectory_expansion_v011.policy import VERSION


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def build_provider_registry(frozen_results: list[dict[str, Any]]) -> dict[str, Any]:
    providers = []
    for r in frozen_results:
        fr = r.get("frozen")
        if not fr:
            continue
        providers.append(
            {
                "grain_id": fr.get("grain_id"),
                "outcome": fr.get("outcome"),
                "unit": fr.get("unit"),
                "active_provider": fr.get("active_provider"),
                "model_file_hash": fr.get("model_file_hash"),
                "model_identity_hash": fr.get("model_identity_hash"),
                "feature_contract": {
                    "feature_order": fr.get("feature_order"),
                    "feature_schema_hash": fr.get("feature_schema_hash"),
                },
                "active_uncertainty": fr.get("active_uncertainty"),
                "applicability_reference": fr.get("applicability_reference"),
                "dataset_split_train_hashes": {
                    "split_hash": fr.get("split_hash"),
                    "train_manifest_hash": fr.get("train_manifest_hash"),
                    "dataset_pair_count": fr.get("dataset_pair_count"),
                },
                "model_payload": {
                    "ridge": fr.get("ridge"),
                    "seed": fr.get("seed"),
                    "l2": fr.get("l2"),
                },
            }
        )
    providers.sort(key=lambda p: (str(p.get("outcome")), str(p.get("unit"))))
    return {
        "version": VERSION,
        "FROZEN_PROVIDER_REGISTRY_STATUS": "PASS" if providers else "FAIL",
        "n_providers": len(providers),
        "registry_hash": _hash(
            [
                {
                    "grain_id": p["grain_id"],
                    "model_file_hash": p["model_file_hash"],
                    "model_identity_hash": p["model_identity_hash"],
                    "interval_payload_hash": (p.get("active_uncertainty") or {}).get(
                        "interval_payload_hash"
                    ),
                }
                for p in providers
            ]
        ),
        "providers": providers,
        "usable_without_clinical_db": True,
    }


def write_provider_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_provider_registry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reload_and_check_equality(
    registry: dict[str, Any], *, horizon_days: float = 30.0
) -> dict[str, Any]:
    """Predict before/after reload; compare prediction payloads."""
    providers = registry.get("providers") or []
    # Expand to frozen-shaped objects
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
                "feature_order": (p.get("feature_contract") or {}).get("feature_order"),
                "feature_schema_hash": (p.get("feature_contract") or {}).get(
                    "feature_schema_hash"
                ),
            }
        )

    # Deterministic synthetic snapshot — non-clinical values inside support-ish range
    snap = {
        "snapshot_id": "reload-equality",
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
            for p in frozen_like[: min(20, len(frozen_like))]
        ],
    }
    ens1 = SingleOutcomeTrajectoryEnsemble(frozen_like)
    pred1 = ens1.predict_snapshot(snap, horizon_days=horizon_days)
    # Serialize + reload
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
            }
        )
    ens2 = SingleOutcomeTrajectoryEnsemble(frozen2)
    pred2 = ens2.predict_snapshot(snap, horizon_days=horizon_days)
    h1 = _hash(pred1.get("predictions"))
    h2 = _hash(pred2.get("predictions"))
    hash_ok = all(p.get("model_file_hash") for p in providers)
    return {
        "ok": h1 == h2 and hash_ok and len(providers) > 0,
        "n_providers": len(providers),
        "predictions_hash_before": h1,
        "predictions_hash_after": h2,
        "equality": h1 == h2,
        "all_file_hashes_present": hash_ok,
    }
