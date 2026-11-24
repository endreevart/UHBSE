"""CLI handlers for ``audit core …`` commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.core import source_a as src
from human_simulator.core.load import load_canonical
from human_simulator.core.policy import CORE_ARTIFACT_DIR, DEFAULT_SUBJECT_LIMIT, policy_snapshot
from human_simulator.core.simulation import (
    EmpiricalTrendModel,
    HeuristicDriftBaselineModel,
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    build_timeline,
)
from human_simulator.core.snapshot import build_evidence_state_snapshot
from human_simulator.core.evidence_closure import run_evidence_closure


def _print(doc: Any) -> None:
    print(json.dumps(doc, indent=2, default=str))


def cmd_profile_source_a(root: Path) -> int:
    with src.source_a_connection(root) as conn:
        access = src.access_probe(conn)
        counts = src.relation_counts(conn)
        eligibility = src.cohort_eligibility_aggregates(conn)
    _print(
        {
            "access": access,
            "relation_counts": counts,
            "eligibility": eligibility,
            "policy": policy_snapshot(),
            "security_gate": "ADVISORY_ONLY_not_consulted",
        }
    )
    return 0 if access.get("readable") else 1


def cmd_build_cohort(root: Path, *, limit: int) -> int:
    with src.source_a_connection(root) as conn:
        eligibility = src.cohort_eligibility_aggregates(conn)
        ids = src.select_cohort_patient_ids(conn, limit=limit)
    out = root / CORE_ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    doc = {
        "cohort_size": len(ids),
        "requested_limit": limit,
        "eligibility": eligibility,
        "raw_ids_not_written": True,
    }
    (out / "cohort-selection-cli.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    _print(doc)
    return 0 if ids else 1


def cmd_load_canonical(root: Path, *, limit: int) -> int:
    import hashlib

    with src.source_a_connection(root) as conn:
        ids = src.select_cohort_patient_ids(conn, limit=limit)
    input_sha = hashlib.sha256(f"cli-load|{limit}|{len(ids)}".encode()).hexdigest()
    report = load_canonical(root, patient_ids=ids, input_sha=input_sha)
    _print(report)
    return 0 if report["subjects_loaded"] > 0 else 1


def cmd_build_timeline(root: Path) -> int:
    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings
    from human_simulator.core.vertical_slice import fetch_canonical_bundle

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT subject_id FROM canonical_evidence.subject WHERE source_system_id=%s LIMIT 5",
                ("magerya_api",),
            )
            subject_ids = [r[0] for r in cur.fetchall()]
        bundle = fetch_canonical_bundle(conn, subject_ids)
    summaries = []
    for sid in subject_ids:
        tl = build_timeline(
            subject_id=sid,
            encounters=bundle["encounters"],
            observations=bundle["observations"],
            components=bundle["components"],
        )
        summaries.append({"subject_id": sid, "event_count": len(tl)})
    _print({"timelines": summaries, "ordering": ["clinical_time", "recorded_time", "source_order"]})
    return 0 if summaries else 1


def cmd_build_starting_state(root: Path) -> int:
    from datetime import UTC, datetime

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings
    from human_simulator.core.vertical_slice import _choose_snapshot_at, fetch_canonical_bundle

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT subject_id FROM canonical_evidence.subject WHERE source_system_id=%s LIMIT 5",
                ("magerya_api",),
            )
            subject_ids = [r[0] for r in cur.fetchall()]
        bundle = fetch_canonical_bundle(conn, subject_ids)
    states = []
    for sid in subject_ids:
        snap_at = _choose_snapshot_at(bundle["observations"], sid)
        snap = build_evidence_state_snapshot(
            subject_id=sid,
            snapshot_at=snap_at,
            source_event_cutoff=snap_at,
            characteristics=bundle["characteristics"],
            encounters=bundle["encounters"],
            observations=bundle["observations"],
            components=bundle["components"],
        )
        states.append(
            {
                "snapshot_id": snap.snapshot_id,
                "snapshot_at": snap.snapshot_at,
                "completeness": snap.completeness,
                "component_count": len(snap.components),
            }
        )
    _print(
        {
            "count": len(states),
            "states": states,
            "imputation_forbidden_silent": True,
        }
    )
    return 0 if states else 1


def cmd_simulate(root: Path, *, seed: int = 42) -> int:
    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings
    from human_simulator.core.vertical_slice import _choose_snapshot_at, fetch_canonical_bundle

    state_snap = None
    try:
        settings = load_canonical_settings()
        with canonical_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT subject_id FROM canonical_evidence.subject WHERE source_system_id=%s LIMIT 1",
                    ("magerya_api",),
                )
                row = cur.fetchone()
            if row:
                bundle = fetch_canonical_bundle(conn, [row[0]])
                snap_at = _choose_snapshot_at(bundle["observations"], row[0])
                state_snap = build_evidence_state_snapshot(
                    subject_id=row[0],
                    snapshot_at=snap_at,
                    source_event_cutoff=snap_at,
                    characteristics=bundle["characteristics"],
                    encounters=bundle["encounters"],
                    observations=bundle["observations"],
                    components=bundle["components"],
                )
    except Exception as exc:  # noqa: BLE001
        _print({"error": type(exc).__name__})
        return 1

    if state_snap is None:
        from human_simulator.core.snapshot import EvidenceStateSnapshot

        state_snap = EvidenceStateSnapshot(
            snapshot_id="demo",
            subject_id="demo",
            snapshot_at="2020-01-01T00:00:00Z",
            snapshot_kind="baseline",
            source_event_cutoff="2020-01-01T00:00:00Z",
            provenance={"record_origin": "DERIVED"},
            components=[],
        )

    kernel = SimulationKernel(seed=seed, horizon_weeks=12)
    models = {
        "persistence": PersistenceBaselineModel(),
        "heuristic": HeuristicDriftBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    result = kernel.run_branches(starting=state_snap, models=models)
    _print(
        {
            "seed": result["seed"],
            "branches": [b["branch_id"] for b in result["branches"]],
            "checkpoints": len(result.get("checkpoints") or []),
            "fork_ok": (result.get("fork") or {}).get("ok"),
            "rollback_ok": (result.get("rollback") or {}).get("ok"),
            "input_state_hash": result["input_state_hash"],
            "configuration_hash": result["configuration_hash"],
        }
    )
    return 0


def cmd_compare_branches(root: Path) -> int:
    path = root / CORE_ARTIFACT_DIR / "branch-comparison.json"
    if not path.is_file():
        _print({"error": "run core run-vertical-slice first", "path": str(path)})
        return 1
    _print(json.loads(path.read_text(encoding="utf-8")))
    return 0


def cmd_rollback_run(root: Path) -> int:
    path = root / CORE_ARTIFACT_DIR / "checkpoint-rollback-report.json"
    if not path.is_file():
        _print({"error": "run core run-vertical-slice first"})
        return 1
    _print(json.loads(path.read_text(encoding="utf-8")))
    return 0


def cmd_verify(root: Path) -> int:
    path = root / CORE_ARTIFACT_DIR / "core-verification.json"
    if not path.is_file():
        _print({"error": "missing core-verification.json; run core run-vertical-slice"})
        return 1
    doc = json.loads(path.read_text(encoding="utf-8"))
    _print(doc)
    status = doc.get("core_vertical_slice_status")
    if status in {"PASS", "TECHNICAL_VERTICAL_SLICE_PASS"}:
        return 0
    if status in {"PARTIAL", "TECHNICAL_VERTICAL_SLICE_PARTIAL"}:
        return 2
    return 1


def cmd_run_vertical_slice(root: Path, *, limit: int, seed: int) -> int:
    # v0.1.2.1: evidence closure only — no clinical extraction/load
    _ = limit
    result = run_evidence_closure(root, seed=seed)
    _print(result)
    status = result.get("core_vertical_slice_status")
    if status in {"PASS", "TECHNICAL_VERTICAL_SLICE_PASS"}:
        return 0
    if status in {"PARTIAL", "TECHNICAL_VERTICAL_SLICE_PARTIAL"}:
        return 2
    return 1


def cmd_publish(root: Path) -> int:
    from human_simulator.core.publish import PublicationError, publish_core_vertical_slice

    try:
        result = publish_core_vertical_slice(root)
    except PublicationError as exc:
        _print({"error": str(exc)})
        return 1
    _print(result)
    return 0


def dispatch_core(root: Path, core_command: str, args: Any) -> int:
    if core_command == "profile-source-a":
        return cmd_profile_source_a(root)
    if core_command == "build-cohort":
        return cmd_build_cohort(root, limit=getattr(args, "limit", DEFAULT_SUBJECT_LIMIT))
    if core_command == "load-canonical":
        return cmd_load_canonical(root, limit=getattr(args, "limit", DEFAULT_SUBJECT_LIMIT))
    if core_command == "build-timeline":
        return cmd_build_timeline(root)
    if core_command == "build-starting-state":
        return cmd_build_starting_state(root)
    if core_command == "simulate":
        return cmd_simulate(root, seed=getattr(args, "seed", 42))
    if core_command == "compare-branches":
        return cmd_compare_branches(root)
    if core_command == "rollback-run":
        return cmd_rollback_run(root)
    if core_command == "verify":
        return cmd_verify(root)
    if core_command == "run-vertical-slice":
        return cmd_run_vertical_slice(
            root,
            limit=getattr(args, "limit", DEFAULT_SUBJECT_LIMIT),
            seed=getattr(args, "seed", 42),
        )
    if core_command == "publish":
        return cmd_publish(root)
    _print({"error": f"unknown core command: {core_command}"})
    return 2
