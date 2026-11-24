# Global Split + Individual Multi-Outcome State v0.1.1

Corrective release: horizon-aligned full-test backtest and evidence closure.
Frozen v0.1 providers were **not** refit.

## Statuses

- `BASELINE_VERIFICATION_STATUS` = `PASS`
- `PRIOR_V01_BACKTEST_HORIZON_STATUS` = `INVALID_FOR_HORIZON_ALIGNED_EVALUATION`
- `FROZEN_PROVIDER_NO_REFIT_STATUS` = `PASS`
- `HORIZON_ALIGNMENT_STATUS` = `PASS`
- `TARGET_IDENTITY_ACCOUNTING_STATUS` = `PASS`
- `TARGET_REUSE_AUDIT_STATUS` = `PASS`
- `GLOBAL_TEST_POPULATION_EVALUATION_STATUS` = `PASS`
- `PER_OUTCOME_EVIDENCE_TIER_STATUS` = `PASS`
- `REAL_HELDOUT_STATE_INVENTORY_STATUS` = `PASS`
- `REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS` = `PASS`
- `GLOBAL_PROVIDER_REGISTRY_STATUS` = `PASS`
- `ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS` = `TECHNICAL_REAL_HELDOUT_PASS`
- `CURRENT_STATE_CLASSIFIER_STATUS` = `NOT_STARTED`
- `JOINT_MULTI_OUTCOME_MODEL_STATUS` = `NOT_STARTED`
- `MEDICATION_RESIDUAL_MODEL_STATUS` = `NOT_STARTED`
- `INTERVENTION_RESPONSE_MODEL_STATUS` = `NOT_STARTED`
- `CLINICAL_VALIDATION_STATUS` = `NOT_STARTED`
- `PRODUCTION_READINESS` = `NOT_CLAIMED`
- `SECURITY_STAGE_STATUS` = `PAUSED_NOT_ACCEPTED_BY_OWNER`

## Why v0.1 metrics are invalid for horizon-aligned evaluation

v0.1 built predictions with horizon_days=30 but compared them to the strict next observation at the actual horizon (1–923 days).

- exact horizon matches: 0 / 995
- mismatches: 995
- actual horizon median: 113.0

## Funnel (full global test)

```json
{
  "n_global_test_subjects": 6635,
  "n_test_subjects_with_provider_grain_obs": 2342,
  "n_test_subjects_considered": 2342,
  "n_subjects_with_valid_cutoffs": 2342,
  "n_subjects_with_predictions": 804,
  "n_subjects_with_horizon_aligned_targets": 623,
  "silent_cap_used": false,
  "owner_explicit_cap_contract": null
}
```

- EVALUABLE outcomes: 85
- DIAGNOSTIC_ONLY outcomes: 10
- primary unique targets: 19195

## Metrics comparison

v0.1 predicted at fixed horizon_days=30 but scored against next observation at actual horizon (1–923d). v0.1.1 rebuilds features/applicability/inference at actual_horizon_days, deduplicates to unique targets, and evaluates the full global-test population (not first-N).

### Prior v0.1 (preserved, marked invalid)

```json
{
  "status_mark": "INVALID_FOR_HORIZON_ALIGNED_EVALUATION",
  "n_prediction_targets": 995,
  "n_outcomes_evaluated": 75,
  "overall_interval_coverage": 0.9175879396984925,
  "n_test_subjects_considered": 100
}
```

### Corrected v0.1.1

```json
{
  "n_primary_targets": 19195,
  "n_evaluable_outcomes": 85,
  "n_diagnostic_only_outcomes": 10,
  "funnel": {
    "n_global_test_subjects": 6635,
    "n_test_subjects_with_provider_grain_obs": 2342,
    "n_test_subjects_considered": 2342,
    "n_subjects_with_valid_cutoffs": 2342,
    "n_subjects_with_predictions": 804,
    "n_subjects_with_horizon_aligned_targets": 623,
    "silent_cap_used": false,
    "owner_explicit_cap_contract": null
  },
  "provider_hashes_before": "b3b2175a2c714c8819012c692671ba735ac4c18f83e5d4dcacaa79526207d42e",
  "provider_hashes_after": "b3b2175a2c714c8819012c692671ba735ac4c18f83e5d4dcacaa79526207d42e"
}
```

## Publication lifecycle

Inside the review ZIP, post-pack statuses are `EXTERNAL_ATTESTATION_REQUIRED`. Final PASS is only in the external attestation sidecar.

