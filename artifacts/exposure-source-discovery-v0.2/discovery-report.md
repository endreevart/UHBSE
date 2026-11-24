# Exposure source discovery v0.2

Report status: FINAL

Technical discovery only. Human field meanings stay pending. This is not Stage 05 Gate 1,
not a readiness upgrade, and not an intervention-response cohort.

`TECHNICAL_DISCOVERY_STATUS`=PASS
`SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS`=NOT_ESTABLISHED
`SOURCE_B_TEMPORAL_SEQUENCE_STATUS`=CANDIDATE_COUNTED_IDENTITY_NOT_ESTABLISHED
`OWNER_SEMANTIC_REVIEW_STATUS`=AWAITING_OWNER_CONFIRMATION
`PATIENT_REPORTED_INTAKE_TIER_STATUS`=NOT_ACCEPTED_PENDING_SEMANTIC_REVIEW
`INTERVENTION_RESPONSE_READINESS_STATUS`=NOT_READY

## Source A localization

Pattern fractions below are of non-empty region texts. History and diagnosis text is a control,
not a recommendation.

- whole document dose-like: 0.6334
- recommendations node dose-like: 0.7342
- recommendation items dose-like: 0.7418
- outside recommendations dose-like: 0.004
- section codes profiled: 8
- direct medicine-row foreign key to a recommendation document: False
- shared visit key on the medicine row: NOT_AVAILABLE

Dose-like fraction by section code. This does not decide which code is a medication instruction.

- `activity`: documents 33404, sections 34271, dose-like 0.8994
- `data_povtornogo_obrashcheniia`: documents 3125, sections 3965, dose-like 0.0007
- `inye_rekomendatsii`: documents 2943, sections 3785, dose-like 0.2355
- `medicines`: documents 641, sections 641, dose-like 0.7441
- `napravlenie`: documents 9545, sections 9545, dose-like 0.0
- `napravleniia`: documents 3096, sections 3716, dose-like 0.0022
- `nutrition`: documents 30265, sections 31183, dose-like 0.1559
- `sport`: documents 2780, sections 3611, dose-like None

- medical-report recommendations dose-like: 0.724
- medical-report drugs dose-like: 0.9516
- medical-report history and diagnosis dose-like: 0.3839
- medicine rows with no recommendation document on the same calendar day: 24530
- medicine rows with no recommendation document within 7 days: 22022

## Source B

- feedback rows: 41407
- linked consultation disagreements: 0
- linked consultation agreements are not schema proof.
- feedback before the linked consultation: 31271
- feedback after the linked consultation: 24
- change_drugs negative/placeholder/empty/null fraction: 0.7362
- decline_drugs negative/placeholder/empty/null fraction: 0.6088

The candidate route from an earlier drug recommendation through feedback to a later consultation
uses an unverified subject equality when identity is not established. It is not a verified exposure.

Owner questions are in `owner-questions.md`. No external contact was made.
