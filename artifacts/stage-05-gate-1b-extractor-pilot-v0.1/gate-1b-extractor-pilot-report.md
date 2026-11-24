# Stage 05 Gate 1B extractor pilot v0.1

**Report status: FINAL (gate open, precision/recall not measured)**

The owner opened Gate 1B on 2026-11-17.
The pilot counts candidate slots in Source B feedback.
A candidate is not an accepted medication and not administration.
Private labels were not supplied, so precision and recall stay unmeasured.
Gate 2 was not started.

## Status

- `GATE_1B_STATUS`=OPEN
- `GATE_1B_PILOT_STATUS`=EXECUTED_PRECISION_RECALL_NOT_MEASURED
- `PRECISION_RECALL_STATUS`=NOT_MEASURED
- `PRIVATE_LABEL_SET_STATUS`=ABSENT
- `GATE_2_STATUS`=CLOSED
- `INTERVENTION_RESPONSE_READINESS_STATUS`=NOT_READY
- `INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT`=0
- `INTERVENTION_RESPONSE_MODEL_STATUS`=NOT_STARTED
- `DOMAIN_ACCEPTED_MAPPING_COUNT`=0
- `PUBLIC_DATA_MINIMIZATION_STATUS`=PASS_AGGREGATE_ONLY
- `stream_error_class`=None

`drugs` and `vitamins` stay separate current-intake fields.
`change_drugs` counts a replacement statement. `decline_drugs` counts discontinuation.
`drugs_first` counts previously prescribed text.
Short yes and no are not a regimen.
`positive_changes` is not extracted.
Timing and period assign 0 rows.
Source A stays open.
