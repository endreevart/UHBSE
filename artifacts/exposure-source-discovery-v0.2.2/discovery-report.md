# Exposure source discovery v0.2.2 — owner semantic decisions

**Report status: FINAL (decision ingestion only)**

Not Stage 05 Gate 1. No medication extractor, mapping acceptance, cohort, model, or review ZIP.
Answers come from the system architect (`role=system_architect`), relayed verbally and recorded
in `owner-answer-record.json`. Each decision is bound to its answer by `evidence_sha256`.

## Status

- `TECHNICAL_DISCOVERY_STATUS`=PASS
- `DECISION_SCHEMA_VALIDATION_STATUS`=PASS
- `OWNER_SEMANTIC_REVIEW_STATUS`=PARTIAL_OWNER_DECISIONS_RECORDED
- `SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS`=OWNER_STATED_RECALL_UNCERTAIN_NOT_DATA_PROOF
- `SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS`=NOT_ESTABLISHED
- `SOURCE_B_TIMEZONE_SEMANTICS_STATUS`=OWNER_STATED_EUROPE_MOSCOW
- `FEEDBACK_REPORTING_WINDOW_STATUS`=OWNER_CONFIRMED
- `SOURCE_B_TEMPORAL_SEQUENCE_STATUS`=CANDIDATE_COUNTED_SEQUENCE_SEMANTICS_OWNER_CONFIRMED
- `SOURCE_A_MEDICATION_SECTION_STATUS`=OWNER_CONFIRMED_MEDICINES
- `SOURCE_A_ACTIVITY_SECTION_STATUS`=LIKELY_LIFESTYLE_NOT_MEDICATION
- `SOURCE_A_V02_DOSE_SIGNAL_INTERPRETATION_STATUS`=CORRECTION_REQUIRED_ACTIVITY_SIGNAL_NOT_MEDICATION_EVIDENCE
- `SOURCE_A_MEDICINE_ASSIGNMENT_SEMANTICS`=ASSIGNMENT_NOT_ADMINISTRATION
- `CROSS_SOURCE_IDENTITY_LINKAGE_STATUS`=NOT_PERFORMED
- `PATIENT_REPORTED_INTAKE_TIER_STATUS`=NOT_ACCEPTED_PENDING_SEMANTIC_REVIEW
- `CONFIRMED_ADMINISTRATION_MAPPING_COUNT`=0
- `DOMAIN_ACCEPTED_MAPPING_COUNT`=0
- `INTERVENTION_RESPONSE_READINESS_STATUS`=NOT_READY
- `PUBLIC_DATA_MINIMIZATION_STATUS`=PASS_AGGREGATE_ONLY
- `NEGATIVE_CONTROL_STATUS`=PASS

## Field statuses

| Source | Field | Status | Decision |
|---|---|---|---|
| magerya_api | `document_recommendation.document.recommendations[].code=medicines` | OWNER_CONFIRMED | MEDICINES_SECTION_HOLDS_DRUGS_AND_SUPPLEMENTS |
| magerya_api | `document_analysis.items->document_analysisitem` | OWNER_CONFIRMED | ANALYSIS_ITEMS_ARE_COMPONENT_SUBANALYSES |
| kgz_raw | `public.feedback` | OWNER_CONFIRMED | FILLED_BY_PATIENT_OR_STAFF_FROM_PATIENT_WORDS |
| kgz_raw | `public.feedback.created_at` | OWNER_CONFIRMED | FILLED_BEFORE_CONSULTATION |
| kgz_raw | `public.feedback` | OWNER_CONFIRMED | FIRST_VISIT_GENERAL_HISTORY_REPEAT_VISIT_SINCE_PREVIOUS_VISIT |
| kgz_raw | `public.feedback.user_id` | OWNER_STATED_RECALL_UNCERTAIN | SAME_SUBJECT_AS_CONSULTATIONS_PATIENT_ID |
| kgz_raw | `public.feedback.drugs,public.feedback.vitamins` | OWNER_STATED_RECALL_UNCERTAIN | DRUGS_MEDICATIONS_VITAMINS_SUPPLEMENTS |
| kgz_raw | `public.feedback.drugs_first` | UNKNOWN | — |
| kgz_raw | `public.feedback.change_drugs,public.feedback.decline_drugs` | OWNER_CONFIRMED | CHANGE_OR_DECLINE_RELATIVE_TO_DOCTOR_RECOMMENDATIONS |
| kgz_raw | `public.feedback.positive_changes` | UNKNOWN | — |
| kgz_raw | `public.feedback` | UNKNOWN | — |
| kgz_raw | `public.consultations.date` | UNKNOWN | — |
| kgz_raw | `public.feedback.created_at,public.consultations.date` | OWNER_CONFIRMED | SOURCE_TIMEZONE_EUROPE_MOSCOW |
| magerya_api | `document_recommendation.document.recommendations[].code=activity` | LIKELY | LIFESTYLE_SECTION_NOT_MEDICATION_SECTION |
| magerya_api | `document_recommendation.document.recommendations[].items` | CONFIRMED_SCHEMA | ONE_RECOMMENDATION_PER_ITEM_NAME_AND_DOCTOR_TEXT |
| magerya_api | `document_recommendation` | LIKELY | ONE_MUTABLE_DOCUMENT_PER_APPOINTMENT_READ_ONLY_AFTER_APPOINTMENT_CLOSES_NO_VERSION_HISTORY |
| magerya_api | `diagnosis_medicineappointments->appointment` | CONFIRMED_SCHEMA | ASSIGNMENT_LINKED_TO_APPOINTMENT_VIA_DOCUMENT_APPOINTMENTANALYSISRESULT |
| magerya_api | `diagnosis_medicines.category` | CONFIRMED_SCHEMA | DRUG_OR_SUPPLEMENTS |

## Source A evidence (aggregate, query identifiers in `query-log.json`)

- Recommendation section catalog (`a_template_categories`):
  - `activity` = Образ жизни
  - `diagnosis` = Диагноз
  - `inye_rekomendatsii` = Иные рекомендации
  - `manipuliatsii` = Манипуляции
  - `medicines` = Медикаменты
  - `napravleniia` = Направление к специалистам
  - `nutrition` = Питание
  - `protsedury` = Процедурный кабинет
  - `sport` = Спорт
- Item keys (`a_item_keys`): description=251595, name=251595.
- Recommendation documents (`a_recommendation_shape`): documents=53894, distinct_appointments=53894, one_per_appointment=True.
- Medicine catalog (`a_medicine_catalog`): drug=683, supplements=197.
- Assignment statuses (`a_medicine_status`): added=24318, draft=846, not_received=562.
- Assignment→appointment links (`a_medicine_link`): link_rows=28768, resolving=28768, distinct_appointments=4237, with_recommendation_document=4237, assignments_on_several_appointments=2630.

The v0.2 dose-like signal in `activity` cannot be read as medication evidence: the catalog label of
`activity` is a lifestyle section. A code fixture (`baker_recipes.py`) uses a different label and is not
production data.

## Source B

Candidate chains from v0.2.1: 26066/41407.
The owner confirms that feedback is filled before a consultation and, for a repeat visit, covers the
period since the previous visit. The subject statement is recorded with a recall caveat and is not data proof.

## Unresolved

- `public.feedback.drugs_first`, `positive_changes`, short «да»/«нет» values: UNKNOWN.
- `public.consultations.date` null cause: UNKNOWN.
- `drugs`/`vitamins` meaning and subject equality: owner recall uncertain.
- Whether a Source A recommendation document reached the patient: UNKNOWN.

Decisions: 9 of 15 answers; 6 answers create no decision.
