# Stage 02 — Second source audit and comparison

**Status:** planned (do not start until Stage 01 gate is **FINAL**)  
**Last updated:** 2026-07-31

## Objective

Audit a second immutable clinic database from `kgz-20231204.dump`, compare it
with the Stage 01 audit of `dumps/stage_magerya_api.dump`, and produce
evidence-backed assessments of schema overlap and possible source relationship —
without merging records, without a canonical database, and without assuming
patient identity equivalence.

## Sources

| ID | Dump file | Stage 01 role | Stage 02 role |
|----|-----------|---------------|---------------|
| **A** | `dumps/stage_magerya_api.dump` | Primary audited source (`magerya_api`) | Baseline artifacts in `artifacts/stage-01/` |
| **B** | `kgz-20231204.dump` | Listed, not audited | Second immutable source to restore and audit |

Both dumps remain local, uncommitted, and unchanged on disk.

## Non-goals

Stage 02 must **not**:

- merge or deduplicate patient records across sources;
- create a unified or canonical database;
- treat patients as the same person without explicit, documented proof;
- design the simulator, ML models, or LLM pipelines;
- map to OMOP, FHIR, or other exchange standards;
- modify either original restored database;
- run restoration of source B without explicit human confirmation.

## Prerequisites

1. Stage 01 gate reached: `artifacts/stage-01/stage-01-report.md` has **Report status: FINAL**.
2. Stage 01 baseline artifacts present and verified:
   - `artifacts/stage-01/schema-profile.json`
   - `artifacts/stage-01/entity-candidates.yaml`
   - `artifacts/stage-01/relation-graph.md`
   - `artifacts/stage-01/unknown-semantics.md`
3. Local dumps intact:
   - `dumps/stage_magerya_api.dump`
   - `kgz-20231204.dump`
4. Human confirmation received before any restore of source B (see **Confirmation gate**).

## Infrastructure plan (not executed yet)

Source A and source B must remain **separate immutable PostgreSQL instances**
(or separate databases with isolated credentials and ports). Source A keeps the
existing Stage 01 layout; source B gets its own container, volume, and connection
profile.

### Proposed layout

| Source | Service (proposed) | Host port | Database (TBD) | Restore target |
|--------|-------------------|-----------|----------------|----------------|
| A | `mg-db` (existing) | `5434` | `magerya_api` | `./restore.sh dumps/stage_magerya_api.dump` |
| B | `kgz-db` (new) | `5435` | TBD from dump metadata | `./restore-kgz.sh` (new script) |

**TBD before restore:** database name, owner role, and extensions inside
`kgz-20231204.dump` — discover with `pg_restore --list kgz-20231204.dump`
and dry-run connectivity checks. Do not guess.

### Configuration additions (implementation phase)

- Extend `docker-compose.yml` with read-only-oriented second service.
- Add `db-kgz.env.example` (credentials local only, not in git).
- Extend `config/sources.example.yaml` with `local_kgz` connection block.
- Add `restore-kgz.sh` that restores **only** into the B container/volume.

### Confirmation gate

**Restoration of `kgz-20231204.dump` is forbidden until the user explicitly confirms.**

The agent must:

1. Present the planned service name, port, database name, and restore script.
2. Confirm disk space (~1.5 GB dump + expanded DB).
3. Wait for user approval (e.g. reply “confirm restore” or run `/stage-02-start` step 1 with confirmation).

No `docker compose up` for `kgz-db`, no `pg_restore`, and no volume creation for B
before that approval.

## Workflow

Execute skills and commands in order. Do not skip steps.

```
/stage-02-start
  │
  ├─ 1. restore-second-source          [CONFIRMATION REQUIRED]
  ├─ 2. profile-second-source          (structure + aggregates, same as Stage 01)
  ├─ 3. compare-source-audits          → schema-diff, entity-crosswalk
  ├─ 4. assess-source-relationship     → relationship type, identity-linkage-assessment
  └─ 5. draft-report                   → stage-02-report.md (DRAFT)

/stage-02-check
  └─ verify-stage-02                    → promote to FINAL on PASS
```

### Step 1 — Restore second source

Skill: **restore-second-source**

- Verify dump file exists and is PostgreSQL custom format.
- Discover dump metadata (DB name, encoding, extensions) without restoring rows to A.
- After human confirmation: start B container, restore dump, verify read-only access.
- Write `artifacts/stage-02/source-b-audit.json`.

### Step 2 — Audit source B (same class as Stage 01)

Skill: **profile-second-source**

Reuses the Stage 01 profiling approach (structure + aggregates + entity classification)
against source B only:

