"""Portable synthetic fixtures — no patient rows. Persistence P0 + residual ECDF."""

from __future__ import annotations

from typing import Any

from human_simulator.integrated_research_runtime_v011.hashes import feature_order_sha256, sha_obj
from human_simulator.integrated_research_runtime_v011.policy import (
    CODE_VERSION,
    SYN_HORIZON,
    SYN_OUTCOMES,
    SYN_SOURCE,
)
from human_simulator.natural_history_rollout_v011.policy import P1_FEATURE_ORDER

SYN_ECDF = {
    SYN_OUTCOMES[0]: [-0.4, -0.2, -0.1, 0.0, 0.1, 0.2, 0.4],
    SYN_OUTCOMES[1]: [-0.3, -0.1, 0.0, 0.1, 0.3],
}


def synthetic_marginal_cell(outcome_key: str) -> dict[str, Any]:
    feat_hash = feature_order_sha256()
    body = {
        "provider": "P0_PERSISTENCE",
        "source_system": SYN_SOURCE,
        "outcome_key": outcome_key,
        "horizon_days": SYN_HORIZON,
        "feature_order": list(P1_FEATURE_ORDER),
        "feature_order_sha256": feat_hash,
        "unit": outcome_key.split("::")[-1],
    }
    ident = sha_obj(body)
    return {
        **body,
        "active_provider": "P0",
        "active_payload_sha256": ident,
        "scaler_sha256": sha_obj({"median": 0.0, "scale": 1.0}),
        "supported_horizons": [SYN_HORIZON],
        "synthetic_fixture": True,
    }


def synthetic_request(**kw: Any) -> dict[str, Any]:
    fo = feature_order_sha256()
    req: dict[str, Any] = {
        "source_system": SYN_SOURCE,
        "requested_horizon_days": SYN_HORIZON,
        "outcome_keys": list(SYN_OUTCOMES),
        "state_at_t0": {SYN_OUTCOMES[0]: 1.0, SYN_OUTCOMES[1]: 2.0, "history_depth": 2},
        "cutoff_t0": "synthetic-t0",
        "model_id": fo,
        "feature_order_sha256": fo,
        "n_paths": 8,
        "seed": 42,
        "replay_key": "synthetic",
    }
    req.update(kw)
    return req


def synthetic_runtime_bundle() -> dict[str, Any]:
    cells = {ok: synthetic_marginal_cell(ok) for ok in SYN_OUTCOMES}
    scales = {
        f"{SYN_SOURCE}|{ok}|au": {"source_system": SYN_SOURCE, "outcome_key": ok, "unit": "au", "median": 0.0, "scale": 1.0}
        for ok in SYN_OUTCOMES
    }
    return {
        "source_system": SYN_SOURCE,
        "horizon_days": SYN_HORIZON,
        "outcomes": list(SYN_OUTCOMES),
        "cells": cells,
        "ecdf": SYN_ECDF,
        "train_scales": scales,
        "feature_order_sha256": feature_order_sha256(),
        "code_version": CODE_VERSION,
        "validation_accepted": False,
        "family": "D0_INDEPENDENT_NORMALIZED_MARGINAL_RESIDUALS",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": 0,
        "synthetic_fixture": True,
    }
