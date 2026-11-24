"""Effective overlap groups: known upstream preserved; null → opaque singleton."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.joint_dependence_rollout_v02.hashes import domain_sha
from human_simulator.joint_dependence_rollout_v02.policy import V0111_OVERLAP_DIR, VERSION


def singleton_group(source_system: str, subject_id: str) -> str:
    digest = domain_sha("effective-overlap-singleton", source_system, subject_id)
    return f"eg:{digest}"


def effective_from_upstream(source_system: str, subject_id: str, upstream: Any) -> tuple[str, str]:
    raw = "" if upstream is None else str(upstream).strip()
    if raw:
        return raw, "upstream_preserved"
    return singleton_group(source_system, str(subject_id)), "null_singleton"


def load_split_effective(root: Path) -> dict[str, dict[str, str]]:
    table = pq.read_table(root / V0111_OVERLAP_DIR / "subject-split.parquet")
    out: dict[str, dict[str, str]] = {}
    for sid, ss, role, og in zip(
        table["source_scoped_subject_id"].to_pylist(),
        table["source_system"].to_pylist(),
        table["split_role"].to_pylist(),
        table["overlap_group_id"].to_pylist(),
        strict=True,
    ):
        if not sid:
            continue
        eg, kind = effective_from_upstream(str(ss or ""), str(sid), og)
        out[str(sid)] = {
            "source_system": str(ss or ""),
            "split_role": str(role or ""),
            "upstream_overlap_group_id": "" if og is None else str(og).strip(),
            "effective_overlap_group_id": eg,
            "group_kind": kind,
        }
    return out


def audit_overlap_groups(root: Path) -> dict[str, Any]:
    split = load_split_effective(root)
    n = len(split)
    known = sum(1 for r in split.values() if r["group_kind"] == "upstream_preserved")
    nulls = n - known
    known_ids = {r["upstream_overlap_group_id"] for r in split.values() if r["group_kind"] == "upstream_preserved"}
    sizes: dict[str, int] = defaultdict(int)
    roles_by_g: dict[str, set[str]] = defaultdict(set)
    for r in split.values():
        sizes[r["effective_overlap_group_id"]] += 1
        roles_by_g[r["effective_overlap_group_id"]].add(r["split_role"])
    size_list = sorted(sizes.values())
    cross_role = sum(1 for roles in roles_by_g.values() if len(roles) > 1)
    return {
        "version": VERSION,
        "n_subjects": n,
        "subjects_with_known_upstream_group": known,
        "subjects_with_null_upstream_group": nulls,
        "distinct_non_null_upstream_groups": len(known_ids),
        "blank_null_pseudo_group_v011_would_collapse": nulls,
        "effective_groups": len(sizes),
        "singleton_fallbacks": nulls,
        "group_size_min": size_list[0] if size_list else 0,
        "group_size_median": size_list[len(size_list) // 2] if size_list else 0,
        "group_size_max": size_list[-1] if size_list else 0,
        "effective_groups_crossing_roles": cross_role,
        "EFFECTIVE_OVERLAP_GROUP_STATUS": "UPSTREAM_OR_OPAQUE_SINGLETON",
        "NULL_OVERLAP_SINGLETON_FALLBACK_STATUS": "OPAQUE_SHA256_SINGLETON",
        "EFFECTIVE_GROUP_SPLIT_ISOLATION_STATUS": "PASS" if cross_role == 0 else "FAIL",
        "not_identity_merge": True,
        "ok": cross_role == 0 and n > 0,
    }
