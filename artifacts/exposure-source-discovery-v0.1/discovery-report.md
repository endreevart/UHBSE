# Exposure source discovery v0.1

Report status: DRAFT

Aggregate-only discovery of recommendation and intake evidence. Read-only sessions
(`default_transaction_read_only=on`, `statement_timeout`, `lock_timeout`). Text and JSON
were parsed inside the local process. No values, identifiers or free text were exported.
Privacy scan: `PASS_AGGREGATE_ONLY` (`privacy-scan.json`).

All field meanings below are **UNKNOWN** until human review. Names of fields are not evidence
of meaning. Recommendation is not administration. Nothing here changes the published
readiness result (`INTERVENTION_RESPONSE_READINESS_STATUS=NOT_READY`).

Evidence files: `source-a-discovery.json`, `source-b-discovery.json`, `followup-discovery.json`,
`query-log.json` (query names and durations).

## Source A (`magerya_api`)

| Field | Rows | Non-empty | Dose-like | Frequency-like | Duration-like | Supplement terms | Catalog drug mention |
|---|---|---|---|---|---|---|---|
| `document_recommendation.document` | 53 894 | 87.7% | 72.2% | 70.4% | 65.9% | 68.7% | 62.2% of docs |
| `document_medicalreport.document` | 45 062 | 100% | 95.2% | 87.6% | 89.5% | 98.1% | 88.8% of docs |
| `document_recommendationtemplate.description` | 15 620 | 6.2% | 77.5% | 65.1% | 60.6% | 9.8% | not run |

Percentages for pattern columns are of non-empty rows.

- `document_recommendation.document` is structured: `recommendations[]` with `code`, `title`, `items`
  (40 696 docs). Section codes by count: `activity` 34 271, `nutrition` 31 183, `napravlenie` 9 545,
  `data_povtornogo_obrashcheniia` 3 965, `inye_rekomendatsii` 3 785, `napravleniia` 3 716, `sport` 3 611,
  `medicines` 641; 8 low-support or non-identifier codes suppressed. Query: `a_rec_sections`.
- Drug-like content appears far more often than the `medicines` section count. Which section carries
  medication instructions is UNKNOWN. Query: `a_rec_document`, `a_rec_sections`.
- `document_medicalreport.document` contains a `recommendations` block too. It also contains direct
  identifier fields (names, birthdate); any later parsing must stay in-process. Query: `a_medreport_document`.
- `diagnosis_medicines`: 880 entries; `unit_of_measurement_id`, `form_id`, `reception_frequency_id` are
  filled in 0 rows; `diagnosis_receptionfrequency` has 0 rows. Query: `a_medicine_catalog_fk_fill`,
  `a_reception_frequency_rows`.
- `diagnosis_medicineappointments`: 5.9% of rows have a recommendation document for the same patient
  created within 1 day. The structured table is mostly not a mirror of the documents. Interpretation
  UNKNOWN. Query: `a_medicineappointment_to_recommendation_doc_same_day`.

## Source B (`kgz_raw`)

| Field | Rows | Non-empty | Dose-like | Frequency-like | Supplement terms | Change terms |
|---|---|---|---|---|---|---|
| `consultations.recommendations` | 88 867 | 93.1% | 99.9% | 99.9% | 99.9% | 64.9% |
| `recommendations_user.description` | 999 606 | 99.99% | 49.4% | 31.9% | 36.8% | 4.5% |
| `feedback.drugs` | 41 407 | 95.7% | 37.4% | 23.8% | 23.1% | 1.6% |
| `feedback.vitamins` | 41 407 | 82.0% | 70.7% | 53.8% | 84.1% | 1.7% |
| `feedback.change_drugs` | 41 407 | 82.0% | 5.5% | 1.8% | 11.0% | 16.3% |
| `feedback.decline_drugs` | 41 407 | 82.0% | 5.6% | 2.8% | 14.0% | 17.8% |
| `feedback.positive_changes` | 41 407 | 81.9% | 0.8% | 6.5% | 3.1% | 2.8% |
| `questionnaire.drugs_second` | 52 686 | 74.4% | 31.4% | 20.4% | 17.9% | 1.2% |
| `questionnaire.drugs_third` | 52 686 | 74.4% | 42.6% | 22.2% | 58.6% | 1.0% |

- `recommendations_user` by catalog category (`recommendations_list.category_id`):
  «Препараты» 454 492, «Диагнозы» 304 069, «Питание» 241 045. Category titles are reference
  catalog labels. Query: `b_rec_user_by_category`.
- `feedback` rows with `consultation_id`: 33 373 of 41 407. Only 31 are created after the linked
  consultation date; median `created_at − consultation.date` is −20.3 days. The linked consultation
  is likely the next visit, so feedback may describe the period before it. UNKNOWN. Query:
  `b_feedback_consultation_linkage`.
- 67.0% of feedback rows (27 729) follow an earlier consultation of the same subject with a
  «Препараты» recommendation; median gap 61 days. Subject key equality
  `feedback.user_id = consultations.patient_id` is an assumption pending review. Query:
  `b_feedback_prior_drug_recommendation`.
- Source A catalog was not used on Source B text (`source_a_catalog_used=false`).

## Pattern caveats

Pattern hits are signals, not extraction. The dose pattern also matches year markers such as
"2023 г", and supplement terms match words like "железо" in lab context. Exact rates need a
reviewed extractor.

## Candidate exposure tiers (not accepted)

| Candidate | Tier candidate | Status |
|---|---|---|
| Source A `document_recommendation` sections | `RECOMMENDED` | UNKNOWN |
| Source B `recommendations_user` category «Препараты» | `RECOMMENDED` | UNKNOWN |
| Source B `feedback.drugs`, `feedback.vitamins` | patient-reported current intake | UNKNOWN |
| Source B `feedback.change_drugs`, `feedback.decline_drugs` | patient-reported change or refusal | UNKNOWN |
| Source B `feedback.positive_changes`, `feedback.complaints` | patient-reported response | UNKNOWN |

## Questions for the source owners

1. Source A: which `recommendations[].code` sections carry medication and supplement instructions,
   and what do `items` hold?
2. Source A: are recommendation documents final versions given to the patient?
3. Source B: is `feedback` filled by the patient before the next consultation, and does it describe
   intake since the previous recommendation?
4. Source B: does `feedback.user_id` refer to the same subject as `consultations.patient_id`?
5. Source B: do `change_drugs` / `decline_drugs` mean changes relative to the doctor's recommendation?
