---
name: compare-source-audits
description: Compare Stage 01 source A audit with Stage 02 source B audit.
disable-model-invocation: true
---

Read `docs/stage-02.md` and `docs/stage-02-acceptance.md`.

Compare baseline artifacts from source A with source B audit outputs.
Do not query row-level identifiers for cross-source patient matching.

## Inputs

**Source A (baseline — Stage 01):**

- `artifacts/stage-01/schema-profile.json`
- `artifacts/stage-01/entity-candidates.yaml`
- `artifacts/stage-01/relation-graph.md`
- `artifacts/stage-01/unknown-semantics.md`

**Source B (Stage 02):**

- `artifacts/stage-02/schema-profile-kgz.json`
- `artifacts/stage-02/entity-candidates-kgz.yaml`
- `artifacts/stage-02/relation-graph-kgz.md`
- `artifacts/stage-02/unknown-semantics-kgz.md`

Prerequisite: skill **profile-second-source** completed.

## Tasks

### Schema diff

Produce `artifacts/stage-02/schema-diff.yaml`:

- tables/views in A only, B only, or both;
- column-level diffs for shared tables (type, nullability, default);
- PK/FK/index presence diffs;
- proposed renames as **hypothesis** with confidence, never as fact.

### Entity crosswalk

Produce `artifacts/stage-02/entity-crosswalk.yaml`:

- candidate mappings for each Stage 01 entity type (patients, visits, labs, etc.);
- per mapping: `source_a_table`, `source_b_table`, `confidence`, `evidence_refs`;
- confidence values: `UNKNOWN`, `STRUCTURAL_MATCH`, `NAME_MATCH`, `EVIDENCE_BACKED`.

## Rules

- Structural similarity ≠ semantic equivalence.
- Table/column name match ≠ confirmed entity mapping.
- Every mapping must cite evidence (schema metadata, FK pattern, aggregate signature).
- Do not assume patients in A and B are the same person.
- Mark undocumented semantics **UNKNOWN**.

Planned CLI: `audit compare-sources`
