"""Freeze Source A Ridge model artifact; prove SHA-256 stability."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER, FirstLearnedBaseline
from human_simulator.unified_v0121.policy import (
    FIXED_OUTCOME_CANDIDATE_ID,
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    SEED,
    VERSION,
)


def freeze_model_from_learned(
    learned: FirstLearnedBaseline,
    *,
    seed: int = SEED,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert learned.coef is not None
    out = outcome or {
        "candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "label": FIXED_OUTCOME_LABEL,
        "unit": FIXED_OUTCOME_UNIT,
    }
    doc = {
        "version": VERSION,
        "model_id": learned.MODEL_ID,
        "model_family": learned.MODEL_FAMILY,
        "claim_level": learned.CLAIM_LEVEL,
        "clinical_validation": "NOT_CLAIMED",
        "seed": seed,
        "l2": learned.l2,
        "coef": list(learned.coef),
        "intercept": learned.intercept,
        "residual_std": learned.residual_std,
        "interval_multiplier": learned.interval_multiplier,
        "scaler_means": list(learned.scaler.means),
        "scaler_stds": list(learned.scaler.stds),
        "scaler_fit_n_rows": learned.scaler.fit_n_rows,
        "feature_order": list(FEATURE_ORDER),
        "feature_schema_hash": learned.feature_schema_hash,
        "training_configuration_hash": learned.training_configuration_hash,
        "outcome": out,
        "frozen_at_version": VERSION,
    }
    return doc


def sha256_frozen_json(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_frozen_model(art_dir: Path, doc: dict[str, Any]) -> dict[str, Any]:
    art_dir.mkdir(parents=True, exist_ok=True)
    path = art_dir / "frozen-source-a-model.json"
    digest = sha256_frozen_json(doc)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    sha_path = art_dir / "frozen-source-a-model.json.sha256"
    sha_path.write_text(f"{digest}  frozen-source-a-model.json\n", encoding="utf-8")
    return {
        "path": str(path),
        "sha256": digest,
        "frozen_source_a_model_status": "FROZEN",
    }


def prove_hash_unchanged(art_dir: Path) -> dict[str, Any]:
    path = art_dir / "frozen-source-a-model.json"
    sha_path = art_dir / "frozen-source-a-model.json.sha256"
    if not path.is_file() or not sha_path.is_file():
        return {"ok": False, "detail": "missing frozen model"}
    doc = json.loads(path.read_text(encoding="utf-8"))
    recomputed = sha256_frozen_json(doc)
    recorded = sha_path.read_text(encoding="utf-8").split()[0]
    return {
        "ok": recomputed == recorded,
        "recorded_sha256": recorded,
        "recomputed_sha256": recomputed,
        "unchanged_after_b_evaluation": recomputed == recorded,
    }


def build_frozen_from_runtime(runtime_learned: Any, *, seed: int = SEED) -> dict[str, Any]:
    if runtime_learned is None or not isinstance(runtime_learned, FirstLearnedBaseline):
        return {
            "status": "FAIL",
            "frozen_source_a_model_status": "UNAVAILABLE",
            "reason": "learned_model_missing",
        }
    doc = freeze_model_from_learned(runtime_learned, seed=seed)
    digest = sha256_frozen_json(doc)
    return {
        "status": "FROZEN",
        "frozen_source_a_model_status": "FROZEN",
        "model": doc,
        "sha256": digest,
    }


def load_frozen_model(doc: dict[str, Any]) -> FirstLearnedBaseline:
    """Rehydrate frozen Ridge for scoring (no refit / no B tuning)."""
    m = FirstLearnedBaseline(
        seed=int(doc.get("seed") or SEED),
        l2=float(doc["l2"]),
        interval_multiplier=float(doc.get("interval_multiplier") or 1.6448536269514722),
    )
    m.coef = [float(x) for x in doc["coef"]]
    m.intercept = float(doc["intercept"])
    m.residual_std = float(doc["residual_std"])
    m.scaler.means = [float(x) for x in doc["scaler_means"]]
    m.scaler.stds = [float(x) for x in doc["scaler_stds"]]
    m.scaler.fit_n_rows = int(doc.get("scaler_fit_n_rows") or 0)
    m.scaler.fitted = True
    m.feature_schema_hash = doc.get("feature_schema_hash")
    m.training_configuration_hash = doc.get("training_configuration_hash")
    m.trained = True
    return m
