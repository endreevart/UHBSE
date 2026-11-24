"""Freeze M1 and M2C with file + identity hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v011.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    PRIMARY_HORIZON_DAYS,
    TIMESTAMP_HYPOTHESIS,
    VERSION,
)


def _sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_obj(obj: Any) -> str:
    return _sha_b(json.dumps(obj, sort_keys=True, default=str).encode())


def freeze_m1_m2c(art: Path, cohort_result: dict[str, Any]) -> dict[str, Any]:
    if cohort_result.get("status") != "EVALUATED":
        return {"MODEL_FREEZE_STATUS": "NOT_FROZEN", "reason": cohort_result.get("status")}
    ser = cohort_result.get("serialized") or {}
    if not ser.get("m1") or not ser.get("m2c"):
        return {"MODEL_FREEZE_STATUS": "NOT_FROZEN", "reason": "missing_serialized"}

    safe = hashlib.sha256(
        f"{cohort_result['outcome']}|{cohort_result['unit']}".encode()
    ).hexdigest()[:12]
    model_dir = art / "frozen_models" / f"{TIMESTAMP_HYPOTHESIS}_h{PRIMARY_HORIZON_DAYS}_{safe}"
    model_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": VERSION,
        "clinical_use": CLINICAL_USE_PROHIBITED,
        "causal_interpretation": CAUSAL_INTERPRETATION_PROHIBITED,
        "authoritative_models": ["m1", "m2c"],
        "legacy_ordinal_m2_included_for_diagnostics_only": True,
        "timestamp_hypothesis": TIMESTAMP_HYPOTHESIS,
        "horizon_days": PRIMARY_HORIZON_DAYS,
        "outcome": cohort_result["outcome"],
        "unit": cohort_result["unit"],
        "m1_feature_order": cohort_result["m1_feature_order"],
        "m2c_feature_order": cohort_result["m2c_feature_order"],
        "m1": ser["m1"],
        "m2c": ser["m2c"],
        "m2_legacy_ordinal": ser.get("m2_legacy_ordinal"),
        "metrics_test": {
            "m0": cohort_result["m0"],
            "m1": cohort_result["m1"],
            "m2c": cohort_result["m2c"],
            "m2c_vs_m1": cohort_result["m2c_vs_m1"],
        },
    }
    path = model_dir / "model.json"
    raw = json.dumps(payload, indent=2, sort_keys=True, default=str).encode()
    path.write_bytes(raw)
    file_sha = _sha_b(raw)
    identity = {
        "version": VERSION,
        "outcome": cohort_result["outcome"],
        "unit": cohort_result["unit"],
        "m1_feature_order": cohort_result["m1_feature_order"],
        "m2c_feature_order": cohort_result["m2c_feature_order"],
        "m1_coef_hash": _sha_obj(ser["m1"]["coef"]),
        "m2c_coef_hash": _sha_obj(ser["m2c"]["coef"]),
        "m2c_hash_dim": ser["m2c"].get("hash_dim"),
        "file_sha256": file_sha,
    }
    identity_sha = _sha_obj(identity)
    (model_dir / "model-identity.json").write_text(
        json.dumps({**identity, "model_identity_sha256": identity_sha}, indent=2) + "\n"
    )
    reload_sha = _sha_b(path.read_bytes())
    return {
        "MODEL_FREEZE_STATUS": "FROZEN",
        "relative_path": str(path.relative_to(art)),
        "file_sha256": file_sha,
        "reload_file_sha256": reload_sha,
        "reload_matches": reload_sha == file_sha,
        "model_identity_sha256": identity_sha,
        "outcome": cohort_result["outcome"],
        "unit": cohort_result["unit"],
    }
