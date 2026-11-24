# Stage 05 Gate 1A primary evidence recovery v0.1

**Report status: FINAL (Gate 1A still open)**

Primary evidence was read from database catalogs and the configured Magerya checkout.
No Source B application repository was available. No new question was closed.

## Status

- `GATE_1A_EVIDENCE_RECOVERY_STATUS`=PASS
- `GATE_1A_STATUS`=PARTIALLY_ATTESTED_OPEN
- `GATE_1A_SOURCE_B_EXPOSURE_ROUTE_STATUS`=BLOCKED
- `GATE_1B_STATUS`=BLOCKED
- `SOURCE_B_APPLICATION_CODE_ACCESS_STATUS`=NOT_AVAILABLE
- `SOURCE_B_FORM_SEMANTICS_STATUS`=NOT_RECOVERED_APPLICATION_CODE_NOT_AVAILABLE
- `SUPERSESSION_RESOLUTION_STATUS`=PASS
- `EFFECTIVE_B_TIMING_CLOSES_QUESTION`=False
- `EFFECTIVE_B_PERIOD_CLOSES_QUESTION`=False
- `B_TIMING_ROW_LEVEL_ASSIGNMENT_COUNT`=0
- `B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT`=0
- `NEW_SUPERSEDING_RECORD_COUNT`=0
- `INTERVENTION_RESPONSE_READINESS_STATUS`=NOT_READY
- `INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT`=0
- `INTERVENTION_RESPONSE_MODEL_STATUS`=NOT_STARTED
- `PUBLIC_DATA_MINIMIZATION_STATUS`=PASS_AGGREGATE_ONLY
- `NEGATIVE_CONTROL_STATUS`=PASS

Accepted decisions remain 4 and insufficient decisions remain 10.
The workflow rules for timing and period are not applied to any feedback row.
`B_IDENTITY` has a consultation-row foreign key and no subject-key foreign key.
That is schema evidence, not identity proof.

Source B blockers stay open: `B_IDENTITY`, `B_DRUGS`, `B_VITAMINS`, `B_CHANGE`, `B_DECLINE`, `B_SHORT`.
`B_POSITIVE` stays deferred and is not a response label.
Source A stays open: `A_RECOMMENDATION_ITEMS`, `A_MEDICATION_CODE_SET`, `A_DOCUMENT_FINAL`.

Absence from the Magerya checkout is not treated as absence of a Source B form.
Gate 1B was not started.

## Repository follow-up

Source B form text is only in `gitlab.com/magerya/magerya` (`b362936`).
The patient form reads labels from `resources/lang/ru/feedback.php`.
The staff chat view binds the same FeedbackItem fields to the longer labels in `admin-panel` i18n.
`drugs_first` has a third label in that staff view.
`front8333110/spa-lk` does not contain these fields.
`mobile5385745/app-android` was not retrieved: the Git server closed the connection.
No question was closed.
