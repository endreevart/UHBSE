"""SHA-256 identities. Frozen NHR payload identity uses the NHR canonical encoder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v016.policy import NAMESPACE, P0_FEATURE_ORDER, SEED, VERSION
from human_simulator.natural_history_rollout_v011.hashes import sha_obj as nhr_sha_obj
from human_simulator.natural_history_rollout_v011.policy import P1_FEATURE_ORDER


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def nhr_identity_sha(obj: Any) -> str:
    return nhr_sha_obj(obj)


def feature_order_sha256(order: list[str] | tuple[str, ...] | None = None) -> str:
    return nhr_sha_obj(list(order if order is not None else P1_FEATURE_ORDER))


def p0_feature_order_sha256() -> str:
    return nhr_sha_obj(list(P0_FEATURE_ORDER))


def scaler_sha256(payload: dict[str, Any] | None, *, provider: str) -> str:
    if not payload:
        return sha_obj({"scaler": None, "active_provider": provider})
    return sha_obj(
        {
            "scaler_mean": payload.get("scaler_mean"),
            "scaler_scale": payload.get("scaler_scale"),
            "active_provider": provider,
        }
    )


def derive_seed(
    *,
    source_system: str = "",
    horizon_days: int = 0,
    replay_key: str = "",
    mode: str = "d0",
    path_index: int = 0,
    extra: str = "",
) -> int:
    digest = sha_obj(
        {
            "namespace": NAMESPACE,
            "version": VERSION,
            "global_seed": SEED,
            "source_system": source_system,
            "horizon_days": int(horizon_days),
            "replay_key": replay_key,
            "mode": mode,
            "path_index": int(path_index),
            "extra": extra,
        }
    )
    return int(digest[:16], 16) % (2**31 - 1)
