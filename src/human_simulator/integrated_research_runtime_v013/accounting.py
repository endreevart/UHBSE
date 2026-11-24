"""Joint panel row accounting and a sequential v0.1↔v0.1.1 strict-panel count bridge."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.integrated_research_runtime_v013.policy import (
    RUNTIME_DIR,
    V01_ARTIFACT,
    V011_ARTIFACT,
    V01_ORIGINS,
    V02_MODELS,
    VERSION,
)

SYNTHETIC_UNIVERSE = {
    "raw_origin_rows": 20,
    "outside_vocab_rows": 4,
    "eligible_origin_rows": 16,
    "duplicate_target_rows": 2,
    "deterministic_selected_rows": 14,
    "strict_panel_membership_rows": 6,
    "asynchronous_vector_membership_rows": 4,
    "single_outcome_group_membership_rows": 2,
    "excluded_invalid_rows": 2,
    "strict_panels": 3,
    "asynchronous_groups": 2,
    "single_outcome_groups": 2,
}

CLASS_STRICT = "strict_panel_membership"
CLASS_ASYNC = "asynchronous_vector_membership"
CLASS_SINGLE = "single_outcome_group_membership"
CLASS_INVALID = "excluded_invalid"
PUBLISHED_V01_STRICT = 43085
PUBLISHED_V011_STRICT = 39465
PUBLISHED_DELTA = PUBLISHED_V011_STRICT - PUBLISHED_V01_STRICT
ORIGIN_COLUMNS = (
    "source_system",
    "outcome_key",
    "requested_horizon_days",
    "source_scoped_subject_id",
    "t0_iso",
    "target_id",
    "split_role",
    "actual_recorded_label_offset_days",
)


def reconcile(counts: dict[str, int]) -> dict[str, Any]:
    raw = int(counts["raw_origin_rows"])
    outside = int(counts["outside_vocab_rows"])
    eligible = int(counts["eligible_origin_rows"])
    dup = int(counts["duplicate_target_rows"])
    selected = int(counts["deterministic_selected_rows"])
    strict_rows = int(counts["strict_panel_membership_rows"])
    async_rows = int(counts["asynchronous_vector_membership_rows"])
    single_rows = int(counts["single_outcome_group_membership_rows"])
    invalid = int(counts["excluded_invalid_rows"])
    residual_raw = raw - (outside + eligible)
    residual_eligible = eligible - (dup + selected)
    residual_selected = selected - (strict_rows + async_rows + single_rows + invalid)
    unexplained = abs(residual_raw) + abs(residual_eligible) + abs(residual_selected)
    return {
        "equations": {
            "raw_origin_rows = outside_vocab_rows + eligible_origin_rows": {
                "lhs": raw,
                "rhs": outside + eligible,
                "residual": residual_raw,
            },
            "eligible_origin_rows = duplicate_target_rows + deterministic_selected_rows": {
                "lhs": eligible,
                "rhs": dup + selected,
                "residual": residual_eligible,
            },
            "deterministic_selected_rows = strict_panel_membership_rows + asynchronous_vector_membership_rows + single_outcome_group_membership_rows + excluded_invalid_rows": {
                "lhs": selected,
                "rhs": strict_rows + async_rows + single_rows + invalid,
                "residual": residual_selected,
            },
        },
        "panel_and_group_counts_not_in_row_formulas": {
            "strict_panels": int(counts["strict_panels"]),
            "asynchronous_groups": int(counts["asynchronous_groups"]),
            "single_outcome_groups": int(counts["single_outcome_groups"]),
        },
        "unexplained": unexplained,
        "unexplained_assigned_as_literal": False,
        "ok": unexplained == 0,
    }


def synthetic_accounting() -> dict[str, Any]:
    rec = reconcile(SYNTHETIC_UNIVERSE)
    return {
        "version": VERSION,
        "universe": "SYNTHETIC_PORTABLE_FIXTURE",
        "JOINT_PANEL_ROW_ACCOUNTING_STATUS": "RECONCILED" if rec["ok"] else "NOT_RECONCILED",
        "JOINT_PANEL_ACCOUNTING_STATUS": "RECONCILED" if rec["ok"] else "NOT_RECONCILED",
        "row_counts": dict(SYNTHETIC_UNIVERSE),
        **rec,
    }


def _collapse_ts(t0_iso: str, actual: float) -> str:
    return f"{t0_iso}|{round(float(actual), 6)}"


def panel_key_sha256(source_system: str, subject: str, t0_iso: str, horizon: int) -> str:
    payload = f"{source_system}\0{subject}\0{t0_iso}\0{int(horizon)}".encode()
    return hashlib.sha256(payload).hexdigest()


def set_digest(keys: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(keys)).encode()).hexdigest()


def recount_origins(path: Path, vocab: set[tuple[str, str, int]]) -> dict[str, Any]:
    table = pq.read_table(path, columns=list(ORIGIN_COLUMNS))
    cols = table.to_pydict()
    n = len(next(iter(cols.values()))) if cols else 0
    outside = 0
    eligible_idx: list[int] = []
    for i in range(n):
        trip = (
            str(cols["source_system"][i]),
            str(cols["outcome_key"][i]),
            int(cols["requested_horizon_days"][i]),
        )
        if trip in vocab:
            eligible_idx.append(i)
        else:
            outside += 1
    seen: set[tuple[str, str, int]] = set()
    selected: list[int] = []
    dup = 0
    for i in eligible_idx:
        tkey = (str(cols["split_role"][i]), str(cols["target_id"][i]), int(cols["requested_horizon_days"][i]))
        if tkey in seen:
            dup += 1
        else:
            seen.add(tkey)
            selected.append(i)
    by: dict[tuple[str, str, str, int], list[int]] = defaultdict(list)
    for i in selected:
        key = (
            str(cols["source_system"][i]),
            str(cols["source_scoped_subject_id"][i]),
            str(cols["t0_iso"][i]),
            int(cols["requested_horizon_days"][i]),
        )
        by[key].append(i)
    row_class: dict[int, str] = {}
    strict_panels = async_groups = single_groups = 0
    for recs in by.values():
        by_ok: dict[str, int] = {}
        for i in recs:
            ok = str(cols["outcome_key"][i])
            prev = by_ok.get(ok)
            if prev is None:
                by_ok[ok] = i
                continue
            h = int(cols["requested_horizon_days"][i])
            d_new = abs(float(cols["actual_recorded_label_offset_days"][i] or 0) - h)
            d_old = abs(float(cols["actual_recorded_label_offset_days"][prev] or 0) - h)
            if d_new < d_old:
                row_class[prev] = CLASS_INVALID
                by_ok[ok] = i
            else:
                row_class[i] = CLASS_INVALID
        n_ok = len(by_ok)
        if n_ok < 2:
            single_groups += 1
            for i in by_ok.values():
                row_class[i] = CLASS_SINGLE
            continue
        stamps = set()
        for i in by_ok.values():
            h = int(cols["requested_horizon_days"][i])
            actual = float(cols["actual_recorded_label_offset_days"][i] or 0)
            stamps.add(_collapse_ts(str(cols["t0_iso"][i]), actual))
        label = CLASS_STRICT if len(stamps) == 1 else CLASS_ASYNC
        if label == CLASS_STRICT:
            strict_panels += 1
        else:
            async_groups += 1
        for i in by_ok.values():
            row_class[i] = label
    unclassified = [i for i in selected if i not in row_class]
    for i in unclassified:
        row_class[i] = CLASS_INVALID
    strict_rows = sum(1 for i in selected if row_class[i] == CLASS_STRICT)
    async_rows = sum(1 for i in selected if row_class[i] == CLASS_ASYNC)
    single_rows = sum(1 for i in selected if row_class[i] == CLASS_SINGLE)
    invalid = sum(1 for i in selected if row_class[i] == CLASS_INVALID)
    counts = {
        "raw_origin_rows": n,
        "outside_vocab_rows": outside,
        "eligible_origin_rows": len(eligible_idx),
        "duplicate_target_rows": dup,
        "deterministic_selected_rows": len(selected),
        "strict_panel_membership_rows": strict_rows,
        "asynchronous_vector_membership_rows": async_rows,
        "single_outcome_group_membership_rows": single_rows,
        "excluded_invalid_rows": invalid,
        "strict_panels": strict_panels,
        "asynchronous_groups": async_groups,
        "single_outcome_groups": single_groups,
        "unclassified_selected_rows_forced_invalid": len(unclassified),
    }
    rec = reconcile(counts)
    exclusive = (strict_rows + async_rows + single_rows + invalid) == len(selected)
    return {
        "version": VERSION,
        "universe": "LIVE_ORIGIN_AGGREGATES",
        "row_values_disclosed": False,
        "exclusive_classification": exclusive,
        "excluded_invalid_from_tagged_rows": True,
        "excluded_invalid_as_leftover_balance": False,
        "JOINT_PANEL_ROW_ACCOUNTING_STATUS": "RECONCILED" if rec["ok"] and exclusive else "NOT_RECONCILED",
        "JOINT_PANEL_ACCOUNTING_STATUS": "RECONCILED" if rec["ok"] and exclusive else "NOT_RECONCILED",
        "row_counts": counts,
        **rec,
        "ok": rec["ok"] and exclusive,
    }


def _load_v02_cells(root: Path) -> list[dict[str, Any]]:
    path = Path(root) / V02_MODELS / "pre-test-cells.json"
    if not path.is_file():
        return []
    return list((json.loads(path.read_text(encoding="utf-8")).get("cells") or []))


def vocab_v01(cells: list[dict[str, Any]]) -> set[tuple[str, str, int]]:
    return {
        (str(c["source_system"]), str(c["outcome_key"]), int(c["horizon_days"]))
        for c in cells
        if c.get("validation_gate_accepted") and c.get("source_system") and c.get("outcome_key")
    }


def vocab_v011(cells: list[dict[str, Any]]) -> set[tuple[str, str, int]]:
    return {
        (str(c["source_system"]), str(c["outcome_key"]), int(c["horizon_days"]))
        for c in cells
        if c.get("source_system") and c.get("outcome_key")
    }


def _strict_panel_keys(
    cols: dict[str, list[Any]],
    *,
    vocab: set[tuple[str, str, int]],
    drop_duplicates: bool,
) -> tuple[set[str], dict[str, int]]:
    n = len(next(iter(cols.values()))) if cols else 0
    eligible: list[int] = []
    outside = 0
    for i in range(n):
        trip = (
            str(cols["source_system"][i]),
            str(cols["outcome_key"][i]),
            int(cols["requested_horizon_days"][i]),
        )
        if trip in vocab:
            eligible.append(i)
        else:
            outside += 1
    dup = 0
    selected: list[int]
    if drop_duplicates:
        seen: set[tuple[str, str, int]] = set()
        selected = []
        for i in eligible:
            tkey = (str(cols["split_role"][i]), str(cols["target_id"][i]), int(cols["requested_horizon_days"][i]))
            if tkey in seen:
                dup += 1
            else:
                seen.add(tkey)
                selected.append(i)
    else:
        seen_all: set[tuple[str, str, int]] = set()
        selected = list(eligible)
        for i in eligible:
            tkey = (str(cols["split_role"][i]), str(cols["target_id"][i]), int(cols["requested_horizon_days"][i]))
            if tkey in seen_all:
                dup += 1
            seen_all.add(tkey)
    by: dict[tuple[str, str, str, int], list[int]] = defaultdict(list)
    for i in selected:
        key = (
            str(cols["source_system"][i]),
            str(cols["source_scoped_subject_id"][i]),
            str(cols["t0_iso"][i]),
            int(cols["requested_horizon_days"][i]),
        )
        by[key].append(i)
    strict: set[str] = set()
    async_n = single_n = 0
    for (ss, sid, t0_iso, h), recs in by.items():
        by_ok: dict[str, int] = {}
        for i in recs:
            ok = str(cols["outcome_key"][i])
            prev = by_ok.get(ok)
            if prev is None:
                by_ok[ok] = i
                continue
            d_new = abs(float(cols["actual_recorded_label_offset_days"][i] or 0) - h)
            d_old = abs(float(cols["actual_recorded_label_offset_days"][prev] or 0) - h)
            if d_new < d_old:
                by_ok[ok] = i
        if len(by_ok) < 2:
            single_n += 1
            continue
        stamps = {
            _collapse_ts(str(cols["t0_iso"][i]), float(cols["actual_recorded_label_offset_days"][i] or 0))
            for i in by_ok.values()
        }
        if len(stamps) == 1:
            strict.add(panel_key_sha256(ss, sid, t0_iso, h))
        else:
            async_n += 1
    stats = {
        "raw_origin_rows": n,
        "outside_vocab_rows": outside,
        "eligible_origin_rows": len(eligible),
        "duplicate_target_rows": dup,
        "grouped_rows": len(selected),
        "strict_panels": len(strict),
        "asynchronous_groups": async_n,
        "single_outcome_groups": single_n,
        "n_groups": len(by),
    }
    return strict, stats


def _step(name: str, before: set[str], after: set[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    gained = after - before
    lost = before - after
    rec = {
        "step": name,
        "strict_panels_before": len(before),
        "strict_panels_after": len(after),
        "n_gained_panel_keys": len(gained),
        "n_lost_panel_keys": len(lost),
        "delta_strict_panels": len(after) - len(before),
        "gained_keyset_sha256": set_digest(gained) if gained else None,
        "lost_keyset_sha256": set_digest(lost) if lost else None,
        "panel_keys_disclosed": False,
        "subject_identifiers_disclosed": False,
    }
    if extra:
        rec.update(extra)
    return rec


def numerical_panel_bridge(root: Path) -> dict[str, Any]:
    origin = Path(root) / V01_ORIGINS
    cells = _load_v02_cells(root)
    if not origin.is_file() or not cells:
        return {
            "version": VERSION,
            "JOINT_PANEL_COUNT_BRIDGE_STATUS": "NOT_RECONCILED",
            "reason": "ORIGIN_OR_VOCAB_UNAVAILABLE",
            "row_values_disclosed": False,
        }
    table = pq.read_table(origin, columns=list(ORIGIN_COLUMNS))
    cols = table.to_pydict()
    v01 = vocab_v01(cells)
    v011 = vocab_v011(cells)
    observed = {
        (str(cols["source_system"][i]), str(cols["outcome_key"][i]), int(cols["requested_horizon_days"][i]))
        for i in range(len(cols["source_system"]))
    }
    keys_raw_unfiltered, raw_stats = _strict_panel_keys(cols, vocab=observed, drop_duplicates=False)
    keys_v01_keep, st_v01 = _strict_panel_keys(cols, vocab=v01, drop_duplicates=False)
    keys_v011_keep, st_v011_keep = _strict_panel_keys(cols, vocab=v011, drop_duplicates=False)
    keys_v011_drop, st_v011 = _strict_panel_keys(cols, vocab=v011, drop_duplicates=True)
    # Published comparison starts at the v0.1 algorithm complete (keep duplicates, v0.1 vocab).
    # Raw universe is reported as a baseline, not as a term in the -3620 sum.
    steps = [
        _step(
            "1_raw_origin_universe_baseline_not_in_published_delta",
            keys_raw_unfiltered,
            keys_raw_unfiltered,
            {
                "row_stats": {
                    "raw_origin_rows": raw_stats["raw_origin_rows"],
                    "eligible_origin_rows": raw_stats["eligible_origin_rows"],
                    "strict_panels_on_unfiltered_keep_duplicates": len(keys_raw_unfiltered),
                },
                "included_in_published_delta_sum": False,
            },
        ),
        _step(
            "2_vocabulary_filter_apply_v0.1_then_v0.1.1_on_keep_duplicates",
            keys_v01_keep,
            keys_v011_keep,
            {
                "n_vocab_v01": len(v01),
                "n_vocab_v011": len(v011),
                "vocab_symmetric_difference": len(v01 ^ v011),
                "eligible_v01": st_v01["eligible_origin_rows"],
                "eligible_v011": st_v011_keep["eligible_origin_rows"],
                "outside_v01": st_v01["outside_vocab_rows"],
                "outside_v011": st_v011_keep["outside_vocab_rows"],
                "included_in_published_delta_sum": True,
            },
        ),
        _step(
            "3_duplicate_target_resolution_drop_before_grouping",
            keys_v011_keep,
            keys_v011_drop,
            {
                "duplicate_target_rows_counted_v01_style": st_v011_keep["duplicate_target_rows"],
                "duplicate_target_rows_dropped_v011": st_v011["duplicate_target_rows"],
                "grouped_rows_before": st_v011_keep["grouped_rows"],
                "grouped_rows_after": st_v011["grouped_rows"],
                "n_groups_before": st_v011_keep["n_groups"],
                "n_groups_after": st_v011["n_groups"],
                "included_in_published_delta_sum": True,
                "note": "duplicate_target_rows is a row count, not a panel-count proof by itself",
            },
        ),
        _step(
            "4_group_keys_source_subject_t0_horizon",
            keys_v011_drop,
            keys_v011_drop,
            {"group_key_definition_changed": False, "included_in_published_delta_sum": True},
        ),
        _step(
            "5_one_target_per_outcome_closest_to_horizon",
            keys_v011_drop,
            keys_v011_drop,
            {"selector_changed": False, "included_in_published_delta_sum": True},
        ),
        _step(
            "6_collapsed_timestamp_predicate",
            keys_v011_drop,
            keys_v011_drop,
            {"predicate_changed": False, "included_in_published_delta_sum": True},
        ),
        _step(
            "7_strict_async_single_classification",
            keys_v011_drop,
            keys_v011_drop,
            {
                "async_groups": st_v011["asynchronous_groups"],
                "single_outcome_groups": st_v011["single_outcome_groups"],
                "classification_rule_changed": False,
                "included_in_published_delta_sum": True,
            },
        ),
    ]
    published_path_delta = len(keys_v011_drop) - len(keys_v01_keep)
    step_delta_sum = sum(int(s["delta_strict_panels"]) for s in steps if s.get("included_in_published_delta_sum"))
    reproduced_v01 = len(keys_v01_keep)
    reproduced_v011 = len(keys_v011_drop)
    endpoints_match = reproduced_v01 == PUBLISHED_V01_STRICT and reproduced_v011 == PUBLISHED_V011_STRICT
    deltas_match = published_path_delta == PUBLISHED_DELTA and step_delta_sum == PUBLISHED_DELTA
    status = "RECONCILED" if endpoints_match and deltas_match else "NOT_RECONCILED"
    private_dir = Path(root) / RUNTIME_DIR
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / "panel-count-bridge-keyset-digests.json").write_text(
        json.dumps(
            {
                "v01_strict_keyset_sha256": set_digest(keys_v01_keep),
                "v011_keep_dup_keyset_sha256": set_digest(keys_v011_keep),
                "v011_strict_keyset_sha256": set_digest(keys_v011_drop),
                "n_v01": reproduced_v01,
                "n_v011": reproduced_v011,
                "panel_keys_disclosed": False,
                "subject_identifiers_disclosed": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "version": VERSION,
        "universe": "SAME_PRIVATE_ORIGIN_PARQUET_AS_V01_AND_V011",
        "row_values_disclosed": False,
        "panel_keys_disclosed": False,
        "subject_identifiers_disclosed": False,
        "algorithm_order": [s["step"] for s in steps],
        "steps": steps,
        "reproduced": {
            "v01_strict_panels": reproduced_v01,
            "v011_strict_panels": reproduced_v011,
            "delta": published_path_delta,
            "published_v01_strict_panels": PUBLISHED_V01_STRICT,
            "published_v011_strict_panels": PUBLISHED_V011_STRICT,
            "published_delta": PUBLISHED_DELTA,
            "sum_of_step_deltas_after_raw": step_delta_sum,
        },
        "equation": "n_v011 - n_v01 = sum(step_delta after raw filter chain) = -3620",
        "duplicate_row_count_is_not_panel_delta_proof": True,
        "JOINT_PANEL_COUNT_BRIDGE_STATUS": status,
        "ok": status == "RECONCILED",
    }


def json_load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def v01_v011_published_totals(root: Path) -> dict[str, Any]:
    v01_path = Path(root) / V01_ARTIFACT / "joint-panel-accounting.json"
    v011_path = Path(root) / V011_ARTIFACT / "joint-panel-accounting.json"
    v01 = json_load(v01_path)
    v011 = json_load(v011_path)
    n01 = int(v01.get("n_strict_panels") or 0) if v01 else None
    live = (v011 or {}).get("live") or {}
    n011 = int((live.get("row_counts") or {}).get("strict_panels") or 0) if v011 else None
    return {
        "published_v01_strict_panels": n01,
        "published_v011_strict_panels": n011,
        "published_delta": (n011 - n01) if n01 is not None and n011 is not None else None,
        "matching_published_totals_is_not_explanation": True,
    }


def build_accounting(root: Path, vocab: set[tuple[str, str, int]] | None = None) -> dict[str, Any]:
    syn = synthetic_accounting()
    live_path = Path(root) / V01_ORIGINS
    live = None
    if live_path.is_file() and vocab:
        live = recount_origins(live_path, vocab)
    bridge = numerical_panel_bridge(root)
    published = v01_v011_published_totals(root)
    live_ok = live is None or live.get("ok")
    row_status = "RECONCILED" if syn["ok"] and live_ok else "NOT_RECONCILED"
    return {
        "version": VERSION,
        "JOINT_PANEL_ROW_ACCOUNTING_STATUS": row_status,
        "JOINT_PANEL_COUNT_BRIDGE_STATUS": bridge.get("JOINT_PANEL_COUNT_BRIDGE_STATUS"),
        "JOINT_PANEL_ACCOUNTING_STATUS": row_status,
        "synthetic_portable": syn,
        "live": {k: v for k, v in (live or {}).items() if k != "ok"} if live else None,
        "v01_v011_bridge": {**bridge, "published_totals_are_not_an_explanation": published},
        "ok": syn["ok"] and live_ok,
        "bridge_ok": bool(bridge.get("ok")),
    }
