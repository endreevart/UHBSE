"""Negative controls: each case mutates a valid input and expects the validator or contract to reject it."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v022.contract import field_statuses, stage_statuses, violations
from human_simulator.exposure_source_discovery_v022.decisions import (
    answer_record,
    build_decisions,
    evidence_hash_errors,
    validate,
    validate_all,
)
from human_simulator.exposure_source_discovery_v022.policy import ANSWERS, NOT_KNOWN

EXPECTED_CASES = 18


def synthetic_evidence() -> dict[str, Any]:
    return {
        "template_categories": [
            {"code": "activity", "label": "Образ жизни", "prohibit_deletion": False},
            {"code": "medicines", "label": "Медикаменты", "prohibit_deletion": True},
        ],
        "item_key_counts": {"description": 3, "name": 3},
        "recommendation_shape": {"one_document_per_appointment": True},
        "medicine_appointment_link": {"link_rows": 2, "link_rows_resolving_to_assignment": 2},
    }


def _v021() -> dict[str, Any]:
    return {
        "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": "CANDIDATE_COUNTED_IDENTITY_NOT_ESTABLISHED",
        "counts": {"candidate_count": 3, "candidate_denominator": 5},
    }


def _baseline(schema: dict[str, Any]) -> dict[str, Any]:
    record = answer_record(ANSWERS)
    decisions = build_decisions(record)
    evidence = synthetic_evidence()
    code = {"SOURCE_A_CODE_EVIDENCE_STATUS": "AVAILABLE"}
    fields = field_statuses(record, evidence, code)
    status = stage_statuses(record, evidence, _v021())
    return {"record": record, "decisions": decisions, "evidence": evidence, "fields": fields, "status": status}


def _case(name: str, rejected: bool, reason: str) -> dict[str, Any]:
    return {"control": name, "rejected": bool(rejected), "reason": reason if rejected else "NOT_REJECTED"}


def _status_mutation(base: dict[str, Any], key: str, value: Any) -> bool:
    status = {**base["status"], key: value}
    return bool(violations(status, base["decisions"], base["record"], base["fields"]))


def run_negative_controls(tmp: Path, schema: dict[str, Any]) -> dict[str, Any]:
    base = _baseline(schema)
    valid = base["decisions"][0]
    clean = (
        validate_all(base["decisions"], base["record"], schema)["ok"]
        and not violations(base["status"], base["decisions"], base["record"], base["fields"])
    )

    missing = {k: v for k, v in valid.items() if k != "reviewer_digest"}
    extra = {**valid, "reviewer_name": "architect"}
    bad_time = {**valid, "decided_at": "2026-11-06 20:47"}
    bad_hash = {**valid, "evidence_sha256": "not-a-hash"}
    named = {**valid, "reviewer_digest": "system architect by name"}

    edited = copy.deepcopy(base["record"])
    next(a for a in edited if a["answer_key"] == "B2")["decision"] = "FILLED_AFTER_CONSULTATION"

    silent = next(a for a in base["record"] if a["answer_key"] == "B8")
    fabricated = {**valid, "field_path": silent["field_path"], "decision": "X", "evidence_sha256": silent["answer_sha256"]}

    promoted = copy.deepcopy(base["fields"])
    next(f for f in promoted if f.get("answer_key") == "B4")["status"] = "OWNER_CONFIRMED"

    activity = copy.deepcopy(base["fields"])
    next(f for f in activity if f["field_path"].endswith("code=activity"))["decision"] = "MEDICATION_SECTION"

    no_code = field_statuses(base["record"], base["evidence"], {"SOURCE_A_CODE_EVIDENCE_STATUS": "UNAVAILABLE"})
    items = next(f for f in no_code if f["field_path"].endswith("recommendations[].items"))

    no_tz = copy.deepcopy(base["record"])
    next(a for a in no_tz if a["answer_key"] == "B11")["certainty"] = NOT_KNOWN

    leak = tmp / "numeric-id"
    leak.mkdir(parents=True, exist_ok=True)
    (leak / "leak.json").write_text(json.dumps({"patient_id": 15}) + "\n", encoding="utf-8")

    cases = [
        _case("missing_reviewer_digest", "missing:reviewer_digest" in validate(missing, schema), "SCHEMA_REQUIRED"),
        _case("extra_property_with_personal_name", "extra:reviewer_name" in validate(extra, schema), "SCHEMA_CLOSED"),
        _case("decided_at_without_utc", "pattern:decided_at" in validate(bad_time, schema), "SCHEMA_PATTERN"),
        _case("evidence_hash_not_sha256", "pattern:evidence_sha256" in validate(bad_hash, schema), "SCHEMA_PATTERN"),
        _case("reviewer_digest_is_plain_text", "reviewer_digest_not_sha256" in validate(named, schema), "DIGEST_REQUIRED"),
        _case("answer_edited_after_hashing", bool(evidence_hash_errors(base["decisions"], edited)), "EVIDENCE_HASH_BOUND"),
        _case(
            "decision_fabricated_from_not_remembered_answer",
            not validate_all(base["decisions"] + [fabricated], base["record"], schema)["ok"]
            and bool(violations(base["status"], base["decisions"] + [fabricated], base["record"], base["fields"])),
            "UNKNOWN_STAYS_UNKNOWN",
        ),
        _case(
            "recall_uncertain_identity_promoted_to_confirmed",
            bool(violations(base["status"], base["decisions"], base["record"], promoted)),
            "RECALL_CAVEAT_PRESERVED",
        ),
        _case(
            "identity_claimed_established",
            _status_mutation(base, "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS", "ESTABLISHED"),
            "OWNER_STATEMENT_IS_NOT_DATA_PROOF",
        ),
        _case(
            "identity_data_proof_claimed",
            _status_mutation(base, "SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS", "ESTABLISHED"),
            "OWNER_STATEMENT_IS_NOT_DATA_PROOF",
        ),
        _case(
            "administration_mapping_counted",
            _status_mutation(base, "CONFIRMED_ADMINISTRATION_MAPPING_COUNT", 1),
            "CEILING_ADMINISTRATION",
        ),
        _case("domain_mapping_accepted", _status_mutation(base, "DOMAIN_ACCEPTED_MAPPING_COUNT", 1), "CEILING_DOMAIN"),
        _case(
            "cross_source_identity_linked",
            _status_mutation(base, "CROSS_SOURCE_IDENTITY_LINKAGE_STATUS", "PERFORMED"),
            "NO_A_B_MERGE",
        ),
        _case(
            "readiness_claimed",
            _status_mutation(base, "INTERVENTION_RESPONSE_READINESS_STATUS", "READY"),
            "CEILING_READINESS",
        ),
        _case(
            "activity_section_labelled_medication",
            bool(violations(base["status"], base["decisions"], base["record"], activity)),
            "CATALOG_LABEL_IS_LIFESTYLE",
        ),
        _case(
            "assignment_treated_as_administration",
            _status_mutation(base, "SOURCE_A_MEDICINE_ASSIGNMENT_SEMANTICS", "ADMINISTRATION"),
            "ASSIGNMENT_NOT_ADMINISTRATION",
        ),
        _case(
            "code_only_fact_kept_confirmed_without_code",
            items["status"] != "CONFIRMED_SCHEMA",
            "CODE_EVIDENCE_REQUIRED",
        ),
        _case(
            "timezone_kept_without_answer",
            stage_statuses(no_tz, base["evidence"], _v021())["SOURCE_B_TIMEZONE_SEMANTICS_STATUS"]
            == "UNKNOWN_SOURCE_TIMEZONE",
            "TIMEZONE_NEEDS_OWNER_ANSWER",
        ),
    ]
    privacy_rejects_numeric_id = scan_public(leak)["PUBLIC_DATA_MINIMIZATION_STATUS"] == "FAIL"
    rejected = sum(1 for case in cases if case["rejected"])
    ok = clean and privacy_rejects_numeric_id and rejected == len(cases) == EXPECTED_CASES
    return {
        "ok": ok,
        "NEGATIVE_CONTROL_STATUS": "PASS" if ok else "FAIL",
        "baseline_accepted": clean,
        "privacy_rejects_numeric_identifier": privacy_rejects_numeric_id,
        "n_cases": len(cases),
        "n_rejected": rejected,
        "cases": cases,
    }
