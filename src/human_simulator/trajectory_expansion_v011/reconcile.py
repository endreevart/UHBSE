"""Registry-to-rebuild reconciliation for trajectory expansion v0.1.1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.trajectory_expansion_v011.policy import (
    ACCEPTED_V01_ARTIFACT_DIR,
    ACCEPTED_V01_RUNTIME_DIR,
    EXPECTED_REGISTRY_COUNT_V01,
    PRIMARY_THRESHOLD_PROFILE,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def classify_pair_delta(
    registry_pairs: int,
    rebuilt_pairs: int,
    exclusions: dict[str, Any] | None,
) -> tuple[str, int, int]:
    """Return (classified_reason, explained_delta, unexplained)."""
    delta = int(registry_pairs) - int(rebuilt_pairs)
    excl = exclusions or {}
    explained = int(excl.get("duplicate_same_timestamp_collapsed") or 0) + int(
        excl.get("zero_horizon") or 0
    ) + int(excl.get("negative_horizon") or 0) + int(
        excl.get("missing_timestamp") or 0
    ) + int(excl.get("incompatible_unit") or 0) + int(
        excl.get("all_forward_combinations_forbidden") or 0
    )
    if delta == 0:
        return "MATCH", 0, 0
    if explained == delta:
        parts = [
            k
            for k, v in excl.items()
            if int(v or 0) > 0
            and k
            in {
                "duplicate_same_timestamp_collapsed",
                "zero_horizon",
                "negative_horizon",
                "missing_timestamp",
                "incompatible_unit",
                "all_forward_combinations_forbidden",
            }
        ]
        return "+".join(parts) if parts else "EXCLUSIONS_EXPLAINED", explained, 0
    if explained > 0 and explained != delta:
        return "PARTIAL_EXCLUSION_ACCOUNTING", explained, abs(delta - explained)
    return "UNEXPLAINED_PAIR_DELTA", explained, abs(delta)


def authoritative_threshold_result(
    *,
    n_subjects_with_repeats: int,
    n_pairs: int,
    n_test_subjects: int | None,
    criteria: dict[str, Any],
) -> dict[str, Any]:
    subj_ok = int(n_subjects_with_repeats) >= int(criteria["min_subjects_with_ge2"])
    pairs_ok = int(n_pairs) >= int(criteria["min_strict_consecutive_pairs"])
    test_ok = True
    if n_test_subjects is not None:
        test_ok = int(n_test_subjects) >= int(criteria["min_test_subjects_if_split"])
    eligible = bool(subj_ok and pairs_ok and test_ok)
    fails = []
    if not subj_ok:
        fails.append("subjects_with_repeats")
    if not pairs_ok:
        fails.append("strict_consecutive_pairs")
    if not test_ok:
        fails.append("test_subjects")
    return {
        "eligible": eligible,
        "fails": fails,
        "criteria_applied_to": "authoritative_rebuilt_dataset",
    }


def build_reconciliation(
    root: Path,
    *,
    criteria: dict[str, Any],
    rebuilt_by_grain: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare v0.1 registry counts to authoritative rebuilt datasets."""
    root = Path(root)
    reg_path = root / ACCEPTED_V01_ARTIFACT_DIR / "selected-outcome-registry.json"
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    grains = registry.get("grains") or []
    rows: list[dict[str, Any]] = []
    unexplained_total = 0
    eligible = []
    ineligible = []

    for g in grains:
        gid = g["grain_id"]
        rebuilt = rebuilt_by_grain.get(gid) or {}
        # Prefer live rebuild; fall back to v0.1 private summary if needed
        if not rebuilt:
            legacy = (
                root
                / ACCEPTED_V01_RUNTIME_DIR
                / "datasets"
                / f"{gid}-summary.json"
            )
            if legacy.is_file():
                rebuilt = json.loads(legacy.read_text(encoding="utf-8"))

        excl = ((rebuilt.get("pair_meta") or {}).get("summary") or {}).get(
            "exclusions_by_reason"
        ) or rebuilt.get("exclusions_by_reason") or {}
        reg_obs = int(g.get("n_observations") or g.get("observations") or 0)
        reg_subj = int(g.get("n_subjects") or g.get("subjects") or 0)
        reg_rep = int(
            g.get("n_subjects_with_ge2")
            or g.get("n_subjects_with_repeats")
            or g.get("subjects_with_repeats")
            or 0
        )
        reg_pairs = int(
            g.get("n_strict_consecutive_pairs")
            or g.get("n_pairs")
            or g.get("strict_consecutive_pairs")
            or 0
        )
        reb_obs = int(rebuilt.get("n_observations") or 0)
        reb_subj = int(rebuilt.get("n_subjects") or 0)
        reb_rep = int(rebuilt.get("n_subjects_with_repeats") or 0)
        reb_pairs = int(rebuilt.get("n_pairs") or 0)
        reason, explained, unexplained = classify_pair_delta(reg_pairs, reb_pairs, excl)
        unexplained_total += int(unexplained)

        split = rebuilt.get("split_counts") or {}
        n_test = split.get("test_subjects")
        if n_test is None and rebuilt.get("n_test_subjects") is not None:
            n_test = rebuilt.get("n_test_subjects")
        # provisional eligibility without test subjects uses pairs+subjects only;
        # final gate re-applied after split in orchestrator.
        thr = authoritative_threshold_result(
            n_subjects_with_repeats=reb_rep,
            n_pairs=reb_pairs,
            n_test_subjects=int(n_test) if n_test is not None else None,
            criteria=criteria,
        )
        # pre-split: only subjects+pairs decide provisional set
        provisional = authoritative_threshold_result(
            n_subjects_with_repeats=reb_rep,
            n_pairs=reb_pairs,
            n_test_subjects=None,
            criteria=criteria,
        )
        row = {
            "grain_id": gid,
            "outcome": g.get("normalized_label") or g.get("outcome") or rebuilt.get("outcome"),
            "unit": g.get("unit") or rebuilt.get("unit"),
            "registry_observations": reg_obs,
            "registry_subjects": reg_subj,
            "registry_subjects_with_repeats": reg_rep,
            "registry_pairs": reg_pairs,
            "rebuilt_observations": reb_obs,
            "rebuilt_subjects": reb_subj,
            "rebuilt_subjects_with_repeats": reb_rep,
            "rebuilt_pairs": reb_pairs,
            "difference_pairs": reg_pairs - reb_pairs,
            "difference_observations": reg_obs - reb_obs,
            "exclusions_by_reason": excl,
            "classified_reason": reason,
            "explained_pair_delta": explained,
            "unexplained": unexplained,
            "authoritative_threshold_result": provisional,
            "authoritative_threshold_with_test": thr if n_test is not None else None,
            "observation_counts_match": reg_obs == reb_obs,
        }
        rows.append(row)
        if provisional["eligible"]:
            eligible.append(row)
        else:
            ineligible.append(row)

    # Focus exemplars
    exemplars = [
        r
        for r in rows
        if any(
            x in (r.get("outcome") or "")
            for x in (
                "цитомегаловирусу",
                "ОЖСС",
                "простого герпеса",
            )
        )
    ]

    status = "PASS" if unexplained_total == 0 and len(rows) == EXPECTED_REGISTRY_COUNT_V01 else "FAIL"
    return {
        "version": VERSION,
        "REGISTRY_REBUILD_RECONCILIATION_STATUS": status,
        "profile": PRIMARY_THRESHOLD_PROFILE,
        "n_registry_grains": len(rows),
        "expected_registry_count_v01": EXPECTED_REGISTRY_COUNT_V01,
        "n_authoritative_eligible_provisional": len(eligible),
        "n_ineligible_provisional": len(ineligible),
        "AUTHORITATIVE_ELIGIBLE_GRAIN_COUNT_PROVISIONAL": len(eligible),
        "unexplained_total": unexplained_total,
        "reconciliation_hash": _hash(
            [
                {
                    "grain_id": r["grain_id"],
                    "rebuilt_pairs": r["rebuilt_pairs"],
                    "classified_reason": r["classified_reason"],
                    "unexplained": r["unexplained"],
                    "eligible": r["authoritative_threshold_result"]["eligible"],
                }
                for r in rows
            ]
        ),
        "exemplars": exemplars,
        "ineligible_provisional": [
            {
                "grain_id": r["grain_id"],
                "outcome": r["outcome"],
                "unit": r["unit"],
                "rebuilt_pairs": r["rebuilt_pairs"],
                "rebuilt_subjects_with_repeats": r["rebuilt_subjects_with_repeats"],
                "fails": r["authoritative_threshold_result"]["fails"],
                "classified_reason": r["classified_reason"],
            }
            for r in ineligible
        ],
        "rows": rows,
        "note": (
            "Inventory pair SQL counted neighbors without collapsing same-timestamp "
            "duplicates or excluding zero-horizon pairs; scientific "
            "build_consecutive_pairs applies both. Thresholds apply to rebuilt counts."
        ),
    }
