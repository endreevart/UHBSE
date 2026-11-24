"""Carry v0.2.1 regime status. No new regime model in this closure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v0211.policy import (
    ACCEPTED_V021_ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
)


def correct_regimes(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    prior = json.loads(
        (root / ACCEPTED_V021_ARTIFACT_DIR / "regime-methodology-correction.json").read_text(
            encoding="utf-8"
        )
    )
    doc = {
        "version": VERSION,
        "no_new_regime_model": True,
        "carried_from": "0.2.1",
        "REGIME_NUMERICAL_STABILITY_STATUS": prior.get("REGIME_NUMERICAL_STABILITY_STATUS"),
        "REGIME_CONFOUNDING_STATUS": prior.get("REGIME_CONFOUNDING_STATUS"),
        "REGIME_FOUNDATION_ACCEPTANCE_STATUS": "NOT_ACCEPTED_RETROSPECTIVE_ONLY",
        "not_runtime_prediction": True,
        "engine_inference_forbidden": True,
        "ok": True,
    }
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR / "regime-methodology-correction.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
