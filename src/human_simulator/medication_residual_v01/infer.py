"""Apply frozen residual models (no refit)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.medication_residual_v01.models import predict_family, predict_r0
from human_simulator.medication_residual_v01.policy import MODELS_DIR


def load_vocab(root: Path) -> dict[str, Any]:
    doc = json.loads((root / MODELS_DIR / "frozen-vocab.json").read_text(encoding="utf-8"))
    ids = list(doc.get("ids") or [])
    doc["index"] = {m: i for i, m in enumerate(ids)}
    return doc


def load_r0(root: Path) -> dict[str, float]:
    doc = json.loads((root / MODELS_DIR / "frozen-r0-means.json").read_text(encoding="utf-8"))
    return {k: float(v) for k, v in (doc.get("means") or {}).items()}


def load_payload(root: Path, fname: str) -> dict[str, Any]:
    return json.loads((root / MODELS_DIR / fname).read_text(encoding="utf-8"))


def score_cell(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    r2_file: str,
    r1_file: str,
    family: str,
) -> dict[str, Any]:
    from human_simulator.medication_residual_v01.evaluate import cell_metrics

    vocab = load_vocab(root)
    r0 = load_r0(root)
    r1 = load_payload(root, r1_file)
    r2 = load_payload(root, r2_file)
    p0 = predict_r0(r0, rows)
    p1 = predict_family("R1", r1, rows, vocab)
    p2 = predict_family(family, r2, rows, vocab)
    metrics = cell_metrics(rows, p0, p1, p2)
    return {
        "metrics": metrics,
        "r1_identity": r1.get("model_identity_sha256"),
        "r2_identity": r2.get("model_identity_sha256"),
        "r1_file_reload": r1.get("model_identity_sha256"),
        "feature_order_r2": r2.get("feature_order"),
    }
