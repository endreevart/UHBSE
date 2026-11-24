"""Process-independent SHA-256 identities and seeds. No built-in hash()."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.joint_dependence_rollout_v02.policy import NAMESPACE, SEED, VERSION


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def domain_sha(*parts: str) -> str:
    payload = "|".join(["v02", VERSION, *[str(p) for p in parts]])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_seed(
    *,
    source_system: str = "",
    outcome_key: str = "",
    horizon_days: int = 0,
    split_role: str = "",
    target_id: str = "",
    landmark_id: str = "",
    mode: str = "direct",
    path_index: int = 0,
    extra: str = "",
) -> int:
    digest = sha_obj(
        {
            "namespace": NAMESPACE,
            "version": VERSION,
            "global_seed": SEED,
            "source_system": source_system,
            "outcome_key": outcome_key,
            "horizon_days": int(horizon_days),
            "split_role": split_role,
            "target_id": target_id,
            "landmark_id": landmark_id,
            "mode": mode,
            "path_index": int(path_index),
            "extra": extra,
        }
    )
    return int(digest[:16], 16) % (2**31 - 1)
