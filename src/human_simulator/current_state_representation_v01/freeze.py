"""Freeze / reload / mutation identity proofs."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.current_state_representation_v01.encoder import (
    encoder_canonical_identity,
    predict_encoder,
    save_encoder,
)
from human_simulator.current_state_representation_v01.policy import (
    MODELS_DIR,
    RUNTIME_DIR,
    TENSOR_DIR,
    V0111_STATES_DIR,
    VERSION,
)


def freeze_and_prove(root: Path, model: dict[str, Any], vocab: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    states = pq.read_table(
        root / V0111_STATES_DIR / "individual_state.parquet",
        columns=["source_scoped_subject_id", "split_role"],
    ).to_pylist()
    train_subj = sorted(
        {r["source_scoped_subject_id"] for r in states if r.get("split_role") == "train"}
    )
    train_pop_hash = hashlib.sha256(json.dumps(train_subj).encode()).hexdigest()
    split_path = (
        root
        / "artifacts/stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1"
        / "overlap-guarded-split.json"
    )
    split_hash = hashlib.sha256(split_path.read_bytes()).hexdigest() if split_path.is_file() else ""
    target_path = root / V0111_STATES_DIR / "target-reuse-audit.json"
    target_hash = (
        hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.is_file() else ""
    )
    meta = {
        "train_population_hash": train_pop_hash,
        "split_hash": split_hash,
        "target_construction_hash": target_hash,
        "vocabulary_hash": vocab["vocabulary_hash"],
        "vocabulary_order": vocab["vocabulary_order"],
        "feature_order_context": model["context_keys"],
        "outcome_channels": model["outcome_channels"],
        "mask_schema": model["mask_schema"],
        "seed": model["seed"],
        "architecture": model["architecture"],
    }
    saved = save_encoder(root, model, meta)
    ident = saved["identity"]

    # Reload equality
    loaded = json.loads((root / MODELS_DIR / "frozen-encoder.json").read_text(encoding="utf-8"))
    reload_eq = encoder_canonical_identity(loaded, meta) == ident

    # Coefficient mutation breaks identity
    mut = copy.deepcopy(loaded)
    mut["W_fore"][0][0] += 1e-3
    coef_breaks = encoder_canonical_identity(mut, meta) != ident

    # Vocabulary order mutation
    mut2 = copy.deepcopy(loaded)
    if len(mut2["outcome_keys"]) >= 2:
        mut2["outcome_keys"] = list(reversed(mut2["outcome_keys"]))
    vocab_breaks = encoder_canonical_identity(mut2, meta) != ident

    # Mask schema mutation
    mut3 = copy.deepcopy(loaded)
    mut3["mask_schema"] = "MUTATED"
    mask_breaks = encoder_canonical_identity(mut3, meta) != ident

    # File SHA
    file_sha = hashlib.sha256(
        (root / MODELS_DIR / "frozen-encoder.json").read_bytes()
    ).hexdigest()

    # Deterministic repeat on one tensor
    tensors = pq.read_table(root / TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
    row = next(r for r in tensors if r.get("split_role") == "validation")
    p1 = predict_encoder(loaded, row)
    p2 = predict_encoder(loaded, row)
    det = p1["latent"] == p2["latent"] and p1["forecast"] == p2["forecast"]

    # No pad/truncate: outcome count matches vocab
    no_pad = len(loaded["outcome_keys"]) == len(vocab["vocabulary_order"])

    doc = {
        "version": VERSION,
        "CURRENT_STATE_REPRESENTATION_STATUS": "FROZEN" if reload_eq and coef_breaks else "FAIL",
        "model_identity_sha256": ident,
        "file_sha256": file_sha,
        "reload_equality": reload_eq,
        "coefficient_mutation_breaks_identity": coef_breaks,
        "vocabulary_order_mutation_breaks_identity": vocab_breaks,
        "mask_schema_mutation_breaks_identity": mask_breaks,
        "deterministic_repeat": det,
        "no_pad_truncate": no_pad,
        "freeze_meta": meta,
        "ok": reload_eq and coef_breaks and vocab_breaks and mask_breaks and det and no_pad,
    }
    (root / RUNTIME_DIR / "encoder-freeze-proof.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
