"""Public Remotion fixture: display values only. No subject ids, hashes, SQL, or table names."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.media.series.constants import (
    EVIDENCE_DIR,
    FPS,
    HEIGHT,
    SERIES_TITLE,
    WIDTH,
)

DISCLAIMERS = {
    "Roadmap01": "Aggregated counts from one connected pilot source. No patient record is displayed.",
    "Roadmap02": "Aggregated counts from one connected pilot source. No patient record is displayed.",
    "Roadmap03": "SYNTHETIC_COMPOSITE timeline. No real subject and no laboratory values are shown.",
    "Roadmap04": "Technical synthetic intervention test. No biological or clinical effect is claimed.",
    "Roadmap05": "Technical core tests. Clinical validation has not started.",
    "Roadmap06": "Exploratory retrospective backtest complete. No incremental signal claimed. Clinical validation not started.",
}


def _d(bindings: dict[str, Any], key: str) -> str:
    return str(bindings["displayed"][key])


def build_fixture(bindings: dict[str, Any]) -> dict[str, Any]:
    d = lambda key: _d(bindings, key)  # noqa: E731
    episodes = []
    for meta in bindings["episodes"]:
        eid = meta["id"]
        payload: dict[str, Any] = {
            **meta,
            "series_title": SERIES_TITLE,
            "disclaimer": DISCLAIMERS[eid],
            "disclosure_label": "Aggregates only · no patient record",
        }
        if eid == "Roadmap01":
            payload.update(
                {
                    "hook": [
                        f"{d('subjects_entered')} SUBJECTS ENTERED THE PIPELINE",
                        f"{d('bounded_cohort')} ENTERED THE FIRST BOUNDED TECHNICAL COHORT",
                    ],
                    "funnel": [
                        {"label": "subjects entered the pipeline", "value": d("subjects_entered")},
                        {"label": "with 3+ appointments", "value": d("subjects_appt_ge3")},
                        {"label": "with laboratory history and 3+ appointments", "value": d("subjects_appt3_and_lab")},
                        {"label": "bounded technical cohort", "value": d("bounded_cohort")},
                    ],
                    "stats": [
                        {"label": "appointments", "value": d("appointments_volume")},
                        {"label": "laboratory result records", "value": d("laboratory_records_volume")},
                        {"label": "result items", "value": d("result_items_volume")},
                    ],
                    "thesis": "DATA VOLUME IS NOT ENOUGH. LONGITUDINAL STRUCTURE IS WHAT MAKES SIMULATION TESTABLE.",
                    "captions": [
                        {"from": 0, "to": 56, "text": f"{d('subjects_entered')} subjects entered. {d('bounded_cohort')} made the first cohort."},
                        {"from": 56, "to": 140, "text": "Eligibility is longitudinal, not just a headcount."},
                        {"from": 140, "to": 208, "text": f"{d('appointments_volume')} appointments · {d('laboratory_records_volume')} lab records · {d('result_items_volume')} result items."},
                        {"from": 208, "to": 270, "text": "Volume is not enough. Longitudinal structure makes simulation testable."},
                    ],
                }
            )
        elif eid == "Roadmap02":
            payload.update(
                {
                    "hook": ["MOST OF THE WORK HAPPENS BEFORE THE MODEL."],
                    "flow": [
                        {"label": "available laboratory records", "value": d("lab_records_available")},
                        {"label": "selected for the bounded technical slice", "value": d("lab_records_selected")},
                        {"label": "available result items", "value": d("result_items_available")},
                        {"label": "selected result items", "value": d("result_items_selected")},
                        {"label": "valid canonical components", "value": d("valid_components")},
                    ],
                    "rejects": [
                        {"label": "missing source values", "value": d("reject_missing_source"), "tone": "expected"},
                        {"label": "invalid numeric representations", "value": d("reject_invalid_numeric"), "tone": "expected"},
                    ],
                    "pipeline": ["SOURCE RECORD", "SUBJECT", "ENCOUNTER", "OBSERVATION", "OBSERVATION COMPONENT"],
                    "thesis": "A CLINICAL DATABASE BECOMES MODEL-READY ONLY AFTER ITS UNCERTAINTY, MISSINGNESS AND PROVENANCE ARE MADE EXPLICIT.",
                    "captions": [
                        {"from": 0, "to": 56, "text": "Most of the work happens before the model."},
                        {"from": 56, "to": 140, "text": f"{d('lab_records_available')} available labs → {d('lab_records_selected')} selected → {d('valid_components')} valid."},
                        {"from": 140, "to": 208, "text": f"Rejects are expected: {d('reject_missing_source')} missing, {d('reject_invalid_numeric')} invalid numerics."},
                        {"from": 208, "to": 270, "text": "Uncertainty, missingness and provenance must be explicit."},
                    ],
                }
            )
        elif eid == "Roadmap03":
            payload.update(
                {
                    "hook": ["BEFORE WE SIMULATE A FUTURE, WE NEED A STATE THE COMPUTER CAN UNDERSTAND."],
                    "counts": [
                        {"label": "SourceRecord", "value": d("source_record")},
                        {"label": "Subject", "value": d("subject")},
                        {"label": "SubjectCharacteristic", "value": d("subject_characteristic")},
                        {"label": "Encounter", "value": d("encounter")},
                        {"label": "Observation", "value": d("observation")},
                        {"label": "ObservationComponent", "value": d("observation_component")},
                    ],
                    "extras": [
                        {"label": "records with valid provenance", "value": d("provenance_valid")},
                        {"label": "timelines", "value": d("timelines")},
                        {"label": "timeline events", "value": d("timeline_events")},
                        {"label": "starting-state snapshots", "value": d("snapshots")},
                    ],
                    "layers": ["OBSERVED", "COMPUTED", "SYNTHETIC"],
                    "composite_label": "SYNTHETIC_COMPOSITE",
                    "snapshot_label": "EvidenceStateSnapshot",
                    "thesis": "EVERY COMPUTED STATE MUST REMAIN TRACEABLE TO THE EVIDENCE THAT CREATED IT.",
                    "captions": [
                        {"from": 0, "to": 56, "text": "Before we simulate a future, we need a state the computer can understand."},
                        {"from": 56, "to": 140, "text": f"{d('source_record')} source records · {d('subject')} subjects · {d('provenance_valid')} with valid provenance."},
                        {"from": 140, "to": 208, "text": f"SYNTHETIC_COMPOSITE from {d('timelines')} histories and {d('timeline_events')} events."},
                        {"from": 208, "to": 270, "text": "Observed, computed and synthetic stay in separate layers."},
                    ],
                }
            )
        elif eid == "Roadmap04":
            payload.update(
                {
                    "hook": ["WE CAN NOW FORK A BIOLOGICAL STATE WITHOUT CHANGING ITS ORIGINAL HISTORY."],
                    "checkpoint_label": f"POST-STEP CHECKPOINT · WEEK {d('checkpoint_week')}",
                    "checkpoint_hash": d("checkpoint_hash_prefix"),
                    "branches": ["COUNTERFACTUAL CONTINUATION", "CONTROLLED EVENT BRANCH"],
                    "event_label": "SYNTHETIC CONTROLLED EVENT",
                    "event_week": d("event_week"),
                    "divergence_week": d("first_divergence_week"),
                    "changed_variables": d("changed_variables"),
                    "hashes": {
                        "checkpoint": d("checkpoint_hash_prefix"),
                        "counterfactual": d("counterfactual_hash_prefix"),
                        "event_fork": d("event_fork_hash_prefix"),
                        "rollback": d("rollback_hash_prefix"),
                    },
                    "isolation": [
                        "parent state unchanged",
                        "parent history unchanged",
                        "parent events unchanged",
                    ],
                    "rollback_label": "ROLLBACK FINAL HASH = ORIGINAL FINAL HASH",
                    "thesis": "SAME STARTING STATE. ONE CONTROLLED CHANGE. TWO TRACEABLE CONTINUATIONS.",
                    "captions": [
                        {"from": 0, "to": 56, "text": "Fork a biological state without changing its original history."},
                        {"from": 56, "to": 140, "text": f"Checkpoint week {d('checkpoint_week')}. Same hash {d('checkpoint_hash_prefix')}."},
                        {"from": 140, "to": 208, "text": f"Week {d('event_week')}: controlled event. Parent history stays unchanged."},
                        {"from": 208, "to": 270, "text": "Rollback reproduces the original final hash."},
                    ],
                }
            )
        elif eid == "Roadmap05":
            payload.update(
                {
                    "hook": ["A SIMULATION SHOULD BE ABLE TO FAIL."],
                    "tests": [
                        "future-data leakage rejected",
                        "parent-state mutation detected",
                        "parent-history mutation detected",
                        "no-op event produces no fork effect",
                        "same seed produces the same trajectory",
                        "rollback reproduces the original continuation",
                        "provenance without required fields rejected",
                        "modified contract hash rejected",
                        f"{d('clean_room_tests')} clean-room tests passed",
                    ],
                    "statuses": [
                        {"label": "TECHNICAL CORE", "value": "VERIFIED"},
                        {"label": "CLINICAL VALIDATION", "value": "NOT STARTED"},
                    ],
                    "thesis": "WE TEST FAILURE MODES BEFORE WE TRUST PERFORMANCE.",
                    "captions": [
                        {"from": 0, "to": 56, "text": "A simulation should be able to fail."},
                        {"from": 56, "to": 140, "text": "PASS only after the check. Expected FAIL is part of the design."},
                        {"from": 140, "to": 208, "text": f"{d('clean_room_tests')} clean-room tests passed. Technical core verified."},
                        {"from": 208, "to": 270, "text": "Clinical validation not started."},
                    ],
                }
            )
        elif eid == "Roadmap06":
            p_mae = d("metric_persistence_mae")
            l_mae = d("metric_learned_mae")
            n_subj = d("sdr_n_subjects_with_pairs")
            n_pairs = d("sdr_n_consecutive_pairs")
            n_test_s = d("sdr_test_subjects")
            n_test_p = d("sdr_test_pairs")
            payload.update(
                {
                    "hook": [
                        "LOWER ERROR THAN PERSISTENCE.",
                        "TWO TEST SUBJECTS. NO SIGNAL CLAIMED.",
                    ],
                    "status_badge": "FIRST EXPLORATORY RETROSPECTIVE BACKTEST COMPLETE",
                    "method": [
                        "Observed state at t0",
                        "Prediction",
                        "Real follow-up at t1",
                        "Measured error",
                        "Honest conclusion",
                    ],
                    "models": [
                        {"label": "Persistence baseline", "status": "WORKING_NOW", "mae": p_mae},
                        {"label": "Empirical trend", "status": "WORKING_NOW", "mae": p_mae},
                        {"label": "First learned Ridge baseline", "status": "WORKING_NOW", "mae": l_mae},
                    ],
                    "metrics": [
                        {"label": "Subjects with consecutive pairs", "value": n_subj},
                        {"label": "Strict consecutive pairs", "value": n_pairs},
                        {"label": "Test subjects / pairs", "value": f"{n_test_s} / {n_test_p}"},
                        {"label": "Persistence MAE", "value": p_mae},
                        {"label": "Learned MAE", "value": l_mae},
                        {"label": "Uncertainty calibration", "value": d("uncertainty_calibration_status")},
                    ],
                    "guards": [
                        "EXPLORATORY TEST",
                        f"TEST: {n_test_s} SUBJECTS / {n_test_p} PAIRS",
                        "NO INCREMENTAL SIGNAL CLAIMED",
                        "CLINICAL VALIDATION: NOT STARTED",
                    ],
                    "thesis": "LOWER ERROR THAN PERSISTENCE. TWO TEST SUBJECTS. NO SIGNAL CLAIMED.",
                    "conclusion": (
                        "A smaller error is not a scientific claim when the held-out test is only two subjects."
                    ),
                    "captions": [
                        {"from": 0, "to": 56, "text": "First exploratory retrospective backtest is complete."},
                        {
                            "from": 56,
                            "to": 140,
                            "text": f"Persistence MAE {p_mae}. Learned MAE {l_mae}. Test: {n_test_s} subjects / {n_test_p} pairs.",
                        },
                        {"from": 140, "to": 208, "text": "No incremental signal claimed. Clinical validation not started."},
                        {"from": 208, "to": 270, "text": "A smaller error is not a claim when the test is two subjects."},
                    ],
                }
            )
        episodes.append(payload)
    return {
        "schema": "uhbse.public.roadmap.fixture.v1",
        "series_title": SERIES_TITLE,
        "fps": FPS,
        "width": WIDTH,
        "height": HEIGHT,
        "no_database_connection": True,
        "synthetic_composite_only": True,
        "episodes": episodes,
    }


def write_fixture(root: Path, bindings: dict[str, Any]) -> Path:
    doc = build_fixture(bindings)
    path = root / EVIDENCE_DIR / "public-fixture.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
