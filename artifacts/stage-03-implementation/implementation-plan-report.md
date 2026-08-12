# Stage 03 Implementation Plan Report

Generated: 2026-08-11T08:00:00.000000+00:00

**Report status:** DRAFT

## Phase

**Stage 03 — Implementation Planning v0.3.6 alignment candidate**

## Design baseline

Design candidate: **v0.7.5 alignment** (DRAFT). Frozen accepted design baseline remains **v0.7.4**.

## Plan candidate

Plan candidate: **v0.3.6 alignment** (DRAFT, PARTIAL).

Frozen accepted implementation plan baseline remains **v0.3.5**, recovered as
`RECONSTRUCTED_FROM_ACCEPTED_MEMBERS` because the exact accepted ZIP SHA
`c93b8270ede688cda67cdcaed8e5522df3466e63572012e896fc59a38d89895c` is unavailable
in this workspace.

| Field | Value |
|-------|-------|
| Recovered Plan bundle | `stage-03-implementation-plan-v0.3.5-recovered-review.zip` |
| Recovered Plan SHA-256 | `33bc3daa253b5587963185f4e3552dd426abdcbbc1e47a2cd4466a4cca6035ee` |
| Invalid copy (superseded) | `stage-03-implementation-plan-v0.3.5-review.zip` marked `SUPERSEDED_INVALID_BASELINE_COPY` |

## v0.3.6 changes (alignment candidate — PARTIAL)

| Area | Change |
|------|--------|
| Loader runtime | Partial `canonical_loader_runtime_contract` in `security-runtime-plan.yaml` |
| Pilot / pipeline | `provider_id` population marked `DEFERRED_UNTIL_PROVIDER_CONSTRUCTION` |
| Design baseline pointer | Candidate `design-baseline-manifest.sha256` references Design v0.7.5 content |

## v0.3.5 corrections

- prior-stage integrity evaluation is strictly read-only; no verifier, gate or test repairs Stage 01/02
- restoring the accepted baseline moved to the explicit `audit restore-prior-stage-baseline --confirm` command
- `artifacts/stage-02/schema-profile-kgz.json` added to byte-controlled Stage 03 dependencies
- false Git provenance replaced by a content-addressed `baseline_source` descriptor with verified member hashes
- live source-relationship test marked `integration`, skips with explicit missing-prerequisite names, and runs in an isolated workspace copy
- release evidence split into `release-verification.json` with per-suite literal commands and counts
- `REPRODUCE.md` carries literal, complete commands and points to the correct evidence file
- published ZIP is validated once, then its SHA-256 is written to a `.sha256` sidecar with no rebuild

## Explicit non-actions

- No secret provider selection
- No canonical clinical row load
- No SQL DDL beyond accepted Changeset 01 migrations
- No ETL executed
- Plan **not** promoted to FINAL
- Four pre-live-load blockers remain OPEN

**implementation-plan-manifest.sha256:** verified at publish time.

**Planning alignment candidate v0.3.6 — PARTIAL.**
