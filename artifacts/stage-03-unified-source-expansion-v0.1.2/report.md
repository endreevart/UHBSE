# Unified Source Expansion v0.1.2

**Status:** see verification.json

## Claims

- Corrected v0.1.1 publication indexed_members defect (members = indexed + 1).
- Exclusive quantile assignment; finite-sample permutation p=(n_extreme+1)/(n+1).
- Source B lab semantics + Observation construction gates.
- Observation load only when SUPPORTED_TRANSFORMATION gates pass.

## Non-claims

- Not clinical validation / treatment effect / production readiness.
- No migration 0005 / identity merge / Vault.
- v0.1 and v0.1.1 ZIPs remain immutable.

## Key statuses

```text
{
  "clinical_validation_status": "NOT_STARTED",
  "cross_source_outcome_comparability_status": "OUTCOME_NOT_COMPARABLE",
  "cross_source_overlap_control_status": "NO_DETECTED_OVERLAP_AFTER_CONSERVATIVE_EXCLUSION",
  "cross_source_transfer_status": "NOT_RUN_DUE_TO_FAILED_GATE",
  "identity_linkage_status": "CANDIDATE_ONLY",
  "intervention_response_model_status": "NOT_STARTED",
  "multi_source_canonical_status": "TECHNICAL_MULTI_SOURCE_PIPELINE_PASS",
  "post_publish_integrity_status": "PENDING_PUBLISH",
  "pre_publish_verification_status": "PENDING_PUBLISH",
  "production_readiness": "NOT_CLAIMED",
  "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
  "source_a_canonical_status": "PASS",
  "source_a_predictive_signal_status": "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED",
  "source_a_uncertainty_status": "CORRECTED_QUANTILE_AND_PERMUTATION",
  "source_b_encounter_audit_status": "PASS",
  "source_b_encounter_mapping_status": "ACCEPTED",
  "source_b_observation_contract_status": "SUPPORTED_TRANSFORMATION",
  "source_b_observation_idempotency_status": "PASS",
  "source_b_observation_load_status": "PASS",
  "source_b_observation_semantics_status": "PASS",
  "source_b_outcome_catalog_status": "INSUFFICIENT_DATA",
  "source_b_subject_mapping_status": "ACCEPTED",
  "treatment_effect_status": "NOT_EVALUATED"
}
```
