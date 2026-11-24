"""Superseding records from the 2026-11-17 owner answers. Words are not widened."""

from __future__ import annotations

import hashlib
from typing import Any

from human_simulator.exposure_source_discovery_v022.decisions import canonical_sha256
from human_simulator.stage05_gate1a_owner_attestation_v01.policy import (
    COMMIT_SHA,
    DECIDED_AT,
    PRIOR_RECORDS,
    REPOSITORY,
    REVIEWER_LABEL,
    REVIEWER_ROLE,
)

_NO_PRIOR = "NO_PRIOR_GATE_1A_QUESTION"


def reviewer_digest() -> str:
    return hashlib.sha256(REVIEWER_LABEL.encode("utf-8")).hexdigest()


def _base(previous: dict[str, Any] | None, question_id: str, field_path: str) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "prior_record_sha256": canonical_sha256(previous) if previous else hashlib.sha256(_NO_PRIOR.encode()).hexdigest(),
        "prior_question_present": previous is not None,
        "supersedes_artifact": PRIOR_RECORDS if previous else None,
        "source_system": "kgz_raw",
        "field_path": field_path,
        "repository": REPOSITORY,
        "commit_sha": COMMIT_SHA,
        "evidence_level": "E4",
        "evidence_type": "OWNER_ATTESTATION",
        "applicability": "PRODUCTION",
        "role": REVIEWER_ROLE,
        "reviewer_digest": reviewer_digest(),
        "prior_role": previous["role"] if previous else None,
        "prior_reviewer_digest": previous["reviewer_digest"] if previous else None,
        "decided_at": DECIDED_AT,
        "recall_uncertainty": False,
        "row_level_proof": False,
        "drugs_merged_with_vitamins": False,
        "yes_is_confirmed_intake": False,
        "response_label": False,
    }


def build_records(prior: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {record["question_id"]: record for record in prior}
    specs = (
        {
            "question_id": "B_DRUGS",
            "field_path": "public.feedback.drugs",
            "decision": "CURRENT_INTAKE",
            "owner_statement": "это что принимается",
            "file_path": "magerya_backend/resources/lang/ru/feedback.php",
            "symbol_or_migration": "feedback.form.drugs",
            "closes_question": True,
            "attestation": "accepted",
            "attestation_scope": "CURRENT_INTAKE_PRESCRIBER_AND_DOSE_NOT_ATTESTED",
            "ambiguities": ["prescriber was not stated", "dose was not stated"],
        },
        {
            "question_id": "B_VITAMINS",
            "field_path": "public.feedback.vitamins",
            "decision": "CURRENT_INTAKE",
            "owner_statement": "это что принимается",
            "file_path": "magerya_backend/resources/lang/ru/feedback.php",
            "symbol_or_migration": "feedback.form.vitamins",
            "closes_question": True,
            "attestation": "accepted",
            "attestation_scope": "CURRENT_INTAKE_SEPARATE_FROM_DRUGS",
            "ambiguities": ["prescriber was not stated", "dose was not stated"],
        },
        {
            "question_id": "B_CHANGE",
            "field_path": "public.feedback.change_drugs",
            "decision": "REPLACEMENT",
            "owner_statement": "это замена",
            "file_path": "admin-panel/src/assets/i18n/US/ru.json",
            "symbol_or_migration": "info_patient.FeedbackItem.change_drugs",
            "closes_question": True,
            "attestation": "accepted",
            "attestation_scope": "REPLACEMENT_ANALOG_AND_THERAPY_WINDOW_NOT_RESTATED",
            "ambiguities": ["analog and therapy window were not restated"],
        },
        {
            "question_id": "B_DECLINE",
            "field_path": "public.feedback.decline_drugs",
            "decision": "DISCONTINUATION",
            "owner_statement": "отмена препарата",
            "file_path": "admin-panel/src/assets/i18n/US/ru.json",
            "symbol_or_migration": "info_patient.FeedbackItem.decline_drugs",
            "closes_question": True,
            "attestation": "accepted",
            "attestation_scope": "DISCONTINUATION_EARLIER_THAN_RECOMMENDED_NOT_STATED",
            "ambiguities": ["earlier than the recommended term was not stated"],
        },
        {
            "question_id": "B_DRUGS_FIRST",
            "field_path": "public.feedback.drugs_first",
            "decision": "PREVIOUSLY_PRESCRIBED",
            "owner_statement": "ранее назначенные",
            "file_path": "admin-panel/src/app/views/chats/chat/components/info-patient/fields.ts",
            "symbol_or_migration": "FeedbackItem.drugs_first",
            "closes_question": True,
            "attestation": "accepted",
            "attestation_scope": "PREVIOUSLY_PRESCRIBED_OTHER_SPECIALIST_NOT_STATED",
            "ambiguities": ["other-specialist wording in the staff card was not selected"],
        },
        {
            "question_id": "B_IDENTITY",
            "field_path": "public.feedback.user_id",
            "decision": "SAME_USERS_ID",
            "owner_statement": "да",
            "file_path": "magerya_backend/modules/Core/Entities/ConsultationItem.php",
            "symbol_or_migration": "ConsultationItem.patient",
            "closes_question": True,
            "attestation": "accepted",
            "attestation_scope": "OWNER_ATTESTED_SAME_USERS_ID_NOT_A_DATABASE_FK",
            "ambiguities": ["the restored database has no foreign key between the columns"],
        },
        {
            "question_id": "B_SHORT",
            "field_path": "public.feedback",
            "decision": "FREE_TEXT_NOT_A_FORM_OPTION",
            "owner_statement": "да",
            "file_path": "magerya_backend/config/form-feedback.php",
            "symbol_or_migration": "form-feedback.casts",
            "closes_question": True,
            "attestation": "accepted",
            "attestation_scope": "FREE_TEXT_YES_IS_NOT_CONFIRMED_INTAKE",
            "ambiguities": [],
        },
    )
    records = []
    for spec in specs:
        question_id = spec["question_id"]
        previous = by_id.get(question_id)
        record = _base(previous, question_id, spec["field_path"])
        record.update({key: value for key, value in spec.items() if key not in {"question_id", "field_path"}})
        record["normalized_evidence_sha256"] = canonical_sha256({
            "question_id": question_id,
            "owner_statement": spec["owner_statement"],
            "decision": spec["decision"],
            "repository": REPOSITORY,
            "commit_sha": COMMIT_SHA,
            "file_path": spec["file_path"],
            "symbol_or_migration": spec["symbol_or_migration"],
        })
        records.append(record)
    return records
