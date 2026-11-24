"""Episode grain audit — describe actual grains without changing them."""

from __future__ import annotations

from typing import Any

from human_simulator.post_pilot_audit_v01.policy import VERSION


def build_grain_audit(funnel: dict[str, Any]) -> dict[str, Any]:
    findings = []

    findings.append(
        {
            "question": "Are multiple outcomes counted as one concept episode?",
            "answer": "NO — opposite: each outcome×unit is a separate concept episode row.",
            "evidence": (
                "episode_id hashes opaque_subject|medicine_id|event_ts|outcome|unit|"
                "hypothesis|horizon; JSONL materialises one row per outcome grain."
            ),
        }
    )
    findings.append(
        {
            "question": "Does concurrent medication count inflate episode count?",
            "answer": "NO — concurrent_med_count is a feature on each row, not a multiplier.",
            "evidence": "polypharmacy derived from same-day distinct medicine_id count; "
            "does not create extra JSONL rows.",
        }
    )
    findings.append(
        {
            "question": "Multiple episodes for one pre/post pair?",
            "answer": (
                "YES across outcomes: one medication event + one pre/post lab pair per "
                "outcome×unit. NO within a single outcome×unit (dedup by episode_id)."
            ),
            "evidence": "funnel unique_medication_events << total_concept_episodes",
        }
    )
    findings.append(
        {
            "question": "Row-level vs grouped-event counts mixed in pilot headline?",
            "answer": (
                "MIXED IN REPORTING LANGUAGE: 'total concept episodes' = row-level "
                "medication×outcome pairs; unique medication appointments are ~24–29× fewer. "
                "Primary CV uses single outcome×unit grain only."
            ),
            "severity_status": "DOCUMENTED_NOT_CHANGED",
        }
    )
    findings.append(
        {
            "question": "Duplication from two source medicine IDs (UDCA 500: 418+739)?",
            "answer": (
                "Possible across IDs if same subject has both medicines at different times; "
                "each medicine_id×event_ts is a distinct medication event. Not double-counting "
                "the same locator within one medicine_id."
            ),
            "note": "Grain unchanged; UDCA 500 unique events ≈ 67 for 65 subjects.",
        }
    )
    findings.append(
        {
            "question": "Valid rows removed by erroneous join?",
            "answer": (
                "No evidence in frozen JSONL for primary grains: same_time exclusions = 0 "
                "on primary; primary counts match reported. Upstream Level-4 already requires "
                "pre and post numeric labs within horizon."
            ),
        }
    )
    findings.append(
        {
            "question": "Is the five-outcome list too narrow?",
            "answer": (
                "Relative to concept episode table: YES — five grains retain only a minority "
                "of medication×outcome rows. Relative to prior association baseline contract: "
                "intentional reuse of V01 grains. Not expanded in this audit."
            ),
            "five_grain_vs_total": [
                {
                    "cohort_id": c["cohort_id"],
                    "total": c["n_total_concept_episodes"],
                    "five": c["n_five_grain_episodes"],
                    "primary": c["n_primary_episodes"],
                    "n_grains_present": c["n_outcome_unit_grains"],
                }
                for c in funnel.get("cohorts") or []
            ],
        }
    )

    grain_map = {
        "medication_event": "subject × medicine_id × event_ts",
        "medication_x_subject_event": "same as medication_event (subject embedded)",
        "medication_x_outcome_pair": "medication_event × outcome × unit (= concept episode row)",
        "medication_x_outcome_x_horizon_pair": "above + horizon_days=365 (JSONL file is h365)",
        "cv_prediction_row": "primary outcome×unit subset after filters; one row → one prediction",
    }

    return {
        "version": VERSION,
        "EPISODE_GRAIN_STATUS": "DOCUMENTED_NO_CHANGE",
        "grain_definitions_as_implemented": grain_map,
        "findings": findings,
        "grains_not_mixed_in_cv": True,
        "grain_changed_in_this_stage": False,
    }
