"""Load accepted v0.1 frozen providers — no refit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.global_state_v011.policy import (
    ACCEPTED_V01_ARTIFACT_DIR,
    ACCEPTED_V01_RUNTIME_DIR,
)
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)


def load_v01_registry(root: Path) -> dict[str, Any]:
    path = Path(root) / ACCEPTED_V01_ARTIFACT_DIR / "global-provider-registry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_v01_global_split(root: Path) -> dict[str, Any]:
    path = Path(root) / ACCEPTED_V01_RUNTIME_DIR / "global-subject-split-manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def registry_to_frozen_list(registry: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in registry.get("providers") or []:
        out.append(
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
    return out


def build_ensemble(registry: dict[str, Any]) -> SingleOutcomeTrajectoryEnsemble:
    return SingleOutcomeTrajectoryEnsemble(registry_to_frozen_list(registry))


def provider_lookup(registry: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(p["outcome"], p["unit"]): p for p in (registry.get("providers") or [])}
