---
name: design-canonical-model
description: Design Stage 03 canonical clinical event model artifacts without implementation.
disable-model-invocation: true
---

Design the UHBSE Stage 03 canonical model per `docs/stage-03.md`.

This is **design only**. Do not create databases, DDL, or ETL.

Before editing:

1. Confirm Stage 01/02 gates are FINAL and verify-stage-02 PASS.
2. Read `artifacts/stage-02/entity-crosswalk.yaml` unresolved_mappings (17 items).
3. Read Stage 01/02 entity candidates for mapping evidence.

Produce or update artifacts under `artifacts/stage-03/` (content list = `STAGE03_CONTENT_ARTIFACTS`):

- canonical-model.yaml (29 required entities)
- provenance-contract.yaml
- temporal-contract.yaml
- state-snapshot-contract.yaml
- record-construction-contract.yaml
- source-a-mapping-draft.yaml
- source-b-mapping-draft.yaml
- field-semantics-register.yaml
- validation-rules.yaml
- unresolved-design-decisions.md
- stage-03-design-report.md (Report status: DRAFT)

Invariants:

- Subject is source-local; no global patient ID.
- Three layers: evidence, simulation_scenario, prediction.
- Raw values preserved; normalized fields nullable.
- Catalog facts ≠ patient facts.
- SubjectCharacteristic for stable demographics; no cross-source merge.
- Do not upgrade HYPOTHESIS/CANDIDATE to CONFIRMED clinical semantics.
- Preserve all 17 Stage 02 unresolved mappings in unresolved-design-decisions.md.
- ScenarioIntervention + ScenarioEvent precedence per scenario_event_precedence_contract.

After changes, run `audit --root . stage-03-check`.

Do not promote the design report to FINAL.
