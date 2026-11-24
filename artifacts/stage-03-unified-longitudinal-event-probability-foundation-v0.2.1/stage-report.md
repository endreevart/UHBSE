# Unified Longitudinal Event Probability Foundation v0.2.1

**Report status: FINAL**

## Phase 0 — v0.2 defect reproduction

- V02_DEFECT_REPRODUCTION_STATUS: `PASS`
- V02_PROBABILITY_ACCEPTANCE_CLAIM_STATUS: `CORRECTION_REQUIRED`
- v0.2 global ACCEPTED claim is not transferred.

## Endpoints / identity

- Primary endpoint (pre-test, not model performance): `TIME_TO_NEXT_LAB_PANEL`
- OBSERVATION_EVENT_IDENTITY_STATUS: `BUILT`
- OBSERVATION_MICROINTERVAL_AUDIT_STATUS: `PUBLISHED`
- Administrative windows are source-specific; global max is an administrative bound, not continuous observation.

## Survival / cells

- KM: `BUILT`
- IPCW Brier: `graf_ipcw_brier_divide_by_n`
- Calibration: `ipcw_weighted_logit_slope`
- Discrete-time hazard: `TRAINED`
- Accepted cells: 9 (A=2, B=7)
- TECHNICAL_PROBABILITY_FOUNDATION_STATUS: `PARTIAL_ACCEPTED`

## Engine

- Routing: `PASS`
- Supported horizon: `PASS`
- OOD integration: `PASS`
- Inference: `TECHNICAL_SHADOW_PASS`
- Future leakage: `PASS_NO_FUTURE_HORIZON_READ`

## Non-claims

No medication residual / intervention / TE / Safety Boundary / QSP / PKPD.
SCIENTIFIC_CROSS_SOURCE_PASS=false
PRODUCTION_READINESS=NOT_CLAIMED
SECURITY_STAGE_STATUS=PAUSED_NOT_ACCEPTED_BY_OWNER

## TECHNICAL_PASS

`True`
