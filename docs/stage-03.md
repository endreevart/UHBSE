# Stage 03 — Canonical Clinical Event Model (Design Phase)

**Status:** in progress (design only)  
**Last updated:** 2026-08-01

## Objective

Design a minimal canonical clinical event model that can later transform Source A
(`magerya_api`) and Source B (`kgz_raw`) without losing provenance, time,
uncertainty, or raw source values.

## Non-goals (design phase)

Stage 03 design must **not**:

- create a canonical database;
- write SQL DDL;
- migrate or transform live rows (ETL);
- merge patients across sources;
- create a global patient ID;
- modify Stage 01/02 artifacts;
- promote CANDIDATE/HYPOTHESIS mappings to CONFIRMED clinical semantics;
- implement simulation or prediction engines.

## Prerequisites

1. Stage 01 gate **FINAL** (`artifacts/stage-01/stage-01-report.md`).
2. Stage 02 gate **FINAL** (`artifacts/stage-02/stage-02-report.md`).
3. `verify-stage-02.json` status **PASS**.
4. Valid `stage-02-final-manifest.sha256`.
5. All 17 Stage 02 unresolved mappings available in `entity-crosswalk.yaml`.
6. Population overlap **NOT_ESTIMABLE**; Subject B **SUBJECT_ROOT_CANDIDATE**.

## Architectural layers

| Layer | Record origins | Purpose |
|-------|----------------|---------|
| **Evidence** | OBSERVED … IMPUTED | Audited source facts |
| **Simulation scenario** | SYNTHETIC | Hypothetical future exposures |
| **Prediction** | PREDICTED | Model outputs with uncertainty |

These layers must not be merged into a single undifferentiated fact type.

## Workflow

1. Verify preconditions (`audit stage-03-check`).
2. Review or extend design artifacts under `artifacts/stage-03/`.
3. Run design validation (`audit stage-03-check`).
4. Keep `stage-03-design-report.md` at **DRAFT** until a future implementation gate.

## Deliverables

Content artifacts are defined by `STAGE03_CONTENT_ARTIFACTS` in `src/human_simulator/stage03/constants.py`
(current count derived from constants, hashed in `design-content-manifest.sha256`).

| Artifact | Purpose |
|----------|---------|
| `canonical-model.yaml` | 29 required entities including SubjectCharacteristic |
| `provenance-contract.yaml` | Lineage and mapping status rules |
| `temporal-contract.yaml` | Time field semantics |
| `state-snapshot-contract.yaml` | Snapshot construction design contract |
| `record-construction-contract.yaml` | Canonical record construction from source rows |
| `source-a-mapping-draft.yaml` | Source A field mapping draft |
| `source-b-mapping-draft.yaml` | Source B field mapping draft |
| `field-semantics-register.yaml` | Field meanings and forbidden identifiers |
| `validation-rules.yaml` | Automated validation rule registry |
| `unresolved-design-decisions.md` | Carried Stage 02 gaps |
| `stage-03-design-report.md` | Design report (DRAFT; not in content manifest) |
| `design-content-manifest.sha256` | Integrity manifest for content artifacts only (excludes self) |
| `stage-03-design-verification.json` | Gate output (not in content manifest) |

## Cursor tooling

- Rule: `.cursor/rules/07-canonical-model.mdc`
- Skills: `design-canonical-model`, `verify-stage-03-design`
- Commands: `stage-03-start`, `stage-03-check`

## Next phase (not started)

Implementation phase would add transforms, optional derived DB, and a separate
FINAL gate. Design phase stops at artifact completion and validation.
