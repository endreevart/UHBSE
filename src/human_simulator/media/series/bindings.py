"""Bind every on-screen number to a frozen evidence artifact. No database I/O."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.media.series.constants import (
    CORE_DIR,
    CORE_ZIP_NAME,
    CORE_ZIP_SHA256,
    EPISODES,
    EVIDENCE_DIR,
    HASH_PREFIX_LEN,
    PRIOR_V012_DIR,
    SDR_DIR,
    SERIES_TITLE,
    _TRUNCATION_RELATION,
    _VOLUME_RELATION,
)
from human_simulator.media.series.rounding import ROUNDERS, hash_prefix

SchemaError = ValueError


def _load(root: Path, rel: Path) -> dict[str, Any]:
    path = root / rel
    if not path.is_file():
        raise SchemaError(f"missing evidence artifact: {rel}")
    return json.loads(path.read_text(encoding="utf-8"))


def _volume(doc: dict[str, Any], role: str) -> int:
    key = _VOLUME_RELATION[role]
    return int(doc["relation_counts"][key])


def _trunc(doc: dict[str, Any], role: str, field: str) -> int:
    key = _TRUNCATION_RELATION[role]
    return int(doc["truncation"]["relations"][key][field])


def _reject(doc: dict[str, Any], category: str) -> int:
    for row in doc["categories"]:
        if row["category"] == category:
            return int(row["count"])
    raise SchemaError(f"reject category missing: {category}")


def _pytest_row(doc: dict[str, Any]) -> dict[str, Any]:
    for command in doc.get("commands") or []:
        if "pytest" in str(command.get("literal_command") or "") and command.get("passed") is not None:
            return command
    raise SchemaError("pytest command missing from reproducibility-verification.json")


def build_bindings(root: Path) -> dict[str, Any]:
    core = CORE_DIR
    access = _load(root, core / "source-a-access-report.json")
    eligibility = _load(root, PRIOR_V012_DIR / "cohort-scope-report.json")["eligibility"]
    scope = _load(root, core / "cohort-scope-report.json")
    load = _load(root, core / "canonical-load-report.json")
    counts = _load(root, core / "canonical-row-counts-before-after.json")["after_v0121"]
    reject = _load(root, core / "reject-report.json")
    prov = _load(root, core / "provenance-coverage.json")["database_provenance_coverage"]
    timeline = _load(root, core / "timeline-summary.json")
    fork = _load(root, core / "checkpoint-fork-rollback-report.json")
    verify = _load(root, core / "core-verification.json")
    repro = _load(root, core / "reproducibility-verification.json")
    models = _load(root, core / "model-registry.json")
    leakage = _load(root, core / "temporal-leakage-verification.json")
    pytest_row = _pytest_row(repro)
    sdr_ver = _load(root, SDR_DIR / "scientific-data-readiness-verification.json")
    sdr_ds = _load(root, SDR_DIR / "longitudinal-dataset-summary.json")

    fork_body = fork["fork"]
    rollback = fork["rollback"]
    effect = fork_body["fork_effect"]
    isolation = fork_body["parent_isolation"]
    checkpoint_hash = str(fork_body["fork_start_state_hash"])
    cf_hash = str(effect["counterfactual_final_state_hash"])
    ev_hash = str(effect["event_fork_final_state_hash"])
    rb_hash = str(rollback["resimulated_final_state_hash"])
    orig_hash = str(rollback["original_final_state_hash"])

    bindings: list[dict[str, Any]] = []

    def add(
        *,
        binding_id: str,
        episode: str,
        source_artifact: str,
        json_path: str,
        exact: Any,
        rounding: str,
        disclosure: str,
        display: Any | None = None,
        owner_review: bool = False,
        public: bool = True,
        capability: str = "WORKING_NOW",
        notes: str = "",
    ) -> None:
        displayed = ROUNDERS[rounding](exact) if rounding in ROUNDERS and rounding != "none" else display
        if rounding == "hash_prefix":
            displayed = hash_prefix(str(exact), HASH_PREFIX_LEN)
            exact = {"kind": "sha256", "length": 64, "prefix": displayed}
        bindings.append(
            {
                "binding_id": binding_id,
                "episode": episode,
                "source_artifact": source_artifact,
                "json_path": json_path,
                "source_exact_value": exact,
                "displayed_public_value": displayed,
                "rounding_rule": rounding,
                "disclosure_category": disclosure,
                "disclosure_status": "OWNER_REVIEW_REQUIRED" if owner_review else "PUBLIC",
                "public_display": public,
                "capability_status": capability,
                "notes": notes,
            }
        )

    v012_scope = str(PRIOR_V012_DIR / "cohort-scope-report.json")
    access_path = str(core / "source-a-access-report.json")
    load_path = str(core / "canonical-load-report.json")
    reject_path = str(core / "reject-report.json")
    counts_path = str(core / "canonical-row-counts-before-after.json")
    scope_path = str(core / "cohort-scope-report.json")
    prov_path = str(core / "provenance-coverage.json")
    tl_path = str(core / "timeline-summary.json")
    fork_path = str(core / "checkpoint-fork-rollback-report.json")
    verify_path = str(core / "core-verification.json")
    repro_path = str(core / "reproducibility-verification.json")
    leak_path = str(core / "temporal-leakage-verification.json")
    model_path = str(core / "model-registry.json")

    add(
        binding_id="subjects_entered",
        episode="Roadmap01",
        source_artifact=v012_scope,
        json_path="eligibility.subjects_total",
        exact=int(eligibility["subjects_total"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
        notes="Carried from accepted v0.1.2 cohort eligibility; v0.1.2.1 did not re-read clinical rows.",
    )
    add(
        binding_id="subjects_appt_ge3",
        episode="Roadmap01",
        source_artifact=v012_scope,
        json_path="eligibility.subjects_appt_ge3",
        exact=int(eligibility["subjects_appt_ge3"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
        notes="Carried from accepted v0.1.2 cohort eligibility.",
    )
    add(
        binding_id="subjects_appt3_and_lab",
        episode="Roadmap01",
        source_artifact=v012_scope,
        json_path="eligibility.subjects_appt3_and_lab",
        exact=int(eligibility["subjects_appt3_and_lab"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
        notes="Carried from accepted v0.1.2 cohort eligibility.",
    )
    add(
        binding_id="bounded_cohort",
        episode="Roadmap01",
        source_artifact=scope_path,
        json_path="cohort_loaded_subjects",
        exact=int(scope["cohort_loaded_subjects"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="appointments_volume",
        episode="Roadmap01",
        source_artifact=access_path,
        json_path="relation_counts.<pilot_appointments_aggregate>",
        exact=_volume(access, "appointments"),
        rounding="round_thousands_1_decimal",
        disclosure="PUBLIC_FACT",
        notes="Underlying relation name omitted from public display.",
    )
    add(
        binding_id="laboratory_records_volume",
        episode="Roadmap01",
        source_artifact=access_path,
        json_path="relation_counts.<pilot_laboratory_aggregate>",
        exact=_volume(access, "laboratory_records"),
        rounding="round_thousands",
        disclosure="PUBLIC_FACT",
        notes="Underlying relation name omitted from public display.",
    )
    add(
        binding_id="result_items_volume",
        episode="Roadmap01",
        source_artifact=access_path,
        json_path="relation_counts.<pilot_result_item_aggregate>",
        exact=_volume(access, "result_items"),
        rounding="round_millions_2",
        disclosure="PUBLIC_FACT",
        notes="Underlying relation name omitted from public display.",
    )
    add(
        binding_id="lab_records_available",
        episode="Roadmap02",
        source_artifact=load_path,
        json_path="truncation.relations.<laboratory_records>.available_rows",
        exact=_trunc(load, "laboratory_records", "available_rows"),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="lab_records_selected",
        episode="Roadmap02",
        source_artifact=load_path,
        json_path="truncation.relations.<laboratory_records>.selected_rows",
        exact=_trunc(load, "laboratory_records", "selected_rows"),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="result_items_available",
        episode="Roadmap02",
        source_artifact=load_path,
        json_path="truncation.relations.<result_items>.available_rows",
        exact=_trunc(load, "result_items", "available_rows"),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="result_items_selected",
        episode="Roadmap02",
        source_artifact=load_path,
        json_path="truncation.relations.<result_items>.selected_rows",
        exact=_trunc(load, "result_items", "selected_rows"),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="valid_components",
        episode="Roadmap02",
        source_artifact=counts_path,
        json_path="after_v0121.observation_component",
        exact=int(counts["observation_component"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="reject_missing_source",
        episode="Roadmap02",
        source_artifact=reject_path,
        json_path="categories[MISSING_SOURCE_VALUE].count",
        exact=_reject(reject, "MISSING_SOURCE_VALUE"),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="reject_invalid_numeric",
        episode="Roadmap02",
        source_artifact=reject_path,
        json_path="categories[INVALID_NUMERIC_REPRESENTATION].count",
        exact=_reject(reject, "INVALID_NUMERIC_REPRESENTATION"),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="source_record",
        episode="Roadmap03",
        source_artifact=counts_path,
        json_path="after_v0121.source_record",
        exact=int(counts["source_record"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="subject",
        episode="Roadmap03",
        source_artifact=counts_path,
        json_path="after_v0121.subject",
        exact=int(counts["subject"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="subject_characteristic",
        episode="Roadmap03",
        source_artifact=counts_path,
        json_path="after_v0121.subject_characteristic",
        exact=int(counts["subject_characteristic"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="encounter",
        episode="Roadmap03",
        source_artifact=counts_path,
        json_path="after_v0121.encounter",
        exact=int(counts["encounter"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="observation",
        episode="Roadmap03",
        source_artifact=counts_path,
        json_path="after_v0121.observation",
        exact=int(counts["observation"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="observation_component",
        episode="Roadmap03",
        source_artifact=counts_path,
        json_path="after_v0121.observation_component",
        exact=int(counts["observation_component"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="provenance_valid",
        episode="Roadmap03",
        source_artifact=prov_path,
        json_path="database_provenance_coverage.valid_records",
        exact=int(prov["valid_records"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="timelines",
        episode="Roadmap03",
        source_artifact=scope_path,
        json_path="timelines_built_subjects",
        exact=int(scope["timelines_built_subjects"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="timeline_events",
        episode="Roadmap03",
        source_artifact=tl_path,
        json_path="total_events",
        exact=int(timeline["total_events"]),
        rounding="thousands_sep",
        disclosure="PUBLIC_FACT",
        notes="On-screen count is the verified timeline-summary total_events (598), not an unbound 695.",
    )
    add(
        binding_id="snapshots",
        episode="Roadmap03",
        source_artifact=scope_path,
        json_path="snapshots_built_subjects",
        exact=int(scope["snapshots_built_subjects"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="checkpoint_week",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.checkpoint_week",
        exact=int(fork_body["checkpoint_week"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="event_week",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.fork_effect.event_week",
        exact=int(effect["event_week"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="first_divergence_week",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.fork_effect.first_divergence_week",
        exact=int(effect["first_divergence_week"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="changed_variables",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.fork_effect.changed_variables.length",
        exact=len(effect["changed_variables"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="same_checkpoint_hash",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.fork_effect.both_started_from_same_checkpoint_hash",
        exact=bool(effect["both_started_from_same_checkpoint_hash"]),
        rounding="none",
        display="same checkpoint hash",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="final_hashes_differ",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.fork_effect.final_hashes_differ",
        exact=bool(effect["final_hashes_differ"]),
        rounding="none",
        display="different final state hashes",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="parent_state_unchanged",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.parent_isolation.parent_state_unchanged_after_fork",
        exact=bool(isolation["parent_state_unchanged_after_fork"]),
        rounding="none",
        display="parent state unchanged",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="parent_history_unchanged",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.parent_isolation.parent_history_unchanged_after_fork",
        exact=bool(isolation["parent_history_unchanged_after_fork"]),
        rounding="none",
        display="parent history unchanged",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="parent_events_unchanged",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.parent_isolation.parent_events_unchanged_after_fork",
        exact=bool(isolation["parent_events_unchanged_after_fork"]),
        rounding="none",
        display="parent events unchanged",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="rollback_reproduces",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="rollback.rollback_reproduces_original_final_state",
        exact=bool(rollback["rollback_reproduces_original_final_state"]),
        rounding="none",
        display="ROLLBACK FINAL HASH = ORIGINAL FINAL HASH",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="checkpoint_hash_prefix",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.fork_start_state_hash",
        exact=checkpoint_hash,
        rounding="hash_prefix",
        disclosure="PUBLIC_FACT",
        notes="Full digest remains in the frozen core artifact; only the prefix is public.",
    )
    add(
        binding_id="counterfactual_hash_prefix",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.fork_effect.counterfactual_final_state_hash",
        exact=cf_hash,
        rounding="hash_prefix",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="event_fork_hash_prefix",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="fork.fork_effect.event_fork_final_state_hash",
        exact=ev_hash,
        rounding="hash_prefix",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="rollback_hash_prefix",
        episode="Roadmap04",
        source_artifact=fork_path,
        json_path="rollback.resimulated_final_state_hash",
        exact=rb_hash,
        rounding="hash_prefix",
        disclosure="PUBLIC_FACT",
    )
    if hash_prefix(orig_hash) != hash_prefix(rb_hash):
        raise SchemaError("rollback hash does not match original final hash")
    add(
        binding_id="clean_room_tests",
        episode="Roadmap05",
        source_artifact=repro_path,
        json_path="commands[pytest].passed",
        exact=int(pytest_row["passed"]),
        rounding="exact_int",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="future_leakage_excluded",
        episode="Roadmap05",
        source_artifact=leak_path,
        json_path="synthetic_future_injection.pass",
        exact=bool(leakage["synthetic_future_injection"]["pass"]),
        rounding="none",
        display="future-data leakage rejected",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="technical_core_status",
        episode="Roadmap05",
        source_artifact=verify_path,
        json_path="technical_vertical_slice_status",
        exact=str(verify["technical_vertical_slice_status"]),
        rounding="none",
        display="TECHNICAL CORE — VERIFIED",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="clinical_validation_status",
        episode="Roadmap05",
        source_artifact=verify_path,
        json_path="policy.clinical_validation_status",
        exact=str(verify["policy"]["clinical_validation_status"]),
        rounding="none",
        display="CLINICAL VALIDATION — NOT STARTED",
        disclosure="PUBLIC_FACT",
        capability="NOT_STARTED",
    )
    persistence_mae = float(sdr_ver["primary_metric_test"]["subject_macro_mae"]["persistence"])
    trend_mae = float(sdr_ver["primary_metric_test"]["subject_macro_mae"]["empirical_trend"])
    learned_mae = float(sdr_ver["primary_metric_test"]["subject_macro_mae"]["first_learned"])
    add(
        binding_id="persistence_model",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="primary_metric_test.subject_macro_mae.persistence",
        exact=persistence_mae,
        rounding="none",
        display="Persistence baseline",
        disclosure="PUBLIC_FACT",
        capability="WORKING_NOW",
        notes="Exploratory retrospective backtest control. Not a clinical predictor.",
    )
    add(
        binding_id="empirical_trend_model",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="primary_metric_test.subject_macro_mae.empirical_trend",
        exact=trend_mae,
        rounding="none",
        display="Empirical trend",
        disclosure="PUBLIC_FACT",
        capability="WORKING_NOW",
        notes="Exploratory retrospective backtest control. Not a clinical predictor.",
    )
    add(
        binding_id="first_learned_baseline",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="primary_metric_test.subject_macro_mae.first_learned",
        exact=learned_mae,
        rounding="none",
        display="First learned Ridge baseline",
        disclosure="PUBLIC_FACT",
        capability="WORKING_NOW",
        notes="Lower test MAE than persistence; n_test_subjects=2 so no incremental signal claimed.",
    )
    add(
        binding_id="sdr_n_subjects_with_pairs",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "longitudinal-dataset-summary.json"),
        json_path="n_subjects_with_pairs",
        exact=int(sdr_ds["n_subjects_with_pairs"]),
        rounding="none",
        display=str(int(sdr_ds["n_subjects_with_pairs"])),
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="sdr_n_consecutive_pairs",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "longitudinal-dataset-summary.json"),
        json_path="n_pairs",
        exact=int(sdr_ds["n_pairs"]),
        rounding="none",
        display=str(int(sdr_ds["n_pairs"])),
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="sdr_test_subjects",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="split_subjects.test",
        exact=int(sdr_ver["split_subjects"]["test"]),
        rounding="none",
        display=str(int(sdr_ver["split_subjects"]["test"])),
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="sdr_test_pairs",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="split_counts.test",
        exact=int(sdr_ver["split_counts"]["test"]),
        rounding="none",
        display=str(int(sdr_ver["split_counts"]["test"])),
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="metric_persistence_mae",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="primary_metric_test.subject_macro_mae.persistence",
        exact=persistence_mae,
        rounding="none",
        display=f"{persistence_mae:.3f}",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="metric_learned_mae",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="primary_metric_test.subject_macro_mae.first_learned",
        exact=learned_mae,
        rounding="none",
        display=f"{learned_mae:.3f}",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="incremental_signal_status",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="incremental_signal_status",
        exact=str(sdr_ver["incremental_signal_status"]),
        rounding="none",
        display="NO INCREMENTAL SIGNAL CLAIMED",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="uncertainty_calibration_status",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="uncertainty_calibration_status",
        exact=str(sdr_ver["uncertainty_calibration_status"]),
        rounding="none",
        display="INSUFFICIENT DATA",
        disclosure="PUBLIC_FACT",
    )
    add(
        binding_id="sdr_clinical_validation",
        episode="Roadmap06",
        source_artifact=str(SDR_DIR / "scientific-data-readiness-verification.json"),
        json_path="clinical_validation_status",
        exact=str(sdr_ver["clinical_validation_status"]),
        rounding="none",
        display="CLINICAL VALIDATION: NOT STARTED",
        disclosure="PUBLIC_FACT",
        capability="NOT_STARTED",
    )

    controlled = [
        ("pipeline_source_to_snapshot", "SourceRecord → Canonical Model → EvidenceStateSnapshot"),
        ("state_construction", "state construction (encounters, laboratory observations, temporal order, source references)"),
        ("observed_computed_synthetic", "OBSERVED / COMPUTED / SYNTHETIC layers"),
        ("checkpoint_fork_rollback", "checkpoint / fork / rollback protocol"),
        ("counterfactual_comparison", "comparison of counterfactual continuations"),
        ("provenance_contract", "provenance contract behaviour"),
        ("model_interface_categories", "model interface categories"),
        ("retrospective_backtest_design", "completed exploratory retrospective backtest"),
        ("negative_control_philosophy", "negative-control philosophy"),
    ]
    for cid, label in controlled:
        add(
            binding_id=cid,
            episode="series",
            source_artifact=verify_path,
            json_path="core_vertical_slice_status",
            exact=str(verify["core_vertical_slice_status"]),
            rounding="none",
            display=label,
            disclosure="CONTROLLED_COMMERCIAL_REVEAL",
            owner_review=True,
            public=True,
        )

    by_id = {row["binding_id"]: row["displayed_public_value"] for row in bindings}
    return {
        "schema": "uhbse.public.evidence.bindings.v1",
        "series_title": SERIES_TITLE,
        "technical_baseline_zip": CORE_ZIP_NAME,
        "technical_baseline_sha256": CORE_ZIP_SHA256,
        "scientific_baseline_dir": str(SDR_DIR),
        "bindings": bindings,
        "displayed": by_id,
        "episodes": [
            {
                "id": episode["id"],
                "slug": episode["slug"],
                "filename": episode["filename"],
                "title": episode["title"],
                "duration_frames": episode["duration_frames"],
                "capability_status": episode["capability_status"],
                "cover_headline": episode["cover_headline"],
            }
            for episode in EPISODES
        ],
    }


def write_bindings(root: Path) -> Path:
    doc = build_bindings(root)
    out = root / EVIDENCE_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / "public-evidence-bindings.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
