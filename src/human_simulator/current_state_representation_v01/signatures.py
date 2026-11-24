"""Research-only state signature candidates (no clinical labels)."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.current_state_representation_v01.encoder import predict_encoder
from human_simulator.current_state_representation_v01.policy import (
    RUNTIME_DIR,
    SEED,
    TENSOR_DIR,
    VERSION,
)


def build_signature_candidates(root: Path, model: dict[str, Any]) -> dict[str, Any]:
    """k-means-like latent clusters — STATE_SIGNATURE_CANDIDATE only."""
    root = Path(root).resolve()
    rng = random.Random(SEED)
    train = [
        r
        for r in pq.read_table(root / TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
        if r.get("split_role") == "train"
    ]
    rng.shuffle(train)
    sample = train[:400]
    latents = [predict_encoder(model, r)["latent"] for r in sample]
    k = 5
    # init
    centers = [latents[rng.randrange(len(latents))][:] for _ in range(k)]
    for _ in range(8):
        assign = []
        for h in latents:
            dists = [
                sum((h[i] - c[i]) ** 2 for i in range(len(h))) for c in centers
            ]
            assign.append(dists.index(min(dists)))
        for j in range(k):
            members = [latents[i] for i, a in enumerate(assign) if a == j]
            if not members:
                continue
            centers[j] = [
                sum(m[d] for m in members) / len(members) for d in range(len(members[0]))
            ]
    sizes = [sum(1 for a in assign if a == j) for j in range(k)]
    doc = {
        "version": VERSION,
        "BIO_SIGNATURE_STATUS": "CANDIDATE_ONLY",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED_NO_ACCEPTED_LABEL_ONTOLOGY",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
        "candidates": [
            {
                "label": "STATE_SIGNATURE_CANDIDATE",
                "cluster_id": j,
                "n_train_states_approx": sizes[j],
                "centroid_l2": math.sqrt(sum(x * x for x in centers[j])),
                "not_a_diagnosis": True,
                "not_a_clinical_state_label": True,
                "not_a_causal_phenotype": True,
            }
            for j in range(k)
        ],
        "trajectory_regime_note": "TRAJECTORY_REGIME_CANDIDATE reserved; classifier NOT_STARTED",
        "ok": True,
    }
    (root / RUNTIME_DIR / "state-signature-candidates.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
