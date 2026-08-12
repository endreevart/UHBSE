# Plan Canonical Implementation

Use when authoring or editing Stage 03 implementation planning artifacts.

## Scope

Planning only. Do not create databases, DDL, or ETL code.

## Steps

1. Read design baseline **v0.7.5** under `artifacts/stage-03/`.
2. Edit implementation planning artifacts for **v0.3.6** under `artifacts/stage-03-implementation/`.
3. Keep pilot Source A only unless explicitly expanding scope in a new plan version.
4. Track open decisions in `unresolved-implementation-decisions.yaml`.
5. Run `audit --root . stage-03-implementation-plan-check`.
6. Keep `implementation-plan-report.md` as DRAFT.

## Key files

- `pilot-slice.yaml` — entities and construction groups
- `pipeline-plan.yaml` — load order, contracts, idempotency
- `validation-plan.yaml` — reconciliation checks
- `security-runtime-plan.yaml` — HMAC and secrets policy
- `unresolved-implementation-decisions.yaml` — planning decisions
