# Exposure source discovery v0.2.1

Report status: FINAL

Temporal and identity accounting correction of discovery v0.2.
Technical reconciliation only. This is not Stage 05 Gate 1.
Field meanings stay pending. Numeric key agreement is not an identity proof.

`TECHNICAL_DISCOVERY_STATUS`=PASS
`V02_TEMPORAL_ACCOUNTING_STATUS`=NOT_RECONCILED
`V02_FINAL_REPORT_ACCOUNTING_STATUS`=CORRECTION_REQUIRED
`SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS`=NOT_ESTABLISHED
`SOURCE_B_TIMEZONE_SEMANTICS_STATUS`=UNKNOWN_SOURCE_TIMEZONE
`SOURCE_B_TEMPORAL_SEQUENCE_STATUS`=CANDIDATE_COUNTED_IDENTITY_NOT_ESTABLISHED
`INTERVENTION_RESPONSE_READINESS_STATUS`=NOT_READY

## Feedback reconciliation

```text
feedback_total
= consultation_id_null
+ consultation_target_missing
+ target_found_before
+ target_found_same_day
+ target_found_after
+ target_found_time_uncomparable
```

feedback_total=41407
consultation_id_null=8034
consultation_target_missing=0
target_found_before=31271
target_found_same_day=7
target_found_after=24
target_found_time_uncomparable=2071

Uncomparable rows are found consultation targets whose dates cannot be ordered:
created_at null and consultation date null=7
created_at null and consultation date present=64
created_at present and consultation date missing=2000

consultation_id_present=33373
consultation_target_found=33373
consultation_target_not_found=0
consultation_target_multiple_match=0

## Subject-key reconciliation

```text
feedback_total
= subject_target_missing
+ subject_both_null
+ subject_user_id_null
+ subject_patient_id_null
+ subject_keys_equal
+ subject_keys_unequal
```

subject_target_missing=8034
subject_both_null=0
subject_user_id_null=0
subject_patient_id_null=0
subject_keys_equal=33373
subject_keys_unequal=0

Comparison of feedback.user_id and consultations.patient_id ran only where a consultation
target was found. The equality denominator is the sum of equal and unequal rows.
subject_equality_denominator=33373
Phrase: `NUMERIC_KEY_AGREEMENT_OBSERVED_NOT_IDENTITY_PROOF`.
There is no foreign key, documented crosswalk, or owner confirmation.

## Time

`feedback.created_at` is `timestamp without time zone`.
`consultations.date` is `date`.
Session TimeZone recorded as `Etc/UTC` and is not source-timezone proof.
Same day means the stored calendar dates are equal. A null timestamp or null consultation date
stays in `target_found_time_uncomparable`.

## Candidate route

Earlier drug recommendation on another consultation, then feedback, then a found consultation
on the same calendar day or later. Identity equality stays an unverified assumption.
A recommendation on the consultation itself is not a prior recommendation.
A missing consultation target is not a completed chain.

candidate_denominator=41407
candidate_count=26066
excluded_target_missing=8034
excluded_no_prior_recommendation=5212
excluded_out_of_order=6
excluded_same_consultation_only=3747
days since prior recommendation p10/p50/p90: 55.0 / 61.0 / 198.0
days from feedback to consultation p10/p50/p90: 8.0 / 21.0 / 66.0

v0.2 published four route counts that do not add up to feedback_total.
That gap is a discovery-accounting omission, not a Stage 05 defect.
The v0.2 directories were not modified.