- `artifacts/stage-02/schema-profile-kgz.json`
- `artifacts/stage-02/entity-candidates-kgz.yaml`
- `artifacts/stage-02/relation-graph-kgz.md`
- `artifacts/stage-02/unknown-semantics-kgz.md`
- `artifacts/stage-02/evidence/` — sanitized query records

Local runtime may read full rows; Git and agent artifacts remain aggregate/sanitized.

### Step 3 — Compare audits

Skill: **compare-source-audits**

Compare Stage 01 baseline (source A) with Stage 02 profile (source B):

| Output | Content |
|--------|---------|
| `artifacts/stage-02/schema-diff.yaml` | Tables/columns/PK/FK/indexes present in A only, B only, or both; type mismatches; renames **hypothesis only** |
| `artifacts/stage-02/entity-crosswalk.yaml` | Candidate entity table mappings A↔B with confidence: `UNKNOWN`, `STRUCTURAL_MATCH`, `NAME_MATCH`, `EVIDENCE_BACKED` |

Rules:

- Structural similarity ≠ semantic equivalence.
- Column/table name match ≠ confirmed entity mapping.
- Every mapping cites evidence (schema hash, FK pattern, aggregate signature).

### Step 4 — Relationship and identity assessment

Skill: **assess-source-relationship**

| Output | Content |
|--------|---------|
| `artifacts/stage-02/source-relationship-assessment.md` | Hypothesis of how A and B relate as **systems**, not people |
| `artifacts/stage-02/identity-linkage-assessment.md` | Whether cross-source patient linkage is supported, inconclusive, or unsupported |

Allowed **system-level** relationship hypotheses (pick best supported; allow multiple if evidence is weak):

| Code | Meaning |
|------|---------|
| `SHARED_LINEAGE` | Schemas suggest common application/version fork |
| `PARALLEL_DEPLOYMENT` | Similar model, independent instances |
| `SUBSCHEMA` | B (or A) appears structurally contained in the other |
| `OVERLAP_PARTIAL` | Substantial shared tables but divergent extensions |
| `INDEPENDENT` | Minimal or no structural overlap |
| `UNKNOWN` | Insufficient evidence |

Identity linkage verdicts (patient level):

| Verdict | Meaning |
|---------|---------|
| `NO_CROSSWALK` | No safe candidate keys for linkage |
| `STRUCTURAL_ONLY` | Shared ID columns exist; values not compared or not comparable |
| `AGGREGATE_HINT` | Population/time/statistical hints only; **not** individual linkage |
| `LINKAGE_UNSUPPORTED` | Evidence argues against meaningful linkage |
| `LINKAGE_PROVEN` | Only if explicit documented proof exists (expected: rare/absent in Stage 02) |

**Never** output row-level identifiers, names, or sample values in assessments.

### Step 5 — Report and gate

- `artifacts/stage-02/stage-02-report.md` — **Report status: DRAFT**, then **FINAL** after verify.
- Run `/stage-02-check` (`verify-stage-02`).

## Planned CLI extensions (implementation phase)

These commands will be added to the `audit` CLI; skills reference them:

| Command | Purpose |
|---------|---------|
| `audit restore-second-source --confirm` | Restore B after confirmation flag |
| `audit profile-source --source kgz` | Profile source B |
| `audit classify-entities --source kgz` | Entity candidates for B |
| `audit compare-sources` | schema-diff + entity-crosswalk |
| `audit assess-relationship` | relationship + identity-linkage assessments |
| `audit draft-report --stage 02` | DRAFT report |
| `audit verify-stage --stage 02` | Gate verification |

Until implemented, skills may use documented manual steps with the same artifact paths.

## Artifact tree

```
artifacts/stage-02/
├── source-b-audit.json
├── schema-profile-kgz.json
├── entity-candidates-kgz.yaml
├── relation-graph-kgz.md
├── unknown-semantics-kgz.md
├── schema-diff.yaml
├── entity-crosswalk.yaml
├── source-relationship-assessment.md
├── identity-linkage-assessment.md
├── stage-02-report.md
└── evidence/
```

## Safety

- Both original restored databases: **read-only**.
- No DDL/DML on A or B during Stage 02.
- No row-level PHI in Cursor context, logs, or Git.
- Comparisons use schema metadata and approved aggregates only in agent-facing outputs.
- Conclusions marked **UNKNOWN** when semantics are undocumented.

## Exit

Stage 02 gate reached when all criteria in [stage-02-acceptance.md](stage-02-acceptance.md)
pass and `stage-02-report.md` is **FINAL**. Stop — do not begin Stage 03 automatically.

## Open questions (resolve during Stage 02)

1. Exact database name and role inside `kgz-20231204.dump`.
2. Whether B requires PostGIS or other extensions (A uses PostGIS 14).
3. Whether A and B share application version markers in schema/table naming.
4. Whether any candidate linkage keys exist without exposing row-level values.
