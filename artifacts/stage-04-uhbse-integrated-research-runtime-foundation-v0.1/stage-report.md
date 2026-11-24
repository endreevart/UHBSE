# UHBSE Integrated Research Runtime Foundation v0.1

Report status: FINAL

Not a clinical product. Not for diagnosis, treatment, or production deployment.
Negative scientific results are allowed when integrity and privacy gates pass.

## Phase 0 — Joint Rollout v0.2 audit

v0.2 publication integrity may remain PASS. The three published joint routes are **not** transferred.

- `V02_JOINT_DEFECT_REPRODUCTION_STATUS`=REPRODUCED
- `PRIOR_JOINT_FOUNDATION_STATUS`=NOT_ACCEPTED_EVIDENCE_AND_RUNTIME_CORRECTION_REQUIRED
- Scalar `run_engine_shadow()` was published as `TECHNICAL_SHADOW_PASS` without copula inference
- Energy/Variogram were computed in raw mixed units
- Panels were horizon-aligned, not strictly co-observed
- D1 used in-sample residuals; acceptance was pointwise Energy without paired group-bootstrap CI
- Source A 30d validation CRPS D1 was worse than D0
- Same-process replay was labelled cross-process
- `JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT` recounts from zero: **0**

v0.2 ZIP is not rewritten.

## Corrected joint foundation

Primary panels: `STRICT_COOBSERVED_TARGET_PANEL`. Asynchronous horizon vectors are diagnostic only.
D1 residuals are train group-OOF. Energy and Variogram are normalized only.
Acceptance requires paired effective-group bootstrap CI upper bound `< 0`.

Result: `JOINT_DEPENDENCE_FOUNDATION_STATUS`=EVALUATED_NOT_ACCEPTED
(small Energy deltas; CI includes 0; seed/path-count sign is not stable).

Engine loads disk payload, emits `paths × outcomes`, uses explicit D0 when D1 is not accepted,
and replays in two subprocesses.

## Other streams

- Source Integration Plane built; future sources remain `NOT_CONFIGURED`
- Technical recorded-event classifier: no incremental signal vs prevalence baseline
- QSP/PKPD: synthetic reference fixtures only; not mixed with patient trajectories
- Research workbench: synthetic default, local/private
- External validation protocol: `SERUM_FREE_T3_RETROSPECTIVE_EXTERNAL_VALIDATION` ready for provider scoping (not a PASS; IROS not contacted)

## Non-claims

No A↔B identity merge, no unverified unit conversion, no real-drug PKPD, no treatment-effect or causal analysis, no Safety Boundary, no clinical or production claims.
