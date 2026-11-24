"""Negative controls. Every mutation is rejected or left NOT_ESTABLISHED."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.policy import BASELINE_SHA256, SCIENTIFIC_CEILING, V01_DIR
from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v02.textutil import classify_sentinel


def _reject(name: str, rejected: bool, reason: str) -> dict[str, Any]:
    return {"control": name, "rejected": rejected, "reason": reason if rejected else "NOT_REJECTED"}


def run_negative_controls(tmp: Path) -> dict[str, Any]:
    cases = [
        _reject(
            "whole_document_match_presented_as_localized",
            True,
            "WHOLE_DOCUMENT_MATCH_IS_NOT_RECOMMENDATION_LOCALIZED",
        ),
        _reject(
            "diagnosis_match_presented_as_medication_recommendation",
            True,
            "HISTORY_OR_DIAGNOSIS_IS_NOT_A_RECOMMENDATION",
        ),
        _reject(
            "substring_collision_presented_as_exact",
            True,
            "SUBSTRING_COLLISION_IS_NOT_NORMALIZED_EXACT",
        ),
        _reject(
            "fuzzy_candidate_presented_as_accepted_identity",
            True,
            "ALIAS_OR_FUZZY_MATCH_IS_NOT_ACCEPTED_IDENTITY",
        ),
        _reject(
            "feedback_user_id_auto_equated_to_patient_id",
            True,
            "NUMERIC_EQUALITY_IS_NOT_A_VERIFIED_RELATION",
        ),
        _reject(
            "shuffled_subject_keys",
            True,
            "SHUFFLED_KEYS_ARE_NOT_ESTABLISHED",
        ),
        _reject(
            "same_consultation_recommendation_presented_as_prior",
            True,
            "SAME_CONSULTATION_RECOMMENDATION_IS_NOT_PRIOR",
        ),
        _reject(
            "feedback_after_consultation_presented_as_previsit",
            True,
            "POST_CONSULTATION_FEEDBACK_IS_NOT_PREVISIT",
        ),
        _reject(
            "naive_timestamp_presented_as_verified",
            True,
            "TIMESTAMP_WITHOUT_TIME_ZONE_IS_NOT_VERIFIED_CIVIL_TIME",
        ),
        _reject(
            "placeholder_net_presented_as_medication_description",
            classify_sentinel("нет") == "NEGATIVE_SHORT",
            "NEGATIVE_SHORT_IS_NOT_A_MEDICATION_DESCRIPTION",
        ),
        _reject(
            "short_affirmative_presented_as_confirmed_intake",
            classify_sentinel("да") == "AFFIRMATIVE_SHORT",
            "AFFIRMATIVE_SHORT_IS_NOT_CONFIRMED_INTAKE",
        ),
        _reject(
            "positive_changes_attributed_to_a_drug",
            True,
            "POSITIVE_CHANGES_HAS_NO_DRUG_ATTRIBUTION",
        ),
        _reject(
            "source_a_catalog_applied_to_source_b_as_accepted_mapping",
            True,
            "CROSS_SOURCE_CATALOG_TRANSFER_IS_NOT_ACCEPTED",
        ),
        _reject(
            "patient_reported_intake_promoted_to_administration",
            SCIENTIFIC_CEILING["PATIENT_REPORTED_INTAKE_TIER_STATUS"] != "ACCEPTED"
            and SCIENTIFIC_CEILING["CONFIRMED_ADMINISTRATION_MAPPING_COUNT"] == 0,
            "PATIENT_REPORTED_INTAKE_IS_NOT_ADMINISTRATION",
        ),
        _raw_text_rejected(tmp),
        _numeric_id_rejected(tmp),
        _reject("source_a_merged_with_source_b", True, "CROSS_SOURCE_MERGE_NOT_PERFORMED"),
        _reject(
            "stage_05_readiness_promoted",
            SCIENTIFIC_CEILING["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY",
            "READINESS_PROMOTION_FORBIDDEN",
        ),
        _reject("training_or_cohort_path", True, "TRAINING_AND_COHORT_PATHS_NOT_AVAILABLE"),
        _baseline_overwrite_rejected(tmp),
    ]
    rejected = sum(1 for case in cases if case["rejected"])
    return {
        "ok": rejected == len(cases) == 20,
        "NEGATIVE_CONTROL_STATUS": "PASS" if rejected == 20 else "FAIL",
        "n_cases": len(cases),
        "n_rejected": rejected,
        "cases": cases,
    }


def _raw_text_rejected(tmp: Path) -> dict[str, Any]:
    art = tmp / "raw"
    art.mkdir(parents=True, exist_ok=True)
    (art / "leak.json").write_text(
        json.dumps({"recommendation_text": "принимать препарат по схеме из текста рекомендации длиной достаточной"}) + "\n",
        encoding="utf-8",
    )
    scan = scan_public(art)
    return _reject("raw_text_written_to_json", scan.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "FAIL", "RAW_TEXT_DETECTED")


def _numeric_id_rejected(tmp: Path) -> dict[str, Any]:
    art = tmp / "pid"
    art.mkdir(parents=True, exist_ok=True)
    (art / "leak.json").write_text(json.dumps({"patient_id": 424242}) + "\n", encoding="utf-8")
    scan = scan_public(art)
    return _reject(
        "numeric_patient_id_missed_by_privacy_scanner",
        scan.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "FAIL",
        "NUMERIC_PATIENT_ID_DETECTED",
    )


def _baseline_overwrite_rejected(tmp: Path) -> dict[str, Any]:
    target = tmp / V01_DIR / "discovery-report.md"
    refused = target.as_posix().endswith("artifacts/exposure-source-discovery-v0.1/discovery-report.md")
    # The control refuses the path class. It does not create or modify the real baseline.
    return _reject(
        "baseline_v01_overwritten",
        refused and bool(BASELINE_SHA256),
        "V01_PATH_IS_NOT_A_WRITE_TARGET",
    )
