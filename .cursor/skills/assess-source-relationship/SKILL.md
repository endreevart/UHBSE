---
name: assess-source-relationship
description: Assess system-level relationship and patient identity linkage between sources A and B.
disable-model-invocation: true
---

Read `docs/stage-02.md` and comparison outputs from skill **compare-source-audits**.

Determine how source A and source B may relate as **database systems** and whether
cross-source **patient identity linkage** is supported — without merging records
and without assuming equal patients.

## Inputs

- `artifacts/stage-02/schema-diff.yaml`
- `artifacts/stage-02/entity-crosswalk.yaml`
- Stage 01 and Stage 02 entity/relation artifacts
- Approved aggregate evidence from `artifacts/stage-01/evidence/` and `artifacts/stage-02/evidence/`

Prerequisite: skill **compare-source-audits** completed.

## System relationship assessment

Write `artifacts/stage-02/source-relationship-assessment.md`:

1. Executive summary (hypothesis, not conclusion of patient sameness).
2. Schema overlap statistics (table/column counts, shared naming patterns).
3. Structural lineage indicators (shared table names, FK shapes, version markers).
4. Temporal/population hints from **aggregates only** (date ranges, row counts — no row samples).
5. Selected hypothesis code(s) with evidence:

   | Code | Use when |
   |------|----------|
   | `SHARED_LINEAGE` | Common application/version fork |
   | `PARALLEL_DEPLOYMENT` | Similar model, independent instances |
   | `SUBSCHEMA` | One schema structurally contained in the other |
   | `OVERLAP_PARTIAL` | Substantial shared core, divergent extensions |
   | `INDEPENDENT` | Minimal structural overlap |
   | `UNKNOWN` | Insufficient evidence |

6. Competing hypotheses if evidence is weak.
7. Unresolved questions.

## Identity linkage assessment

Write `artifacts/stage-02/identity-linkage-assessment.md`:

1. Whether candidate linkage keys exist structurally (column names/types — **not values**).
2. Whether aggregate-level hints suggest overlapping populations (without individual linkage).
3. Verdict using exactly one primary code:

   | Verdict | Meaning |
   |---------|---------|
   | `NO_CROSSWALK` | No safe candidate keys |
   | `STRUCTURAL_ONLY` | Shared ID-shaped columns; values not compared |
   | `AGGREGATE_HINT` | Population/time hints only — not individual linkage |
   | `LINKAGE_UNSUPPORTED` | Evidence against meaningful linkage |
   | `LINKAGE_PROVEN` | Only with explicit documented proof |

4. Explicit statement: **patients are not assumed equal across sources in Stage 02**.
5. What evidence would be required to upgrade verdict (for a future stage).
6. Unresolved questions.

## Constraints

- No row-level identifiers, names, or sample values in outputs.
- No canonical database design.
- No ML, simulator, or merge proposals.
- Every claim references an artifact or aggregate query record.

Planned CLI: `audit assess-relationship`
