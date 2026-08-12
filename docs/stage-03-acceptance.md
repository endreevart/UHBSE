# Stage 03 — Design acceptance criteria

**Phase:** Canonical Clinical Event Model — Design only  
**Report status on completion:** DRAFT (not FINAL)

## Preconditions

- [ ] Stage 01 report **FINAL**
- [ ] Stage 02 report **FINAL**
- [ ] `verify-stage-02.json` status **PASS**
- [ ] `stage-02-final-manifest.sha256` validates
- [ ] 17 unresolved mappings present in crosswalk
- [ ] Population overlap **NOT_ESTIMABLE**
- [ ] Subject B **SUBJECT_ROOT_CANDIDATE**

## Design artifacts

Content artifact list matches `STAGE03_CONTENT_ARTIFACTS` in constants (see verifier):

- [ ] `artifacts/stage-03/canonical-model.yaml`
- [ ] `artifacts/stage-03/canonical-id-contract.yaml`
- [ ] `artifacts/stage-03/provenance-contract.yaml`
- [ ] `artifacts/stage-03/temporal-contract.yaml`
- [ ] `artifacts/stage-03/state-snapshot-contract.yaml`
- [ ] `artifacts/stage-03/record-construction-contract.yaml`
- [ ] `artifacts/stage-03/source-a-mapping-draft.yaml`
- [ ] `artifacts/stage-03/source-b-mapping-draft.yaml`
- [ ] `artifacts/stage-03/field-semantics-register.yaml`
- [ ] `artifacts/stage-03/validation-rules.yaml`
- [ ] `artifacts/stage-03/unresolved-design-decisions.md`
- [ ] `artifacts/stage-03/stage-03-design-report.md`
- [ ] `artifacts/stage-03/design-content-manifest.sha256`

## Model requirements

- [ ] Three layers: evidence, simulation_scenario, prediction
- [ ] All 29 required canonical entities defined (including SubjectCharacteristic)
- [ ] IdentityLinkEvidence excluded from minimal model
- [ ] Subject identity source-local only
- [ ] Observation supports header/value via ObservationComponent
- [ ] Intervention types separated (medication, supplement, nutrition, activity)
- [ ] Catalog vs patient facts strictly separated
- [ ] ScenarioIntervention holds identity/defaults; ScenarioEvent applies timeline overrides
- [ ] `scenario_event_precedence_contract` documented in canonical model

## Contracts

- [ ] Provenance contract requires raw value retention
- [ ] Temporal contract forbids recorded_at substitution for missing clinical time
- [ ] State snapshot contract defines cutoff, no future leakage, age-at-snapshot rules
- [ ] Record construction contract defines full canonical record assembly
- [ ] Canonical ID contract specifies HMAC-SHA256 with domain separation and test vectors
- [ ] Source B `public.users` subject eligibility conservative (no row_filter always)
- [ ] All mapping `record_group` references resolve to construction groups
- [ ] Mapping collision policy explicit (record_group alone insufficient; no silent last-write-wins)
- [ ] Normalized fields nullable in mapping drafts
- [ ] Mapping statuses include evidence and lossiness
- [ ] Demographic/profile mappings use SubjectCharacteristic without clinical sex normalization

## Safety

- [ ] No global patient ID in artifacts
- [ ] No credentials or raw identifiers in design artifacts
- [ ] Stage 01/02 artifacts unchanged
- [ ] No canonical DB, DDL, or ETL

## Validation

- [ ] `audit stage-03-check` returns PASS
- [ ] `tests/test_verify_stage_03_design.py` passes
- [ ] All 17 Stage 02 unresolved items in `unresolved-design-decisions.md`
- [ ] No stale legacy manifest references in active Stage 03 docs/rules/skills/commands

## Stop conditions

On PASS: keep report **DRAFT**, update `docs/current-stage.md`, stop — do not
start implementation phase.

On FAIL: list missing items; do not create databases or modify prior stages.
