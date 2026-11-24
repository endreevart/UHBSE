"""Freeze serialized medication-association models with file + identity hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    VERSION,
)


def _sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_obj(obj: Any) -> str:
    return _sha_b(json.dumps(obj, sort_keys=True, default=str).encode())


def freeze_cohort_models(
    art: Path,
    cohort_result: dict[str, Any],
    *,
    timestamp_hypothesis: str,
    horizon_days: int,
) -> dict[str, Any]:
    if cohort_result.get("status") != "EVALUATED":
        return {
            "MODEL_FREEZE_STATUS": "NOT_FROZEN",
            "reason": cohort_result.get("status"),
        }
    ser = cohort_result.get("serialized") or {}
    if not ser.get("m1") or not ser.get("m2"):
        return {"MODEL_FREEZE_STATUS": "NOT_FROZEN", "reason": "missing_serialized"}

    safe_out = hashlib.sha256(
        f"{cohort_result['outcome']}|{cohort_result['unit']}".encode()
    ).hexdigest()[:12]
    model_dir = art / "frozen_models" / f"{timestamp_hypothesis}_h{horizon_days}_{safe_out}"
    model_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": VERSION,
        "clinical_use": CLINICAL_USE_PROHIBITED,
        "causal_interpretation": CAUSAL_INTERPRETATION_PROHIBITED,
        "not_treatment_response": True,
        "timestamp_hypothesis": timestamp_hypothesis,
        "horizon_days": horizon_days,
        "outcome": cohort_result["outcome"],
        "unit": cohort_result["unit"],
        "m1_feature_order": cohort_result["m1_feature_order"],
        "m2_feature_order": cohort_result["m2_feature_order"],
        "m1": ser["m1"],
        "m2": ser["m2"],
        "metrics_test": {
            "m0": cohort_result["m0"],
            "m1": cohort_result["m1"],
            "m2": cohort_result["m2"],
            "m2_vs_m1": cohort_result["m2_vs_m1"],
        },
    }
    path = model_dir / "model.json"
    raw = json.dumps(payload, indent=2, sort_keys=True, default=str).encode()
    path.write_bytes(raw)
    file_sha = _sha_b(raw)
    identity = {
        "version": VERSION,
        "timestamp_hypothesis": timestamp_hypothesis,
        "horizon_days": horizon_days,
        "outcome": cohort_result["outcome"],
        "unit": cohort_result["unit"],
        "m1_feature_order": cohort_result["m1_feature_order"],
        "m2_feature_order": cohort_result["m2_feature_order"],
        "m1_coef_hash": _sha_obj(ser["m1"]["coef"]),
        "m2_coef_hash": _sha_obj(ser["m2"]["coef"]),
        "file_sha256": file_sha,
    }
    identity_sha = _sha_obj(identity)
    (model_dir / "model-identity.json").write_text(
        json.dumps({**identity, "model_identity_sha256": identity_sha}, indent=2) + "\n"
    )
    # reload verify
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    reload_sha = _sha_b(json.dumps(reloaded, indent=2, sort_keys=True, default=str).encode())
    # Note: indent re-serialize may differ; verify content hash of stored file bytes
    reload_file_sha = _sha_b(path.read_bytes())
    return {
        "MODEL_FREEZE_STATUS": "FROZEN",
        "path": str(path.relative_to(art.parent.parent) if False else path),
        "relative_path": str(path.relative_to(art)),
        "file_sha256": file_sha,
        "reload_file_sha256": reload_file_sha,
        "reload_matches": reload_file_sha == file_sha,
        "model_identity_sha256": identity_sha,
        "outcome": cohort_result["outcome"],
        "unit": cohort_result["unit"],
        "timestamp_hypothesis": timestamp_hypothesis,
        "horizon_days": horizon_days,
    }
