"""Train Source A Ridge v0.2 with fixed L2=0.1 (no L2 retuning; no B/test tuning)."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from human_simulator.scientific.models import (
    FEATURE_ORDER,
    FirstLearnedBaseline,
    feature_schema_hash,
)
from human_simulator.scientific_v02.policy import (
    DOMAIN_REVIEW_PENDING,
    FIXED_OUTCOME_CANDIDATE_ID,
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    L2,
    SEED,
    SOURCE_A_SYSTEM_ID,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def train_ridge_v02(
    train_pairs: list[dict[str, Any]],
    val_pairs: list[dict[str, Any]],
    *,
    split_hash: str,
    train_pair_manifest_hash: str,
    pair_construction_hash: str | None,
    dataset_schema_hash: str | None,
    seed: int = SEED,
    l2: float = L2,
) -> dict[str, Any]:
    """Fit Ridge with fixed L2 on A-only train; calibrate residual_std on validation only."""
    assert abs(l2 - 0.1) < 1e-12, "L2 must remain 0.1"
    model = FirstLearnedBaseline(seed=seed, l2=l2)
    fit_info = model.fit(train_pairs)
    # Recalibrate residual_std on validation (not test, not B)
    if val_pairs:
        val_preds = [model.predict_pair(p) for p in val_pairs]
        resid = [p.y_true - p.y_pred for p in val_preds]
        model.residual_std = math.sqrt(sum(r * r for r in resid) / len(resid)) or model.residual_std

    assert model.scaler.fit_n_rows == len(train_pairs)

    outcome = {
        "candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "label": FIXED_OUTCOME_LABEL,
        "unit": FIXED_OUTCOME_UNIT,
        "medical_domain_interpretation": DOMAIN_REVIEW_PENDING,
    }
    outcome_contract_hash = _hash(outcome)
    feature_contract = {
        "feature_order": list(FEATURE_ORDER),
        "feature_schema_hash": feature_schema_hash(),
        "n_features": len(FEATURE_ORDER),
        "order_is_contract": True,
    }
    training_pair_manifest = {
        "count": len(train_pairs),
        "aggregate_hash": train_pair_manifest_hash,
        "split_hash": split_hash,
        "source_system": SOURCE_A_SYSTEM_ID,
        "feature_schema_hash": feature_schema_hash(),
        "outcome_contract_hash": outcome_contract_hash,
        "pair_construction_hash": pair_construction_hash,
        "dataset_schema_hash": dataset_schema_hash,
        "contains_pair_identifiers": False,
    }
    training_report = {
        "version": VERSION,
        "source_a_model_training_status": "PASS",
        "model_family": model.MODEL_FAMILY,
        "l2": l2,
        "l2_retuned": False,
        "seed": seed,
        "n_train_pairs": len(train_pairs),
        "n_val_pairs": len(val_pairs),
        "scaler_fit_n_rows": model.scaler.fit_n_rows,
        "scaler_fit_equals_train_count": model.scaler.fit_n_rows == len(train_pairs),
        "test_used_for_fit_or_tuning": False,
        "source_b_used_for_fit_or_tuning": False,
        "residual_std_calibrated_on": "validation" if val_pairs else "train",
        "residual_std": model.residual_std,
        "interval_multiplier": model.interval_multiplier,
        "feature_schema_hash": model.feature_schema_hash,
        "training_configuration_hash": model.training_configuration_hash,
        "fit_info": fit_info,
        "outcome": outcome,
        "claim_level": model.CLAIM_LEVEL,
        "clinical_validation": "NOT_CLAIMED",
    }
    return {
        "model": model,
        "training_report": training_report,
        "feature_contract": feature_contract,
        "training_pair_manifest": training_pair_manifest,
        "outcome_contract_hash": outcome_contract_hash,
    }
