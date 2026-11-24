"""Freeze Source A Ridge model v0.2 with dual hash semantics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER, FirstLearnedBaseline
from human_simulator.scientific_v02.policy import (
    FIXED_OUTCOME_CANDIDATE_ID,
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    L2,
    SEED,
    VERSION,
)

IDENTITY_ALGORITHM = (
    "explicit-local-contract: json.dumps(doc, sort_keys=True, separators=(',', ':')) "
    "UTF-8 SHA-256; NOT file-byte SHA; NOT RFC 8785"
)


def model_to_doc(
    model: FirstLearnedBaseline,
    *,
    split_hash: str,
    training_pair_manifest_hash: str,
    outcome_contract_hash: str,
    code_hash: str | None = None,
) -> dict[str, Any]:
    assert model.coef is not None
    return {
        "version": VERSION,
        "model_id": "source_a_ridge_v0.2",
        "model_family": model.MODEL_FAMILY,
        "claim_level": model.CLAIM_LEVEL,
        "clinical_validation": "NOT_CLAIMED",
        "seed": SEED,
        "l2": L2,
        "coef": list(model.coef),
        "intercept": model.intercept,
        "residual_std": model.residual_std,
        "interval_multiplier": model.interval_multiplier,
        "scaler_means": list(model.scaler.means),
        "scaler_stds": list(model.scaler.stds),
        "scaler_fit_n_rows": model.scaler.fit_n_rows,
        "feature_order": list(FEATURE_ORDER),
        "feature_schema_hash": model.feature_schema_hash,
        "training_configuration_hash": model.training_configuration_hash,
        "training_split_hash": split_hash,
        "training_pair_manifest_hash": training_pair_manifest_hash,
        "outcome_contract_hash": outcome_contract_hash,
        "code_hash": code_hash,
        "outcome": {
            "candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
            "label": FIXED_OUTCOME_LABEL,
            "unit": FIXED_OUTCOME_UNIT,
            "medical_domain_interpretation": "DOMAIN_REVIEW_PENDING",
        },
        "frozen_at_version": VERSION,
    }


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity_sha256(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_frozen_v02(art: Path, doc: dict[str, Any]) -> dict[str, Any]:
    art.mkdir(parents=True, exist_ok=True)
    path = art / "frozen-source-a-model-v0.2.json"
    raw = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    fsha = file_sha256(raw)
    (art / "frozen-source-a-model-v0.2.json.sha256").write_text(
        f"{fsha}  frozen-source-a-model-v0.2.json\n", encoding="utf-8"
    )
    isha = identity_sha256(doc)
    identity = {
        "identity_algorithm": IDENTITY_ALGORITHM,
        "canonical_model_identity_sha256": isha,
        "file_sha256": fsha,
        "version": VERSION,
        "refit_after_freeze_forbidden": True,
    }
    (art / "frozen-source-a-model-v0.2.identity.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "source_a_model_freeze_status": "FROZEN",
        "file_sha256": fsha,
        "canonical_model_identity_sha256": isha,
        "scaler_fit_n_rows": doc["scaler_fit_n_rows"],
    }


def load_frozen_v02(doc: dict[str, Any]) -> FirstLearnedBaseline:
    m = FirstLearnedBaseline(seed=int(doc.get("seed") or SEED), l2=float(doc["l2"]))
    m.coef = [float(x) for x in doc["coef"]]
    m.intercept = float(doc["intercept"])
    m.residual_std = float(doc["residual_std"])
    m.interval_multiplier = float(doc.get("interval_multiplier") or m.interval_multiplier)
    m.scaler.means = [float(x) for x in doc["scaler_means"]]
    m.scaler.stds = [float(x) for x in doc["scaler_stds"]]
    m.scaler.fit_n_rows = int(doc["scaler_fit_n_rows"])
    m.scaler.fitted = True
    m.feature_schema_hash = doc.get("feature_schema_hash")
    m.training_configuration_hash = doc.get("training_configuration_hash")
    m.trained = True
    return m


def verify_sidecar(art: Path) -> dict[str, Any]:
    path = art / "frozen-source-a-model-v0.2.json"
    side = art / "frozen-source-a-model-v0.2.json.sha256"
    recorded = side.read_text(encoding="utf-8").split()[0]
    got = file_sha256(path.read_bytes())
    return {"ok": recorded == got, "file_sha256": got, "recorded": recorded}
