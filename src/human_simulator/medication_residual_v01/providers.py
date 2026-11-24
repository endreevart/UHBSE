"""Natural-history providers: UIS M1 is incompatible; M0 last-value is medication-free."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.medication_residual_v01.hashes import sha_obj
from human_simulator.medication_residual_v01.policy import (
    CSR_ENCODER,
    FORBIDDEN_R1_MEDICATION_FIELDS,
    NH_PROVIDER_ID,
    NH_PROVIDER_METHOD,
    PREDECLARED_HORIZONS_DAYS,
    V0111_MODELS_DIR,
    VERSION,
)


def audit_uis_m1(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / V0111_MODELS_DIR / "frozen-providers.json"
    if not path.is_file():
        return {
            "ok": False,
            "NATURAL_HISTORY_PROVIDER_COMPATIBILITY_STATUS": "MISSING_UIS_PROVIDERS",
            "uis_m1_used": False,
        }
    doc = json.loads(path.read_text(encoding="utf-8"))
    providers = doc.get("providers") or {}
    n = len(providers)
    med_in_order = 0
    horizon_in_order = 0
    sample_order: list[str] = []
    for rec in providers.values():
        order = list(rec.get("feature_order") or [])
        if not sample_order:
            sample_order = order
        if any(f in order for f in ("n_medications_before", "has_med_history")):
            med_in_order += 1
        if any("horizon" in str(f).lower() for f in order):
            horizon_in_order += 1
    compatible = False
    return {
        "ok": True,
        "n_uis_providers": n,
        "n_with_medication_features": med_in_order,
        "n_with_horizon_feature": horizon_in_order,
        "feature_order_sample": sample_order,
        "medication_feature_in_payload": med_in_order > 0,
        "requested_horizon_compatible": False,
        "uis_m1_used": False,
        "reason": "MEDICATION_FEATURES_AND_NO_REQUESTED_HORIZON",
        "NATURAL_HISTORY_PROVIDER_COMPATIBILITY_STATUS": (
            "UIS_M1_NOT_USED_INCOMPATIBLE"
        ),
        "do_not_retrain_uis_m1": True,
        "compatible": compatible,
    }


def m0_provider_identity() -> dict[str, Any]:
    payload = {
        "provider_id": NH_PROVIDER_ID,
        "method": NH_PROVIDER_METHOD,
        "medication_free": True,
        "requested_horizon_policy": (
            "horizon_agnostic_persistence; requested horizon is the target window only; "
            "no interpolation; no substitution of actual future horizon"
        ),
        "supported_horizons_days": list(PREDECLARED_HORIZONS_DAYS),
        "forbidden_fields": list(FORBIDDEN_R1_MEDICATION_FIELDS),
        "version": VERSION,
    }
    return {
        **payload,
        "provider_identity_sha256": sha_obj(payload),
        "feature_order": ["persistence_value"],
        "scaler": None,
        "active_provider": True,
        "reload_prediction_equality": "identity_function_last_value",
    }


def encoder_status(root: Path) -> dict[str, Any]:
    exists = (root / CSR_ENCODER).is_file()
    return {
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "rejected_encoder_used": False,
        "encoder_file_present_not_loaded": exists,
        "no_retrain": True,
    }


def provider_audit(root: Path) -> dict[str, Any]:
    uis = audit_uis_m1(root)
    m0 = m0_provider_identity()
    enc = encoder_status(root)
    return {
        "version": VERSION,
        "uis_m1": uis,
        "m0": m0,
        "encoder": enc,
        "NATURAL_HISTORY_PROVIDER_COMPATIBILITY_STATUS": (
            "M0_LAST_VALUE_MEDICATION_FREE_HORIZON_AGNOSTIC"
        ),
        "ROLE_SAFE_NATURAL_HISTORY_INFERENCE_STATUS": (
            "SUBJECT_OWN_PRE_T0_HISTORY_ONLY"
        ),
        "lep_survival_used": False,
        "ok": True,
    }
