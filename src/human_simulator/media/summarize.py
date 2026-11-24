"""Build a PII-free media summary from core vertical-slice artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from human_simulator.core.policy import CORE_SLICE_VERSION, COHORT_SAMPLE_CLASS, policy_snapshot
from human_simulator.media.paths import HEX64, ISO_TS, artifact_dir, safe_dir, summary_path

_FORBIDDEN = (
    re.compile(HEX64),
    re.compile(ISO_TS),
    re.compile(r"(?i)postgres(?:ql)?://"),
    re.compile(r"(?i)patient_id"),
    re.compile(r"(?i)\bhvs\."),
    re.compile(r"(?i)\"password\"\s*:"),
)


class MediaSummarizeError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MediaSummarizeError(f"missing artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _row_counts(doc: dict[str, Any]) -> dict[str, int]:
    for key in ("after_v0121", "after_second_load", "after_first_load", "baseline_v012"):
        block = doc.get(key)
        if isinstance(block, dict) and "subject" in block:
            return {str(k): int(v) for k, v in block.items() if isinstance(v, int)}
    raise MediaSummarizeError("canonical row counts not found")


def _snapshot_aggregates(doc: dict[str, Any]) -> dict[str, int]:
    totals = {
        "demographics_count": 0,
        "lab_count": 0,
        "imputed_count": 0,
        "conflict_count": 0,
        "excluded_future_count": 0,
    }
    for state in doc.get("states") or []:
        if not isinstance(state, dict):
            continue
        comp = state.get("completeness") or {}
        for key in totals:
            totals[key] += int(comp.get(key) or 0)
    return totals


def _assert_safe(text: str, *, where: str) -> None:
    for pat in _FORBIDDEN:
        if pat.search(text):
            raise MediaSummarizeError(f"refusing to write {where}: matched {pat.pattern}")


def build_summary(root: Path) -> dict[str, Any]:
    src = artifact_dir(root)
    counts_doc = _load(src / "canonical-row-counts-before-after.json")
    prov_doc = _load(src / "provenance-coverage.json")
    scope = _load(src / "cohort-scope-report.json")
    timeline = _load(src / "timeline-summary.json")
    snapshot = _load(src / "starting-state-summary.json")
    branches = _load(src / "branch-comparison.json")
    idem = _load(src / "idempotency-report.json")
    verify = _load(src / "core-verification.json")

    db_prov = prov_doc.get("database_provenance_coverage") or prov_doc
    snap_agg = _snapshot_aggregates(snapshot)
    policy = policy_snapshot()
    fork = branches.get("counterfactual_vs_event_fork") or {}
    divergence_week = fork.get("first_divergence_week")
    if divergence_week is not None:
        divergence_week = int(divergence_week)

    summary: dict[str, Any] = {
        "schema": "uhbse.media.summary.v1",
        "slice_version": CORE_SLICE_VERSION,
        "status": verify.get("core_vertical_slice_status"),
        "sample_class": scope.get("sample_class") or COHORT_SAMPLE_CLASS,
        "clinical_validation": policy["clinical_validation_status"],
        "production_readiness": policy["production_readiness"],
        "scope": {
            "cohort_loaded_subjects": int(scope["cohort_loaded_subjects"]),
            "timelines_built_subjects": int(scope["timelines_built_subjects"]),
            "snapshots_built_subjects": int(scope["snapshots_built_subjects"]),
            "simulated_subjects": int(scope["simulated_subjects"]),
        },
        "row_counts": _row_counts(counts_doc),
        "row_counts_unchanged": bool(counts_doc.get("unchanged", idem.get("row_counts_unchanged"))),
        "provenance": {
            "total_records_evaluated": int(db_prov["total_records_evaluated"]),
            "valid_records": int(db_prov["valid_records"]),
            "invalid_records": int(db_prov.get("invalid_records") or 0),
            "full_coverage": bool(db_prov.get("full_coverage")),
        },
        "timeline": {
            "subjects_summarised": int(timeline["subjects_summarised"]),
            "total_events": int(timeline["total_events"]),
            "ordering": list(timeline.get("ordering") or []),
        },
        "snapshot": {
            "subjects_summarised": int(snapshot["subjects_summarised"]),
            "imputation_policy": str(snapshot.get("imputation_policy") or "unknown"),
            **snap_agg,
        },
        "branches": {
            "count": 3,
            "dose_change_differs": bool(branches.get("dose_change_branch_differs")),
            "first_divergence_week": divergence_week,
            "labels": ["control", "intervention", "dose change"],
        },
        "idempotent": bool(idem.get("idempotent")),
        "disclaimer": (
            "Technical vertical slice. Not a clinical model. "
            "Clinical validation not started. Production readiness not claimed."
        ),
    }
    dumped = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    _assert_safe(dumped, where="media summary")
    return summary


def write_summary(root: Path) -> Path:
    summary = build_summary(root)
    out = summary_path(root)
    safe_dir(root).mkdir(parents=True, exist_ok=True)
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    out.write_text(text, encoding="utf-8")
    return out
