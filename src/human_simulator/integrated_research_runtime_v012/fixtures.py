"""Portable synthetic fixtures. Per-outcome identities. No patient rows."""

from __future__ import annotations

from typing import Any

from human_simulator.integrated_research_runtime_v012.hashes import (
    nhr_identity_sha,
    p0_feature_order_sha256,
    scaler_sha256,
    sha_obj,
)
from human_simulator.integrated_research_runtime_v012.policy import (
    CODE_VERSION,
    NS_SYN,
    P0_FEATURE_ORDER,
    SYN_HORIZON,
    SYN_OUTCOMES,
    SYN_SOURCE,
    VERSION,
    none_scaler_identity,
)

SYN_ECDF = {
    SYN_OUTCOMES[0]: [-0.4, -0.2, -0.1, 0.0, 0.1, 0.2, 0.4],
    SYN_OUTCOMES[1]: [-0.3, -0.1, 0.0, 0.1, 0.3],
}


def _residual_sha(xs: list[float]) -> str:
    return sha_obj(
        {
            "sorted": [round(x, 6) for x in sorted(xs)],
            "n_blocks": 1,
            "contract": "INDEPENDENT_STEP_INNOVATIONS_NO_SERIAL_RESIDUAL_MODEL",
        }
    )


def synthetic_marginal_cell(outcome_key: str) -> dict[str, Any]:
    fo = list(P0_FEATURE_ORDER)
    fo_hash = p0_feature_order_sha256()
    scaler = none_scaler_identity("P0")
    sc_hash = scaler_sha256(None, provider="P0")
    ecdf = list(SYN_ECDF[outcome_key])
    resid_sha = _residual_sha(ecdf)
    identity_body = {
        "version": VERSION,
        "active_provider": "P0",
        "family": "P0_persistence",
        "source_system": SYN_SOURCE,
        "namespace": NS_SYN,
        "outcome_key": outcome_key,
        "horizon_days": SYN_HORIZON,
        "feature_order": fo,
        "unit": outcome_key.split("::")[-1],
        "residual_distribution_sha256": resid_sha,
        "residual_sampling_contract": "INDEPENDENT_STEP_INNOVATIONS_NO_SERIAL_RESIDUAL_MODEL",
        "scaler_sha256": sc_hash,
    }
    ident = nhr_identity_sha(identity_body)
    return {
        **identity_body,
        "active_identity_body": identity_body,
        "active_payload_sha256": ident,
        "feature_order_sha256": fo_hash,
        "scaler_sha256": sc_hash,
        "supported_horizons": [SYN_HORIZON],
        "synthetic_fixture": True,
        "evidence_tier": "SYNTHETIC_FIXTURE",
        "inference_eligible": True,
        "ecdf": ecdf,
        "residual_blocks": {"synthetic": ecdf},
        "scale_contract": "NATIVE_UNIT_NO_TRANSFORM",
    }


def synthetic_runtime_bundle() -> dict[str, Any]:
    cells = {ok: synthetic_marginal_cell(ok) for ok in SYN_OUTCOMES}
    return {
        "namespace": NS_SYN,
        "source_system": SYN_SOURCE,
        "horizon_days": SYN_HORIZON,
        "outcomes": list(SYN_OUTCOMES),
        "cells": cells,
        "feature_order_sha256": p0_feature_order_sha256(),
        "code_version": CODE_VERSION,
        "validation_accepted": False,
        "family": "D0_INDEPENDENT_NATIVE_MARGINAL_RESIDUALS",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": 0,
        "synthetic_fixture": True,
        "scale_contract": "NATIVE_UNIT_NO_TRANSFORM",
    }


def synthetic_request(**kw: Any) -> dict[str, Any]:
    bundle = synthetic_runtime_bundle()
    cells = bundle["cells"]
    req: dict[str, Any] = {
        "namespace": NS_SYN,
        "source_system": SYN_SOURCE,
        "requested_horizon_days": SYN_HORIZON,
        "outcome_keys": list(SYN_OUTCOMES),
        "state_at_t0": {SYN_OUTCOMES[0]: 1.0, SYN_OUTCOMES[1]: 2.0},
        "history": {SYN_OUTCOMES[0]: [1.0], SYN_OUTCOMES[1]: [2.0]},
        "history_days": {SYN_OUTCOMES[0]: [], SYN_OUTCOMES[1]: []},
        "history_is_pre_t0_summary": True,
        "cutoff_t0": "2000-01-01T00:00:00Z",
        "cell_identities": {
            ok: {
                "active_payload_sha256": cells[ok]["active_payload_sha256"],
                "feature_order_sha256": cells[ok]["feature_order_sha256"],
                "scaler_sha256": cells[ok]["scaler_sha256"],
                "residual_distribution_sha256": cells[ok]["residual_distribution_sha256"],
                "unit": cells[ok]["unit"],
            }
            for ok in SYN_OUTCOMES
        },
        "n_paths": 8,
        "seed": 42,
        "replay_key": "synthetic",
    }
    req.update(kw)
    return req


def bundle_public_catalog(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for ok, c in (bundle.get("cells") or {}).items():
        out.append(
            {
                "outcome_key": ok,
                "source_system": c.get("source_system"),
                "namespace": bundle.get("namespace"),
                "horizon_days": c.get("horizon_days"),
                "active_provider": c.get("active_provider"),
                "active_payload_sha256": c.get("active_payload_sha256"),
                "feature_order_sha256": c.get("feature_order_sha256"),
                "scaler_sha256": c.get("scaler_sha256"),
                "residual_distribution_sha256": c.get("residual_distribution_sha256"),
                "unit": c.get("unit"),
                "evidence_tier": c.get("evidence_tier"),
                "synthetic_fixture": bool(c.get("synthetic_fixture")),
            }
        )
    return out
