# Stage 03 Design Report

Generated: 2026-08-08T11:33:26.590790+00:00

**Report status:** DRAFT

## Phase

**Canonical Clinical Event Model — Design Phase v0.7.5 (alignment candidate)**

Frozen accepted baseline remains **v0.7.4**. This report describes the **v0.7.5** alignment candidate only.

## v0.7.5 changes (alignment candidate — PARTIAL)

| Area | Change |
|------|--------|
| Temporal model | `temporal_precision` enum and `sequence_when_time_unknown` on Encounter/Observation |
| Subject key | Partial `subject_key_transformation_contract`; `key_reference` deferred (`DECISION_REQUIRED_SECRET_PROVIDER`) |
| Provider population | `provider_id` deferred in `record-construction-contract.yaml` for Source A appointment encounter |
| Conflict resolutions | New `artifact-conflict-resolutions.yaml` with `RESOLVED_PENDING_FINAL_RELEASE` entries |
| Mapping / semantics | Source A mapping, field-semantics register and validation rules updated for temporal precision |

## v0.7.4 preserved (frozen baseline)

SourceRecord field completeness, construction groups, HMAC locator semantics and publication-order invariants from v0.7.4 remain the accepted frozen baseline.

## Content integrity

Design content artifacts (12 files in candidate manifest) are hashed in `design-content-manifest.sha256`.
This report is **not** part of the content manifest.

Verification gate output: `stage-03-design-verification.json`

## Explicit non-actions

- No canonical database
- No SQL DDL
- No ETL or data loading
- No secret provider selection
- Design **not** promoted to FINAL
- Stage 01/02 unchanged
- Report **DRAFT**

**Alignment candidate v0.7.5 — four pre-live-load blockers remain OPEN.**
