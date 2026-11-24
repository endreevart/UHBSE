"""SHA-256 identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v011.policy import NAMESPACE, SEED, VERSION
from human_simulator.natural_history_rollout_v011.policy import P1_FEATURE_ORDER


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def feature_order_sha256(order: list[str] | None = None) -> str:
    return sha_obj({"feature_order": list(order or P1_FEATURE_ORDER)})


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
