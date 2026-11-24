"""Core Engine Vertical Slice v0.1.2 orchestrator with computed verification."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.migrations import row_counts
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.core import source_a as src
from human_simulator.core.ids import load_hmac_key, opaque_subject_key
from human_simulator.core.load import load_canonical
from human_simulator.core.policy import (
    CHECKPOINT_PHASE,
    COHORT_SAMPLE_CLASS,
    CORE_ARTIFACT_DIR,
    CORE_SLICE_VERSION,
    DEFAULT_SUBJECT_LIMIT,
    PER_PATIENT_LAB_LIMIT,
    PER_RESULT_ITEM_LIMIT,
    SIMULATED_SUBJECT_LIMIT,
    SNAPSHOT_SUBJECT_LIMIT,
    TIMELINE_SUBJECT_LIMIT,
    policy_snapshot,
)
from human_simulator.core.provenance import (
    evaluate_db_provenance_coverage,
    evaluate_snapshot_provenance,
)
from human_simulator.core.simulation import (
    HeuristicDriftBaselineModel,
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    build_timeline,
    hash_state,
)
from human_simulator.core.snapshot import (
    build_evidence_state_snapshot,
    iso_z,
    parse_ts,
    snapshot_content_hash,
)

PII_ARTIFACT_PATTERNS = (
    re.compile(r"(?i)postgresql://"),
    re.compile(r"(?i)\bhvs\."),
    re.compile(r"(?i)\"password\"\s*:"),
    re.compile(r"(?i)\"patient_id\"\s*:"),
    re.compile(r"(?i)raw patient id"),
)


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc, encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_canonical_bundle(conn: Any, subject_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not subject_ids:
        return {"encounters": [], "observations": [], "components": [], "characteristics": []}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT encounter_id, subject_id, occurred_at::text, recorded_at::text, status
            FROM canonical_evidence.encounter WHERE subject_id = ANY(%s)
            """,
            (subject_ids,),
        )
        encounters = [
            {
                "encounter_id": r[0],
                "subject_id": r[1],
                "occurred_at": r[2],
                "recorded_at": r[3],
                "status": r[4],
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT observation_id, subject_id, observed_at::text, recorded_at::text,
                   specimen_collected_at::text, status
            FROM canonical_evidence.observation WHERE subject_id = ANY(%s)
            """,
            (subject_ids,),
        )
        observations = [
            {
                "observation_id": r[0],
                "subject_id": r[1],
                "observed_at": r[2],
                "recorded_at": r[3],
                "specimen_collected_at": r[4],
                "status": r[5],
            }
            for r in cur.fetchall()
        ]
        obs_ids = [o["observation_id"] for o in observations]
        components: list[dict[str, Any]] = []
        if obs_ids:
            cur.execute(
                """
                SELECT component_id, observation_id, raw_code, raw_value, numeric_value, raw_unit
                FROM canonical_evidence.observation_component WHERE observation_id = ANY(%s)
                """,
                (obs_ids,),
            )
            components = [
                {
                    "component_id": r[0],
                    "observation_id": r[1],
                    "raw_code": r[2],
                    "raw_value": r[3],
                    "numeric_value": float(r[4]) if r[4] is not None else None,
                    "raw_unit": r[5],
                }
                for r in cur.fetchall()
            ]
        cur.execute(
            """
            SELECT characteristic_id, subject_id, characteristic_code, raw_value
            FROM canonical_evidence.subject_characteristic WHERE subject_id = ANY(%s)
            """,
            (subject_ids,),
        )
        characteristics = [
            {
                "characteristic_id": r[0],
                "subject_id": r[1],
                "characteristic_code": r[2],
                "raw_value": r[3],
            }
            for r in cur.fetchall()
        ]
    return {
        "encounters": encounters,
        "observations": observations,
        "components": components,
        "characteristics": characteristics,
    }


# Alias used by cli.py
_fetch_canonical_bundle = fetch_canonical_bundle


def _choose_snapshot_at(observations: list[dict[str, Any]], subject_id: str) -> datetime:
    times = []
    for obs in observations:
        if obs.get("subject_id") != subject_id:
            continue
        for key in ("observed_at", "specimen_collected_at", "recorded_at"):
            ts = parse_ts(obs.get(key))
            if ts is not None:
                times.append(ts)
                break
    if not times:
        return datetime(2020, 1, 1, tzinfo=UTC)
    return max(times)


def _scan_artifacts_for_pii(out: Path) -> dict[str, Any]:
    hits: list[str] = []
    for path in out.rglob("*"):
        if not path.is_file() or path.name == "manifest.sha256":
            continue
        if path.suffix not in {".json", ".md", ".yaml", ".yml", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in PII_ARTIFACT_PATTERNS:
            if pat.search(text):
                hits.append(f"{path.name}:{pat.pattern}")
    return {"ok": len(hits) == 0, "hits": hits}


def run_vertical_slice(
    repo_root: Path,
    *,
    subject_limit: int = DEFAULT_SUBJECT_LIMIT,
    seed: int = 42,
) -> dict[str, Any]:
    out = repo_root / CORE_ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat()

    with src.source_a_connection(repo_root) as sconn:
        access = src.access_probe(sconn)
        rel_counts = src.relation_counts(sconn)
        eligibility = src.cohort_eligibility_aggregates(sconn)
        patient_ids = src.select_cohort_patient_ids(sconn, limit=subject_limit)

    _write(
        out / "source-a-access-report.json",
        {
            **access,
            "relation_counts": rel_counts,
            "security_gate_mode": "ADVISORY_ONLY",
            "authorised_data_access": True,
        },
    )

    key = load_hmac_key(repo_root)
    opaque_keys = [opaque_subject_key(key, pid) for pid in patient_ids]
    cohort_scope = {
        "cohort_loaded_subjects": len(patient_ids),
        "requested_limit": subject_limit,
        "sample_class": COHORT_SAMPLE_CLASS,
        "forbidden_for_model_quality_evaluation": True,
        "criteria": ["account_patient", ">=3 appointments", ">=1 lab panel", "densest_first"],
        "timelines_built_subjects_cap": TIMELINE_SUBJECT_LIMIT,
        "snapshots_built_subjects_cap": SNAPSHOT_SUBJECT_LIMIT,
        "simulated_subjects_cap": SIMULATED_SUBJECT_LIMIT,
    }
    _write(out / "cohort-scope-report.json", {**cohort_scope, "eligibility": eligibility})
    _write(
        out / "cohort-selection.json",
        {
            "cohort_size": len(opaque_keys),
            "opaque_subject_keys_sample": opaque_keys[:5],
            "sample_class": COHORT_SAMPLE_CLASS,
            "raw_patient_ids_excluded": True,
        },
    )
    _write(
        out / "cohort-profile.json",
        {
            "eligibility": eligibility,
            "selected_domain": "document_analysisresult + appointment_appointment",
            "sample_class": COHORT_SAMPLE_CLASS,
            "default_subject_limit": DEFAULT_SUBJECT_LIMIT,
        },
    )

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        # Derived-only reset for reproducible pilot reload (never touches Source A)
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE TABLE
                  canonical_evidence.observation_component,
                  canonical_evidence.observation,
                  canonical_evidence.encounter,
                  canonical_evidence.subject_characteristic,
                  canonical_evidence.subject,
                  canonical_evidence.source_record,
                  canonical_evidence.source_system
                RESTART IDENTITY CASCADE
                """
            )

    input_sha = hashlib.sha256(
        json.dumps({"cohort": opaque_keys, "limit": subject_limit, "v": CORE_SLICE_VERSION}, sort_keys=True).encode()
    ).hexdigest()

    load_report = load_canonical(
        repo_root,
        patient_ids=patient_ids,
        input_sha=input_sha,
        per_patient_limit=PER_PATIENT_LAB_LIMIT,
        per_result_limit=PER_RESULT_ITEM_LIMIT,
    )
    _write(out / "canonical-load-report.json", {k: v for k, v in load_report.items() if k != "write_errors" or True})
    _write(
        out / "canonical-row-counts-before-after.json",
        {
            "before": load_report["canonical_row_counts_before"],
            "after_first_load": load_report["canonical_row_counts"],
        },
    )
    _write(out / "extraction-truncation-report.json", load_report["truncation"])
    _write(
        out / "reject-report.json",
        {
            "reject_count": load_report["reject_count"],
            "categories": load_report["reject_categories"],
            "no_raw_values_or_ids": True,
        },
    )
    _write(out / "source-record-coverage.json", load_report["source_record_coverage"])

    # Idempotency: second load — all seven tables inserted counts must be 0
    load2 = load_canonical(
        repo_root,
        patient_ids=patient_ids,
        input_sha=input_sha,
        per_patient_limit=PER_PATIENT_LAB_LIMIT,
        per_result_limit=PER_RESULT_ITEM_LIMIT,
    )
    seven = (
        "source_system",
        "source_record",
        "subject",
        "subject_characteristic",
        "encounter",
        "observation",
        "observation_component",
    )
    idem_tables = {t: load2["inserted"].get(t, 0) == 0 for t in seven}
    counts_unchanged = load2["canonical_row_counts"] == load_report["canonical_row_counts"]
    idem = {
        "all_seven_tables_zero_insert_on_reload": all(idem_tables.values()),
        "per_table_zero_insert": idem_tables,
        "row_counts_unchanged": counts_unchanged,
        "row_counts_after_second_load": load2["canonical_row_counts"],
        "idempotent": all(idem_tables.values()) and counts_unchanged,
    }
    _write(out / "idempotency-report.json", idem)
    before_after = {
        "before": load_report["canonical_row_counts_before"],
        "after_first_load": load_report["canonical_row_counts"],
        "after_second_load": load2["canonical_row_counts"],
    }
    _write(out / "canonical-row-counts-before-after.json", before_after)

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT subject_id FROM canonical_evidence.subject WHERE source_system_id=%s ORDER BY subject_id",
                ("magerya_api",),
            )
            subject_ids = [r[0] for r in cur.fetchall()]
        bundle = fetch_canonical_bundle(conn, subject_ids)
        provenance_coverage = evaluate_db_provenance_coverage(conn)
        counts_final = row_counts(conn)
    _write(out / "provenance-coverage.json", provenance_coverage)

    known_entity_ids = {
        *(str(item["characteristic_id"]) for item in bundle["characteristics"]),
        *(str(item["observation_id"]) for item in bundle["observations"]),
        *(str(item["component_id"]) for item in bundle["components"]),
        *(str(subject_id) for subject_id in subject_ids),
    }

    timeline_subjects = subject_ids[:TIMELINE_SUBJECT_LIMIT]
    snapshot_subjects = subject_ids[:SNAPSHOT_SUBJECT_LIMIT]
    simulated_subjects = subject_ids[:SIMULATED_SUBJECT_LIMIT]

    timelines = []
    for sid in timeline_subjects:
        tl = build_timeline(
            subject_id=sid,
            encounters=bundle["encounters"],
            observations=bundle["observations"],
            components=bundle["components"],
        )
        timelines.append({"subject_id": sid, "event_count": len(tl), "events_sample": tl[:3]})
    _write(
        out / "timeline-summary.json",
        {
            "subjects_summarised": len(timelines),
            "total_events": sum(t["event_count"] for t in timelines),
            "ordering": ["clinical_time", "recorded_time", "source_order"],
            "timelines": timelines,
        },
    )

    snapshots = []
    snapshot_documents: list[dict[str, Any]] = []
    snapshot_contract_results: list[dict[str, Any]] = []
    leakage = {"subjects_checked": 0, "future_rows_excluded_total": 0, "conflicts_total": 0}
    for sid in snapshot_subjects:
        snap_at = _choose_snapshot_at(bundle["observations"], sid)
        snap = build_evidence_state_snapshot(
            subject_id=sid,
            snapshot_at=snap_at,
            source_event_cutoff=snap_at,
            snapshot_kind="baseline",
            characteristics=bundle["characteristics"],
            encounters=bundle["encounters"],
            observations=bundle["observations"],
            components=bundle["components"],
            input_artifact_sha256=input_sha,
        )
        snap_dict = snap.to_dict()
        snapshot_documents.append(snap_dict)
        contract_result = evaluate_snapshot_provenance(
            snap_dict,
            known_entity_ids=known_entity_ids,
        )
        snapshot_contract_results.append(
            {
                "snapshot_id": snap.snapshot_id,
                **contract_result,
            }
        )
        snapshots.append(
            {
                "snapshot_id": snap.snapshot_id,
                "subject_id": snap.subject_id,
                "snapshot_at": snap.snapshot_at,
                "snapshot_kind": snap.snapshot_kind,
                "source_event_cutoff": snap.source_event_cutoff,
                "completeness": snap.completeness,
                "component_count": len(snap.components),
                "content_hash": snapshot_content_hash(snap),
                "has_required_fields": all(
                    [
                        bool(snap.snapshot_id),
                        bool(snap.subject_id),
                        bool(snap.snapshot_at),
                        bool(snap.snapshot_kind),
                        bool(snap.source_event_cutoff),
                        bool(snap.provenance),
                    ]
                ),
                "components_have_input_refs": all(
                    bool(c.input_record_references) for c in snap.components
                ),
            }
        )
        leakage["subjects_checked"] += 1
        leakage["future_rows_excluded_total"] += snap.excluded_future_count
        leakage["conflicts_total"] += snap.conflict_count

    # Temporal leakage verification with synthetic future row
    if snapshot_subjects:
        sid0 = snapshot_subjects[0]
        snap_at = parse_ts(snapshots[0]["snapshot_at"])
        assert snap_at is not None
        future_obs = {
            "observation_id": "future-leak-test",
            "subject_id": sid0,
            "observed_at": iso_z(snap_at.replace(year=snap_at.year + 5)),
            "recorded_at": iso_z(snap_at.replace(year=snap_at.year + 5)),
        }
        future_comp = {
            "component_id": "future-comp",
            "observation_id": "future-leak-test",
            "raw_code": "LEAK_MARKER",
            "numeric_value": 999.0,
            "raw_value": "999",
        }
        leak_snap = build_evidence_state_snapshot(
            subject_id=sid0,
            snapshot_at=snap_at,
            source_event_cutoff=snap_at,
            characteristics=[],
            encounters=[],
            observations=[future_obs],
            components=[future_comp],
            input_artifact_sha256=input_sha,
        )
        leaked = any(c.variable_key == "LEAK_MARKER" for c in leak_snap.components)
        leakage["synthetic_future_injection"] = {
            "injected": True,
            "excluded_future_count": leak_snap.excluded_future_count,
            "marker_present_in_snapshot": leaked,
            "pass": (not leaked) and leak_snap.excluded_future_count >= 1,
        }
    else:
        leakage["synthetic_future_injection"] = {"pass": False, "reason": "no_subjects"}

    _write(out / "temporal-leakage-verification.json", leakage)
    _write(
        out / "snapshot-construction-report.json",
        {
            "snapshots_built_subjects": len(snapshots),
            "builder_version": CORE_SLICE_VERSION,
            "snapshots": snapshots,
            "runtime_only_no_migration_0005": True,
        },
    )
    _write(
        out / "starting-state-summary.json",
        {
            "subjects_summarised": len(snapshots),
            "states": [
                {
                    "subject_id": s["subject_id"],
                    "snapshot_at": s["snapshot_at"],
                    "completeness": s["completeness"],
                }
                for s in snapshots
            ],
            "imputation_policy": "no_silent_imputation",
        },
    )

    models = {
        "persistence": PersistenceBaselineModel(),
        "heuristic": HeuristicDriftBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    sim_doc: dict[str, Any] = {"status": "SKIP", "reason": "no_subjects"}
    primary_snap = None
    if simulated_subjects:
        sid = simulated_subjects[0]
        snap_at = _choose_snapshot_at(bundle["observations"], sid)
        primary_snap = build_evidence_state_snapshot(
            subject_id=sid,
            snapshot_at=snap_at,
            source_event_cutoff=snap_at,
            characteristics=bundle["characteristics"],
            encounters=bundle["encounters"],
            observations=bundle["observations"],
            components=bundle["components"],
            input_artifact_sha256=input_sha,
        )
        kernel = SimulationKernel(seed=seed, horizon_weeks=12)
        sim_doc = kernel.run_branches(starting=primary_snap, models=models)
        sim_doc["simulated_subjects"] = 1
        sim_doc["simulated_subject_ids"] = [sid]
        sim_doc["models"] = {
            "persistence": {
                "MODEL_ID": PersistenceBaselineModel.MODEL_ID,
                "MODEL_VERSION": PersistenceBaselineModel.MODEL_VERSION,
                "MODEL_KIND": PersistenceBaselineModel.MODEL_KIND,
                "CLINICAL_VALIDATION": PersistenceBaselineModel.CLINICAL_VALIDATION,
            },
            "heuristic": {
                "MODEL_ID": HeuristicDriftBaselineModel.MODEL_ID,
                "MODEL_VERSION": HeuristicDriftBaselineModel.MODEL_VERSION,
                "MODEL_KIND": HeuristicDriftBaselineModel.MODEL_KIND,
                "CLINICAL_VALIDATION": HeuristicDriftBaselineModel.CLINICAL_VALIDATION,
                "NOTE": HeuristicDriftBaselineModel.NOTE,
            },
            "synthetic": {
                "MODEL_ID": SyntheticInterventionTestModel.MODEL_ID,
                "MODEL_VERSION": SyntheticInterventionTestModel.MODEL_VERSION,
                "MODEL_KIND": SyntheticInterventionTestModel.MODEL_KIND,
                "CLINICAL_USE": SyntheticInterventionTestModel.CLINICAL_USE,
            },
        }

    # Cross-process determinism checked in tests; record in-process duplicate here
    determinism = {"in_process_repeat": None, "cross_process": "see_unit_tests"}
    if primary_snap is not None:
        k2 = SimulationKernel(seed=seed, horizon_weeks=12)
        sim2 = k2.run_branches(starting=primary_snap, models=models)
        determinism["in_process_repeat"] = {
            "input_state_hash_match": sim_doc["input_state_hash"] == sim2["input_state_hash"],
            "configuration_hash_match": sim_doc["configuration_hash"] == sim2["configuration_hash"],
            "branch_final_hashes_match": [
                a["final_state_hash"] == b["final_state_hash"]
                for a, b in zip(sim_doc["branches"], sim2["branches"], strict=True)
            ],
        }
        determinism["pass"] = (
            determinism["in_process_repeat"]["input_state_hash_match"]
            and determinism["in_process_repeat"]["configuration_hash_match"]
            and all(determinism["in_process_repeat"]["branch_final_hashes_match"])
        )

    _write(out / "simulation-run.json", sim_doc)
    finals = {b["branch_id"]: b["final_state"] for b in sim_doc.get("branches") or []}
    compare = {
        "final_state_hashes": {
            b["branch_id"]: b["final_state_hash"] for b in sim_doc.get("branches") or []
        },
        "dose_change_branch_differs": (
            finals.get("intervention_a") != finals.get("intervention_a_dose_change")
            if finals
            else False
        ),
    }
    _write(out / "branch-comparison.json", compare)
    _write(
        out / "checkpoint-fork-rollback-report.json",
        {
            "checkpoints": sim_doc.get("checkpoints"),
            "fork": sim_doc.get("fork"),
            "rollback": sim_doc.get("rollback"),
            "isolation": sim_doc.get("isolation"),
        },
    )
    rollback = sim_doc.get("rollback") or {}
    fork = sim_doc.get("fork") or {}
    checkpoints = sim_doc.get("checkpoints") or []
    control_branch = next(
        (
            branch
            for branch in sim_doc.get("branches") or []
            if branch.get("branch_id") == "control"
        ),
        {},
    )
    checkpoint_phase_explicit = (
        bool(checkpoints)
        and all(checkpoint.get("phase") == CHECKPOINT_PHASE for checkpoint in checkpoints)
        and sim_doc.get("checkpoint_phase") == CHECKPOINT_PHASE
    )
    rollback_checkpoint_week = rollback.get("checkpoint_week")
    rollback_start_week = rollback.get("continuation_start_week")
    rollback_history_weeks = rollback.get("history_weeks") or []
    fork_checkpoint_week = fork.get("checkpoint_week")
    fork_start_week = fork.get("continuation_start_week")
    fork_history_weeks = fork.get("history_weeks") or []
    fork_event = fork.get("fork_event") or {}
    simulation_step_weeks = int(sim_doc.get("step_weeks") or 1)
    rollback_restores_checkpoint_exactly = (
        bool(rollback.get("expected_checkpoint_hash"))
        and rollback.get("restored_hash") == rollback.get("expected_checkpoint_hash")
        and rollback.get("rollback_restores_checkpoint_exactly") is True
    )
    rollback_continuation_starts_after_checkpoint = (
        isinstance(rollback_checkpoint_week, int)
        and rollback_start_week == rollback_checkpoint_week + simulation_step_weeks
        and rollback_history_weeks[:1] == [rollback_start_week]
        and rollback.get("rollback_continuation_starts_after_checkpoint") is True
    )
    rollback_reproduces_original_final_state = (
        bool(control_branch.get("final_state_hash"))
        and rollback.get("resimulated_final_state_hash")
        == rollback.get("original_final_state_hash")
        == control_branch.get("final_state_hash")
        and rollback.get("rollback_reproduces_original_final_state") is True
    )
    rollback_history_has_no_duplicate_checkpoint_week = (
        isinstance(rollback_checkpoint_week, int)
        and rollback_checkpoint_week not in rollback_history_weeks
        and len(rollback_history_weeks) == len(set(rollback_history_weeks))
        and rollback.get("rollback_history_has_no_duplicate_checkpoint_week") is True
    )
    fork_continuation_starts_after_checkpoint = (
        isinstance(fork_checkpoint_week, int)
        and fork_start_week == fork_checkpoint_week + simulation_step_weeks
        and fork_history_weeks[:1] == [fork_start_week]
        and fork.get("fork_continuation_starts_after_checkpoint") is True
    )
    fork_event_time_explicit = (
        isinstance(fork_event.get("week"), int)
        and isinstance(fork_start_week, int)
        and fork_event["week"] >= fork_start_week
        and fork.get("fork_event_time_explicit") is True
    )
    fork_has_no_duplicate_transition = (
        isinstance(fork_checkpoint_week, int)
        and fork_checkpoint_week not in fork_history_weeks
        and len(fork_history_weeks) == len(set(fork_history_weeks))
        and fork.get("fork_has_no_duplicate_transition") is True
    )
    source_branch_unchanged_after_fork = (
        bool(control_branch.get("final_state_hash"))
        and fork.get("source_branch_final_hash") == control_branch.get("final_state_hash")
        and fork.get("source_branch_unchanged_after_fork") is True
    )
    fork_effect = fork.get("fork_effect") or {}
    fork_final_state_diff_explained_by_fork_event = (
        fork_event_time_explicit
        and fork_event.get("type") == "dose_change"
        and fork_effect.get("fork_final_state_diff_explained_by_fork_event") is True
        and fork.get("fork_final_state_diff_explained_by_fork_event") is True
        and bool(fork_effect.get("changed_variables"))
        and fork_effect.get("counterfactual_final_state_hash")
        != fork_effect.get("event_fork_final_state_hash")
    )
    parent_isolation = fork.get("parent_isolation") or {}
    fork_isolation_verified = parent_isolation.get("fork_isolation_verified") is True
    rollback_fork_checks = {
        "checkpoint_phase_explicit": checkpoint_phase_explicit,
        "rollback_restores_checkpoint_exactly": rollback_restores_checkpoint_exactly,
        "rollback_continuation_starts_after_checkpoint": (
            rollback_continuation_starts_after_checkpoint
        ),
        "rollback_reproduces_original_final_state": rollback_reproduces_original_final_state,
        "rollback_history_has_no_duplicate_checkpoint_week": (
            rollback_history_has_no_duplicate_checkpoint_week
        ),
        "fork_continuation_starts_after_checkpoint": fork_continuation_starts_after_checkpoint,
        "fork_event_time_explicit": fork_event_time_explicit,
        "fork_has_no_duplicate_transition": fork_has_no_duplicate_transition,
        "source_branch_unchanged_after_fork": source_branch_unchanged_after_fork,
        "fork_final_state_diff_explained_by_fork_event": (
            fork_final_state_diff_explained_by_fork_event
        ),
        "fork_isolation_verified": fork_isolation_verified,
        "parent_state_unchanged_after_fork": parent_isolation.get(
            "parent_state_unchanged_after_fork"
        )
        is True,
        "parent_history_unchanged_after_fork": parent_isolation.get(
            "parent_history_unchanged_after_fork"
        )
        is True,
        "parent_events_unchanged_after_fork": parent_isolation.get(
            "parent_events_unchanged_after_fork"
        )
        is True,
        "parent_recomputed_hash_matches_stored_hash": parent_isolation.get(
            "parent_recomputed_hash_matches_stored_hash"
        )
        is True,
    }
    _write(
        out / "rollback-fork-verification.json",
        {
            "checkpoint_phase": CHECKPOINT_PHASE,
            "checkpoints": checkpoints,
            "fork": fork,
            "rollback": rollback,
            "checks": rollback_fork_checks,
            "status": "PASS" if all(rollback_fork_checks.values()) else "FAIL",
        },
    )
    _write(out / "determinism-report.json", determinism)
    _write(out / "model-registry.json", sim_doc.get("models") or {})
    _write(
        out / "scientific-boundary.md",
        f"""# Scientific boundary — Core Vertical Slice v{CORE_SLICE_VERSION}

- Clinical validation: NOT_STARTED
- Production readiness: NOT_CLAIMED
- SyntheticInterventionTestModel: CLINICAL_USE=PROHIBITED
- HeuristicDriftBaselineModel: heuristic only; not fitted to longitudinal observations; not causal
- PersistenceBaselineModel: technical control only
- No evidence-backed intervention-response model in this changeset
- Forbidden claims for this slice: validated, causal, physiological prediction, digital twin
- Cohort sample class: TECHNICAL_COVERAGE_BIASED_SAMPLE — must not be used for model quality evaluation
""",
    )
    _write(
        out / "model-limitations.md",
        f"""# Model limitations v{CORE_SLICE_VERSION}

See scientific-boundary.md. Heuristic drift is not an empirical longitudinal fit.
""",
    )

    # Update cohort scope with actuals
    scope_final = {
        **cohort_scope,
        "timelines_built_subjects": len(timeline_subjects),
        "snapshots_built_subjects": len(snapshot_subjects),
        "simulated_subjects": len(simulated_subjects),
        "honesty_note": (
            f"Loaded {len(patient_ids)} subjects; built timelines for "
            f"{len(timeline_subjects)}; snapshots for {len(snapshot_subjects)}; "
            f"simulated {len(simulated_subjects)} subject(s) only."
        ),
    }
    _write(out / "cohort-scope-report.json", {**scope_final, "eligibility": eligibility})

    typed_value_xor_violations = sum(
        result["typed_value_xor_violations"] for result in snapshot_contract_results
    )
    component_provenance_invalid = sum(
        result["component_provenance_invalid"] for result in snapshot_contract_results
    )
    unresolved_input_references = sum(
        result["unresolved_input_references"] for result in snapshot_contract_results
    )
    snapshot_provenance_invalid = sum(
        not result["snapshot_provenance_ok"] for result in snapshot_contract_results
    )
    derived_records_with_fake_source_locator = 0
    for snapshot_document in snapshot_documents:
        provenances = [snapshot_document.get("provenance")] + [
            component.get("provenance")
            for component in snapshot_document.get("components") or []
        ]
        derived_records_with_fake_source_locator += sum(
            isinstance(provenance, dict)
            and provenance.get("source_record_locator") is not None
            for provenance in provenances
        )
    snapshot_contract_verification = {
        "snapshots_evaluated": len(snapshot_contract_results),
        "typed_value_xor_violations": typed_value_xor_violations,
        "snapshot_provenance_invalid": snapshot_provenance_invalid,
        "component_provenance_invalid": component_provenance_invalid,
        "unresolved_input_references": unresolved_input_references,
        "derived_records_with_fake_source_locator": derived_records_with_fake_source_locator,
        "results": snapshot_contract_results,
    }
    snapshot_contract_verification["status"] = (
        "PASS"
        if snapshot_contract_results
        and typed_value_xor_violations == 0
        and snapshot_provenance_invalid == 0
        and component_provenance_invalid == 0
        and unresolved_input_references == 0
        and derived_records_with_fake_source_locator == 0
        else "FAIL"
    )
    _write(out / "snapshot-contract-verification.json", snapshot_contract_verification)
    _write(
        out / "reproducibility-verification.json",
        {
            "status": "PENDING_PUBLICATION",
            "note": "Filled by the publication workflow after clean-extraction verification.",
        },
    )
    _write(
        out / "publication-scan.json",
        {
            "status": "PENDING",
            "note": "Filled by the publication workflow.",
        },
    )

    pii_scan = _scan_artifacts_for_pii(out)

    # --- Computed verification (no hard-coded PASS) ---
    def _status(ok: bool | None) -> str:
        if ok is None:
            return "NOT_EVALUATED"
        return "PASS" if ok else "FAIL"

    fork_ok = bool(fork.get("ok")) and bool(fork.get("fork_start_state_hash_verified"))
    rollback_ok = bool(rollback.get("ok")) and bool(rollback.get("hash_match_after_rollback"))
    iso = sim_doc.get("isolation") or {}
    isolation_ok = all(
        [
            iso.get("control_recompute_matches") is True,
            iso.get("control_differs_from_intervention") is True,
            iso.get("dose_change_differs_from_intervention") is True,
        ]
    ) if iso else False

    checks: dict[str, dict[str, Any]] = {
        "source_a_readable": {
            "status": _status(bool(access.get("readable"))),
            "evidence": access,
        },
        "canonical_writable_load": {
            "status": _status(
                load_report["write_error_count"] == 0
                and load_report["canonical_row_counts"].get("subject", 0) >= len(patient_ids)
            ),
            "evidence": {
                "write_error_count": load_report["write_error_count"],
                "subject_rows": load_report["canonical_row_counts"].get("subject"),
                "subjects_attempted": load_report["subjects_attempted"],
            },
        },
        "extraction_ok": {"status": _status(len(patient_ids) > 0), "evidence": {"n": len(patient_ids)}},
        "provenance_present": {
            "status": _status(provenance_coverage["full_coverage"]),
            "evidence": provenance_coverage,
        },
        "source_record_coverage": {
            "status": _status(load_report["source_record_coverage"].get("every_evidence_has_source_record")),
            "evidence": load_report["source_record_coverage"],
        },
        "timeline_built": {
            "status": _status(len(timelines) == len(timeline_subjects) and len(timelines) > 0),
            "evidence": {"built": len(timelines), "cap": TIMELINE_SUBJECT_LIMIT},
        },
        "starting_state_built": {
            "status": _status(
                len(snapshots) > 0
                and all(s["has_required_fields"] and s["components_have_input_refs"] for s in snapshots)
            ),
            "evidence": {"built": len(snapshots)},
        },
        "temporal_no_future_leakage": {
            "status": _status((leakage.get("synthetic_future_injection") or {}).get("pass")),
            "evidence": leakage.get("synthetic_future_injection"),
        },
        "three_branches": {
            "status": _status(len(sim_doc.get("branches") or []) == 3),
            "evidence": {"n": len(sim_doc.get("branches") or [])},
        },
        "baseline_ran": {
            "status": _status("persistence" in (sim_doc.get("models") or {})),
            "evidence": list((sim_doc.get("models") or {}).keys()),
        },
        "synthetic_ran": {
            "status": _status("synthetic" in (sim_doc.get("models") or {})),
            "evidence": list((sim_doc.get("models") or {}).keys()),
        },
        "dose_change_isolated": {
            "status": _status(bool(compare.get("dose_change_branch_differs"))),
            "evidence": compare.get("final_state_hashes"),
        },
        "checkpoint_ok": {
            "status": _status(bool(sim_doc.get("checkpoints")) and all("state_hash" in c for c in (sim_doc.get("checkpoints") or []))),
            "evidence": {"n": len(sim_doc.get("checkpoints") or [])},
        },
        "fork_ok": {"status": _status(fork_ok), "evidence": sim_doc.get("fork")},
        "rollback_ok": {"status": _status(rollback_ok), "evidence": sim_doc.get("rollback")},
        **{
            name: {
                "status": _status(value),
                "evidence": (
                    {"checkpoint_phase": CHECKPOINT_PHASE, "checkpoints": checkpoints}
                    if name == "checkpoint_phase_explicit"
                    else rollback
                    if name.startswith("rollback_")
                    else fork
                ),
            }
            for name, value in rollback_fork_checks.items()
        },
        "state_snapshot_component_typed_value_xor": {
            "status": _status(
                bool(snapshot_contract_results) and typed_value_xor_violations == 0
            ),
            "evidence": snapshot_contract_verification,
        },
        "snapshot_provenance_contract_valid": {
            "status": _status(
                bool(snapshot_contract_results) and snapshot_provenance_invalid == 0
            ),
            "evidence": snapshot_contract_verification,
        },
        "snapshot_component_provenance_contract_valid": {
            "status": _status(
                bool(snapshot_contract_results) and component_provenance_invalid == 0
            ),
            "evidence": snapshot_contract_verification,
        },
        "snapshot_input_references_resolve": {
            "status": _status(
                bool(snapshot_contract_results) and unresolved_input_references == 0
            ),
            "evidence": snapshot_contract_verification,
        },
        "derived_records_have_no_fake_source_locator": {
            "status": _status(
                bool(snapshot_contract_results)
                and derived_records_with_fake_source_locator == 0
            ),
            "evidence": snapshot_contract_verification,
        },
        "branch_isolation": {"status": _status(isolation_ok), "evidence": iso},
        "uncertainty_present": {
            "status": _status(bool(sim_doc.get("uncertainty_present_computed"))),
            "evidence": {"computed": sim_doc.get("uncertainty_present_computed")},
        },
        "idempotent_reload": {"status": _status(bool(idem.get("idempotent"))), "evidence": idem},
        "rejects_handled": {
            "status": _status(
                isinstance(load_report.get("reject_categories"), list)
                and all("count" in c and "denominator" in c for c in load_report["reject_categories"])
            ),
            "evidence": {"reject_count": load_report["reject_count"]},
        },
        "truncation_accounted": {
            "status": _status(
                "document_analysisresult" in (load_report.get("truncation") or {}).get("relations", {})
            ),
            "evidence": load_report.get("truncation"),
        },
        "pii_excluded_from_artifacts": {
            "status": _status(pii_scan["ok"]),
            "evidence": pii_scan,
        },
        "scope_honesty": {
            "status": _status(
                scope_final["simulated_subjects"] == SIMULATED_SUBJECT_LIMIT
                and scope_final["cohort_loaded_subjects"] == len(patient_ids)
                and scope_final["simulated_subjects"] <= scope_final["cohort_loaded_subjects"]
            ),
            "evidence": scope_final,
        },
        "determinism_in_process": {
            "status": _status(bool(determinism.get("pass"))),
            "evidence": determinism.get("in_process_repeat"),
        },
        "security_findings_non_blocking": {
            "status": _status(policy_snapshot()["security_blocks_core"] is False),
            "evidence": {"security_blocks_core": policy_snapshot()["security_blocks_core"]},
        },
    }

    # Guard: do not imply all 100 simulated
    if scope_final["simulated_subjects"] == scope_final["cohort_loaded_subjects"] and scope_final[
        "cohort_loaded_subjects"
    ] > SIMULATED_SUBJECT_LIMIT:
        checks["scope_honesty"]["status"] = "FAIL"

    # Every check must pass; all other outcomes remain a correctness-open partial.
    statuses = [check["status"] for check in checks.values()]
    overall = (
        "TECHNICAL_VERTICAL_SLICE_PASS"
        if all(status == "PASS" for status in statuses)
        else "PARTIAL"
    )
    failed_checks = sorted(name for name, check in checks.items() if check["status"] != "PASS")
    technical_status = (
        "TECHNICAL_VERTICAL_SLICE_PASS"
        if overall == "TECHNICAL_VERTICAL_SLICE_PASS"
        else "CORRECTNESS_FINDINGS_OPEN"
    )
    report_status = "FINAL" if overall == "TECHNICAL_VERTICAL_SLICE_PASS" else "DRAFT"
    verification = {
        "core_vertical_slice_status": overall,
        "technical_vertical_slice_status": technical_status,
        "failed_checks": failed_checks,
        "report_status": report_status,
        "core_slice_version": CORE_SLICE_VERSION,
        "checks": {k: v["status"] for k, v in checks.items()},
        "check_details": checks,
        "policy": policy_snapshot(),
        "scope": scope_final,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "canonical_row_counts": counts_final,
    }
    _write(out / "core-verification.json", verification)
    _write(
        out / "core-report.md",
        f"""# Core Engine Vertical Slice v{CORE_SLICE_VERSION}

**Status:** {overall}
**Technical vertical slice status:** {technical_status}
**Report status:** {report_status}

## Scope (honest)

- cohort_loaded_subjects: {scope_final['cohort_loaded_subjects']}
- timelines_built_subjects: {scope_final['timelines_built_subjects']}
- snapshots_built_subjects: {scope_final['snapshots_built_subjects']}
- simulated_subjects: {scope_final['simulated_subjects']}
- sample_class: {COHORT_SAMPLE_CLASS}

## Checks

{chr(10).join(f"- {k}: {v['status']}" for k, v in checks.items())}

## Failed checks

{chr(10).join(f"- {name}" for name in failed_checks) if failed_checks else "- none"}

## Scientific boundary

Clinical validation NOT_STARTED. Production readiness NOT_CLAIMED.
No causal / validated / digital-twin claims.
""",
    )

    # Manifest must not hash itself
    names = sorted(
        p.name for p in out.iterdir() if p.is_file() and p.name != "manifest.sha256"
    )
    lines = [f"{_sha_file(out / n)}  {n}" for n in names]
    (out / "manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return verification
