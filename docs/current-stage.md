# Current stage

**Stage:** 01 — Single source audit  
**Status:** in progress  
**Last updated:** 2026-07-31

## Objective

Inspect one clinic database (`magerya_api`) and produce a reproducible,
aggregate, de-identified data audit.

## Progress

| Task | Status | Notes |
|------|--------|-------|
| Bootstrap audit infrastructure | done | CLI, config, tests (27 passing) |
| Source bootstrap / connectivity | not started | `audit connection-check` |
| Schema profiling | not started | `audit profile-source` |
| Entity classification | not started | `audit classify-entities` |
| Evidence artifacts | not started | |
| Acceptance review | not started | `audit verify-stage` |

## Artifacts

| File | Status |
|------|--------|
| `artifacts/stage-01/source-audit.json` | missing |
| `artifacts/stage-01/schema-profile.json` | missing |
| `artifacts/stage-01/entity-candidates.yaml` | missing |
| `artifacts/stage-01/relation-graph.md` | missing |
| `artifacts/stage-01/unknown-semantics.md` | missing |
| `artifacts/stage-01/stage-01-report.md` | missing |

## Unresolved questions

_None yet._

## Gate

Stage 01 gate: **not reached**

See [stage-01-acceptance.md](stage-01-acceptance.md) for exit criteria.
