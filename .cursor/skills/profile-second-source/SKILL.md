---
name: profile-second-source
description: Run Stage 01-class structural and aggregate audit on source B (kgz).
disable-model-invocation: true
---

Read `AGENTS.md`, `docs/stage-02.md`, and skill **profile-postgres-source**.

Profile exactly one configured PostgreSQL source: **source B** (kgz).

Prerequisite: skill **restore-second-source** completed and
`artifacts/stage-02/source-b-audit.json` exists.

Local profiling code may read complete rows in the local runtime.
Raw values must not be printed, logged, or returned to Cursor.

## Order

1. Validate read-only access to source B.
2. Record PostgreSQL version and database metadata.
3. Discover schemas, tables, views, and materialized views.
4. Discover columns, data types, PKs, FKs, and indexes.
5. Produce estimated row counts.
6. Classify potentially sensitive columns from names and types.
7. Run approved profiling (aggregates, relationship detection, local row-level analysis).
8. Classify candidate clinical entities (same entity types as Stage 01).
9. Generate sanitized artifacts for Git and agent context.

Stop if write permissions or unsafe configuration are detected on source B.

## Outputs

| Artifact | Path |
|----------|------|
| Schema profile | `artifacts/stage-02/schema-profile-kgz.json` |
| Entity candidates | `artifacts/stage-02/entity-candidates-kgz.yaml` |
| Relation graph | `artifacts/stage-02/relation-graph-kgz.md` |
| Unknown semantics | `artifacts/stage-02/unknown-semantics-kgz.md` |
| Evidence | `artifacts/stage-02/evidence/` |

Do not mark entity mappings as confirmed unless evidence exists.

Planned CLI:

- `audit profile-source --source kgz`
- `audit classify-entities --source kgz`
