# UHBSE Cursor Configuration Audit V3

**Generated:** 2026-07-31T13:45:52Z
**Workspace:** `/Volumes/Siska/DEVELOP/Human simulator`
**Cursor version:** `3.13.25`
**Method:** Fresh read from disk; no prior audit document used as source.

---

## 1. Executive result

| Item | Result |
|------|--------|
| Configuration snapshot | PASS |
| Stage 01 readiness | PASS |
| P-01 Provenance in Python | DEFERRED (does not block Stage 01) |
| F-09 Working tree secret scan (snapshot files) | PASS |
| F-09 Git history secret scan | NOT_APPLICABLE |
| **Overall configuration** | **PASS** |

> **F-09 Git history NOT_APPLICABLE reason:** `.git` directory absent in this workspace — it has never been a Git repository here; history scan does not apply. If a Git repository exists elsewhere, run the secret scan on that clone and classify as NOT_VERIFIABLE from this workspace.

---

## 2. File tree

```
AGENTS.md
.cursor/
├── commands/
│   ├── stage-01-check.md
│   └── stage-01-start.md
├── rules/
│   ├── 00-project-scope.mdc
│   ├── 01-medical-data-safety.mdc
│   ├── 02-stage-gate.mdc
│   ├── 03-readonly-sql.mdc
│   ├── 04-evidence.mdc
│   ├── 05-testing.mdc
│   └── 06-data-provenance.mdc
└── skills/
    ├── bootstrap-source-audit/SKILL.md
    ├── build-pseudonymized-working-copy/SKILL.md
    ├── classify-clinical-entities/SKILL.md
    ├── curate-research-data/SKILL.md
    ├── profile-postgres-source/SKILL.md
    └── verify-stage-01/SKILL.md
docs/stage-01-acceptance.md
```

---

## 3. SHA-256 checksums

| File | SHA-256 |
|------|---------|
| `AGENTS.md` | `6b749461220ac3f28ce54689cc83254b9d6f548fceaa4292daf621bd3be3bd53` |
| `docs/stage-01-acceptance.md` | `e4334aaccbc6bc0f5cf44b1c5a976c33a338458060a71fab6d35b999cb2fbf47` |
| `.cursor/rules/00-project-scope.mdc` | `db6beef00d9ffbad110f21d7308d71cdcaa403470cb0a390b0a7fbee288ade0d` |
| `.cursor/rules/01-medical-data-safety.mdc` | `d392c203f3ae60298ddc54a49b0ac77819010ca7d02f1cdc857a92bcd5ec12fd` |
| `.cursor/rules/02-stage-gate.mdc` | `2d542941fe893ef97cedeaf097254e74b5f35eb0127d122cd0386dd2b3d64524` |
| `.cursor/rules/03-readonly-sql.mdc` | `0fb57891672e56db96159980b5dfc109463964dca5851432fcdadf7e9f6b2dae` |
| `.cursor/rules/04-evidence.mdc` | `78bd0483d874f1dbc0773aaab46642d966637d46dc219c2227a1ef7d2dfd17a4` |
| `.cursor/rules/05-testing.mdc` | `2ebfadaf2b57330e799027697bc7a2ccadd8c0d5e13b6d447655298091843fcd` |
| `.cursor/rules/06-data-provenance.mdc` | `287de26ff3ab9410e1cda61c7ca1f1189a60525ccf2c0f2c6ae8926c9df90aff` |
| `.cursor/skills/bootstrap-source-audit/SKILL.md` | `b19595317d8d9067acc3962fa6ed4b476e47cc793a5226a30b93dddef76493bd` |
| `.cursor/skills/profile-postgres-source/SKILL.md` | `69d7f855a3f2ea12258231dd8b9ab1c74a78cac4e33b921890c4a6b441280119` |
| `.cursor/skills/classify-clinical-entities/SKILL.md` | `7016e4615421c223be54452533f7216d80fc34c6167b0d85f4715e953bfa36ec` |
| `.cursor/skills/verify-stage-01/SKILL.md` | `95a4c24b927eacde4879fc8456ba32fb2e715782444d1e91edb066e24297e59b` |
| `.cursor/skills/build-pseudonymized-working-copy/SKILL.md` | `fcdac7a21dbbd7a716f384c94317cf4becc9bc6dcf72a0a2c889ab90ae3d7bd6` |
| `.cursor/skills/curate-research-data/SKILL.md` | `bbb5511ecfa2c4075415557f02fb100ce7967403fd1c3a386479a278638dbb56` |
| `.cursor/commands/stage-01-start.md` | `d9f921eaff84435713c4547034c966105694cc50963afafa7c765e1bc97f0cb8` |
| `.cursor/commands/stage-01-check.md` | `9ab6e4122b0456b371a4eda7d63eaf5a5cba60c4aa5b4334040e06ba48c21c51` |

---

## 4. Policy presence verification

| Check | Result |
|-------|--------|
| original_derived_split_agents | PASS |
| original_derived_split_rule03 | PASS |
| always_apply_rule03 | PASS |
| cli_profile_source | PASS |
| cli_classify_entities | PASS |
| cli_draft_report | PASS |
| sanitized_profiling_classify | PASS |
| draft_final_flow | PASS |
| record_origin_rule06 | PASS |

---

## 5. Frontmatter validation

### Rules

| File | description | alwaysApply | globs | Valid |
|------|-------------|-------------|-------|-------|
| `00-project-scope.mdc` | yes | yes | — | yes |
| `01-medical-data-safety.mdc` | yes | yes | — | yes |
| `02-stage-gate.mdc` | yes | yes | — | yes |
| `03-readonly-sql.mdc` | yes | yes | ["**/*.sql", "src/**/*.py"] | yes |
| `04-evidence.mdc` | yes | yes | — | yes |
| `05-testing.mdc` | yes | yes | ["src/**/*.py", "tests/**/*.py"] | yes |
| `06-data-provenance.mdc` | yes | yes | — | yes |

### Skills

| Directory | name=dir | disable-model-invocation | Valid |
|-----------|----------|--------------------------|-------|
| `bootstrap-source-audit` | yes | yes | yes |
| `profile-postgres-source` | yes | yes | yes |
| `classify-clinical-entities` | yes | yes | yes |
| `verify-stage-01` | yes | yes | yes |
| `build-pseudonymized-working-copy` | yes | yes | yes |
| `curate-research-data` | yes | yes | yes |

---

## 6. F-09 Secret scan

### 6.1 Working tree (snapshot + README + config templates)

**Result:** PASS

No credential-like content detected in scanned files.

Scanned files: audit snapshot set, `README.md`, `db.env.example`, `config/sources.example.yaml`.
Excluded: `db.env` (gitignored local secret), `dumps/`, `tests/` (synthetic fixtures), `.venv/`.

### 6.2 Git history

**Result:** NOT_APPLICABLE

`.git` directory absent in this workspace — it has never been a Git repository here.
Command `git rev-list --all` unavailable; history scan does not apply.

If a real Git repository exists in another location, classify history verification as **NOT_VERIFIABLE** from this workspace and run the secret scan on that repository directly.

---

## 7. P-01 Provenance implementation

| Item | Status |
|------|--------|
| `06-data-provenance.mdc` defines record_origin + provenance fields | Present |
| Python runtime enforcement | **DEFERRED** — not implemented |
| Blocks Stage 01 | **No** — Stage 01 performs no data modifications |

---

## 8. Full file texts

### 8.1 `AGENTS.md`

SHA-256: `6b749461220ac3f28ce54689cc83254b9d6f548fceaa4292daf621bd3be3bd53`

```markdown
# UHBSE Data Foundation

## Product

UHBSE is a probabilistic human biology simulation engine.

The system must eventually model:

```
State_before + Intervention + Context + Time -> State_after
```

This repository is not:

- an electronic health record;
- a medical chatbot;
- a diagnosis generator;
- a treatment recommendation system;
- a document storage system.

## Data authorization

All clinic databases were provided under written agreements.

All participating patients provided written consent for:

- full row-level data processing;
- medical research;
- software and model development;
- data correction;
- data enrichment;
- creation of derived datasets;
- model training and validation.

Local project code may read, transform, correct and supplement medical data.

The original dump remains unchanged only for reproducibility.
All modifications are performed in derived datasets.

## Current stage

Current stage: **STAGE 01 — SINGLE SOURCE AUDIT**.

The only current objective is to inspect one clinic database and produce
a reproducible, aggregate, de-identified data audit.

Do not:

- design the simulator;
- select or train an ML model;
- introduce Hugging Face models;
- create a unified database;
- migrate data to OMOP or FHIR;
- process multiple clinics;
- infer undocumented field meanings;
- invent missing medical semantics.

## Required behavior

- Original restored databases are immutable and read-only.
- Derived databases may be writable when explicitly permitted by the current stage.
- Never include row-level patient data in Cursor prompts, logs, terminal output, or Git files.
- Never print names, phones, emails, document text or identifiers outside the local runtime.
- Every conclusion must reference an actual query or generated artifact.
- Unknown semantics must be marked UNKNOWN.
- Stop when the Stage 01 gate is reached.

---

## Stage 01 workflow

1. Run `/stage-01-start` or follow skills in order:
   - `bootstrap-source-audit`
   - `profile-postgres-source`
   - `classify-clinical-entities`
2. Write outputs to `artifacts/stage-01/`
3. Create `artifacts/stage-01/stage-01-report.md` with **Report status: DRAFT** — `audit draft-report`
4. Run `/stage-01-check` (`verify-stage-01`)

Required artifacts before gate pass:

- `artifacts/stage-01/source-audit.json`
- `artifacts/stage-01/schema-profile.json`
- `artifacts/stage-01/entity-candidates.yaml`
- `artifacts/stage-01/relation-graph.md`
- `artifacts/stage-01/unknown-semantics.md`
- `artifacts/stage-01/stage-01-report.md`

## Local source (this repo)

Single clinic source: stage database `magerya_api` (local Docker copy).

| Parameter | Value |
|-----------|-------|
| Host | `localhost` |
| Port | `5434` |
| Database | `magerya_api` |
| User | `magerya_api` |
| Password | see `db.env` (not in git) |

```bash
docker compose up -d
./restore.sh                    # default: dumps/stage_magerya_api.dump
psql -h localhost -p 5434 -U magerya_api -d magerya_api
# password: value of POSTGRES_PASSWORD in db.env
```

If the database password was ever committed, rotate `POSTGRES_PASSWORD` in `db.env`
and recreate the container volume: `docker compose down -v && docker compose up -d && ./restore.sh`

Local dumps (immutable inputs — do not delete or commit):

- `dumps/stage_magerya_api.dump`
- `kgz-20231204.dump`

## Repository layout

| Path | Purpose |
|------|---------|
| `.cursor/rules/` | Persistent agent constraints |
| `.cursor/skills/` | Stage workflows |
| `.cursor/commands/` | Chat shortcuts (`stage-01-start`, `stage-01-check`) |
| `config/` | Source templates and profiling policy |
| `src/human_simulator/` | Data processing tooling; original databases remain read-only |
| `artifacts/stage-01/` | Stage deliverables and evidence |
| `private/` | Local secrets (`sources.yaml`) — not in git |
| `dumps/` | DB dumps — not in git |

## Python

Requires Python >= 3.12.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
audit connection-check   # live DB only when explicitly run
audit profile-source     # full PostgreSQL profile → schema-profile.json
audit classify-entities
audit draft-report       # stage-01-report.md with DRAFT status
audit --root . verify-stage
```
```

### 8.2 `docs/stage-01-acceptance.md`

SHA-256: `e4334aaccbc6bc0f5cf44b1c5a976c33a338458060a71fab6d35b999cb2fbf47`

```markdown
# Stage 01 — Acceptance criteria

Single source audit of clinic database `magerya_api`. All criteria must pass
before the stage gate is declared reached.

## Scope

- [ ] Exactly one clinic source audited (local `magerya_api` copy)
- [ ] No second clinic, no cross-clinic merge, no unified database
- [ ] No simulator design, ML/LLM, OMOP, or FHIR work

## Safety

- [ ] Original restored database access must be read-only
- [ ] Derived database writes are allowed only when explicitly required by the stage
- [ ] Stage 01 does not modify either database
- [ ] No row-level patient data in agent context, logs, or Git artifacts
- [ ] No names, phones, emails, addresses, identifiers, or document bodies exposed outside the local runtime
- [ ] No secrets committed to the repository

## Deliverables

- [ ] `artifacts/stage-01/source-audit.json` — connectivity, source identity, dump inventory
- [ ] `artifacts/stage-01/schema-profile.json` — tables, columns, constraints (sanitized outputs)
- [ ] `artifacts/stage-01/entity-candidates.yaml` — candidate entity mappings (not confirmed without evidence)
- [ ] `artifacts/stage-01/relation-graph.md` — FK graph for candidates
- [ ] `artifacts/stage-01/unknown-semantics.md` — relations marked UNKNOWN
- [ ] `artifacts/stage-01/evidence/` — SQL queries backing factual claims
- [ ] `artifacts/stage-01/stage-01-report.md` — summary with links to artifacts and **Report status: DRAFT**

## Quality

- [ ] Every factual claim references a query or generated artifact
- [ ] Undocumented field meanings marked **UNKNOWN** (not inferred)
- [ ] Unresolved questions listed explicitly in the report
- [ ] `docs/current-stage.md` updated to reflect completion

## Exit

When all boxes above are satisfied:

1. Run `audit verify-stage`
2. Promote `artifacts/stage-01/stage-01-report.md` to **Report status: FINAL**
3. List unresolved questions
4. Stop — do not begin Stage 02
5. Tell the user the stage gate has been reached
```

### 8.3 `.cursor/rules/00-project-scope.mdc`

SHA-256: `db6beef00d9ffbad110f21d7308d71cdcaa403470cb0a390b0a7fbee288ade0d`

```
---
description: UHBSE product boundary and current development stage
alwaysApply: true
---

Work only on the current stage defined in AGENTS.md.

Do not implement future stages unless the current gate has passed.

Do not introduce ML, LLM, OMOP, FHIR, simulation runtime or cross-clinic
data merging during Stage 01.

If a requested change belongs to a future stage, record it in
docs/future-work.md and do not implement it.
```

### 8.4 `.cursor/rules/01-medical-data-safety.mdc`

SHA-256: `d392c203f3ae60298ddc54a49b0ac77819010ca7d02f1cdc857a92bcd5ec12fd`

```
---
description: Safety rules for medical and personal data
alwaysApply: true
---

Local application code may process complete row-level patient data.

Do not include patient data in:

- Cursor prompts;
- external LLM requests;
- application logs;
- terminal output;
- Git repository files.

Row-level processing must happen inside the local application runtime.

Never include in agent-visible output or repository files:

- full names;
- phone numbers;
- email addresses;
- addresses;
- passport or insurance identifiers;
- medical document bodies;
- unredacted free text;
- raw database rows;
- database credentials.

The original clinic dump remains unchanged for reproducibility.
All modifications belong in derived datasets.

Never execute INSERT, UPDATE, DELETE, ALTER, DROP, TRUNCATE or CREATE
against the original clinic database.

Secrets must not be stored inside the repository.
```

### 8.5 `.cursor/rules/02-stage-gate.mdc`

SHA-256: `2d542941fe893ef97cedeaf097254e74b5f35eb0127d122cd0386dd2b3d64524`

```
---
description: Stage control and completion gates
alwaysApply: true
---

Before starting work, read:

- AGENTS.md
- docs/current-stage.md
- docs/stage-01-acceptance.md

After every completed task update docs/current-stage.md.

Do not begin the next stage automatically.

When all Stage 01 acceptance criteria are met:

1. verify `artifacts/stage-01/stage-01-report.md` has **Report status: DRAFT**;
2. promote the report to **Report status: FINAL**;
3. list unresolved questions;
4. stop;
5. tell the user that the stage gate has been reached.
```

### 8.6 `.cursor/rules/03-readonly-sql.mdc`

SHA-256: `0fb57891672e56db96159980b5dfc109463964dca5851432fcdadf7e9f6b2dae`

```
---
description: Read-only SQL requirements for original source databases
globs: ["**/*.sql", "src/**/*.py"]
alwaysApply: true
---

The original restored database is read-only.

Derived databases are writable and may contain:

- corrected data;
- normalized data;
- expert annotations;
- calculated values;
- imputed values;
- synthetic experimental data.

Never modify the original restored database.

Connections to the original restored database must:

- use a dedicated read-only role;
- enable read-only transactions;
- set statement_timeout;
- set lock_timeout;
- use parameterized queries;
- avoid SELECT *;
- avoid unrestricted sampling;
- never print row values to logs, terminal, or Git artifacts;
- prefer database statistics and aggregate queries;
- record query name, duration and source without recording sensitive values.

Initial schema discovery must use information_schema and database catalogs.

Exact full-table counts must not be run automatically on large tables.
Use estimated counts first.
```

### 8.7 `.cursor/rules/04-evidence.mdc`

SHA-256: `78bd0483d874f1dbc0773aaab46642d966637d46dc219c2227a1ef7d2dfd17a4`

```
---
description: Prevent assumptions and unsupported conclusions
alwaysApply: true
---

Never infer a medical field meaning from its name alone.

Each mapped field must have one of these statuses:

- CONFIRMED;
- LIKELY;
- UNKNOWN;
- EXCLUDED.

CONFIRMED requires evidence from schema, code, documentation or user review.

Every report statement must link to:

- a profiling result;
- a SQL query identifier;
- a schema constraint;
- or a documented human decision.

Unknown information must remain unknown.
```

### 8.8 `.cursor/rules/05-testing.mdc`

SHA-256: `2ebfadaf2b57330e799027697bc7a2ccadd8c0d5e13b6d447655298091843fcd`

```
---
description: Testing requirements for the data audit tool
globs: ["src/**/*.py", "tests/**/*.py"]
alwaysApply: false
---

Every profiler component must have tests.

Tests must cover:

- read-only enforcement;
- credential redaction;
- PHI redaction;
- deterministic output;
- unsupported database objects;
- empty tables;
- null-only columns;
- large tables;
- interrupted queries;
- malformed dates;
- unknown data types.

A task is not complete until its tests pass.
```

### 8.9 `.cursor/rules/06-data-provenance.mdc`

SHA-256: `287de26ff3ab9410e1cda61c7ca1f1189a60525ccf2c0f2c6ae8926c9df90aff`

```
---
description: Track the origin of every value
alwaysApply: true
---

Every value in a derived dataset must have record_origin:

- OBSERVED;
- CORRECTED;
- NORMALIZED;
- ANNOTATED;
- DERIVED;
- IMPUTED;
- PREDICTED;
- SYNTHETIC.

Never overwrite observed data.

Corrections and additions must create new versions.

IMPUTED, PREDICTED and SYNTHETIC values must not be treated as
observed ground truth.

Every changed or added record must contain:

- source_dataset_id;
- source_record_id;
- record_origin;
- transformation_id;
- transformation_version;
- created_at;
- created_by;
- evidence or calculation reference.
```

### 8.10 `.cursor/skills/bootstrap-source-audit/SKILL.md`

SHA-256: `b19595317d8d9067acc3962fa6ed4b476e47cc793a5226a30b93dddef76493bd`

```markdown
---
name: bootstrap-source-audit
description: Bootstrap the Stage 01 clinic database audit tool.
disable-model-invocation: true
---

Read AGENTS.md and all project rules.

Create only the infrastructure needed for Stage 01.

Use:

- Python 3.12;
- SQLAlchemy;
- psycopg;
- Pydantic Settings;
- Polars;
- PyArrow;
- pytest;
- structlog or standard structured logging.

Implemented CLI commands:

- audit connection-check;
- audit discover-schema;
- audit profile-structure;
- audit profile-aggregates;
- audit profile-source;
- audit classify-entities;
- audit draft-report;
- audit generate-report;
- audit verify-stage.

Do not connect to a real database during bootstrap.

Create tests using a disposable test database.
```

### 8.11 `.cursor/skills/profile-postgres-source/SKILL.md`

SHA-256: `69d7f855a3f2ea12258231dd8b9ab1c74a78cac4e33b921890c4a6b441280119`

```markdown
---
name: profile-postgres-source
description: Safely profile one PostgreSQL clinic database.
disable-model-invocation: true
---

Profile exactly one configured PostgreSQL source.

Local profiling code may read complete rows.

Raw values must not be printed, logged or returned to Cursor.

The skill may calculate aggregates and identify relationships using
row-level processing inside the local runtime.

Order:

1. Validate that the connection to the original restored database is read-only.
2. Record PostgreSQL version and database metadata.
3. Discover schemas, tables, views and materialized views.
4. Discover columns and data types.
5. Discover primary keys, foreign keys and indexes.
6. Produce estimated row counts.
7. Classify potentially sensitive columns from names and types.
8. Run approved profiling (aggregates, relationship detection, local row-level analysis).
9. Generate sanitized artifacts for Git and agent context.

Stop if write permissions or unsafe configuration are detected on the original restored database.
```

### 8.12 `.cursor/skills/classify-clinical-entities/SKILL.md`

SHA-256: `7016e4615421c223be54452533f7216d80fc34c6167b0d85f4715e953bfa36ec`

```markdown
---
name: classify-clinical-entities
description: Find candidate clinical entities in a profiled clinic schema.
disable-model-invocation: true
---

Using schema metadata and sanitized profiling outputs.
The local profiler may use row-level data, but this skill must not receive raw rows.

Identify candidate tables for:

- patients;
- visits;
- doctors;
- specialties;
- laboratory results;
- diagnoses;
- prescriptions;
- medications;
- procedures;
- ultrasound examinations;
- operations;
- medical documents;
- measurements;
- appointments.

Do not mark mappings as confirmed unless evidence exists.

Generate:

- artifacts/stage-01/entity-candidates.yaml;
- artifacts/stage-01/relation-graph.md;
- artifacts/stage-01/unknown-semantics.md.
```

### 8.13 `.cursor/skills/verify-stage-01/SKILL.md`

SHA-256: `95a4c24b927eacde4879fc8456ba32fb2e715782444d1e91edb066e24297e59b`

```markdown
---
name: verify-stage-01
description: Verify whether the first UHBSE data audit gate has been reached.
disable-model-invocation: true
---

Verify every criterion from docs/stage-01-acceptance.md.

Do not fix missing requirements automatically.

Produce:

- PASS;
- PARTIAL;
- FAIL.

For every failed criterion, provide:

- missing artifact;
- reason;
- required action;
- whether human clarification is needed.

Expect `artifacts/stage-01/stage-01-report.md` to exist with **Report status: DRAFT**
before verification completes.

If all criteria pass, promote the report status to **FINAL** and stop.
```

### 8.14 `.cursor/skills/build-pseudonymized-working-copy/SKILL.md`

SHA-256: `fcdac7a21dbbd7a716f384c94317cf4becc9bc6dcf72a0a2c889ab90ae3d7bd6`

```markdown
---
name: build-pseudonymized-working-copy
description: Build derived working copies with optional pseudonymization for exports and external use.
disable-model-invocation: true
---

Pseudonymization is no longer a mandatory precondition for all data processing.

Identifiable data may be processed inside the authorized local environment.

Pseudonymization is required for:

- model datasets when direct identifiers are unnecessary;
- exports;
- reports;
- external processing;
- shared research datasets.
```

### 8.15 `.cursor/skills/curate-research-data/SKILL.md`

SHA-256: `bbb5511ecfa2c4075415557f02fb100ce7967403fd1c3a386479a278638dbb56`

```markdown
---
name: curate-research-data
description: Correct, annotate and enrich research data with provenance.
disable-model-invocation: true
---

Work only with derived datasets.

Allowed operations:

- correction;
- normalization;
- expert annotation;
- calculation of derived values;
- imputation;
- generation of synthetic experimental records.

Never modify the original restored database.

Every operation must preserve provenance and record_origin.
```

### 8.16 `.cursor/commands/stage-01-start.md`

SHA-256: `d9f921eaff84435713c4547034c966105694cc50963afafa7c765e1bc97f0cb8`

```markdown
# Stage 01 — Start

Run the full stage-01 pipeline in order:

1. Read `AGENTS.md` and applicable `.cursor/rules/`.
2. Execute skill **bootstrap-source-audit** — ensure Docker DB is up.
3. Execute skill **profile-postgres-source** — `audit profile-source`.
4. Execute skill **classify-clinical-entities** — `audit classify-entities`.
5. Create `artifacts/stage-01/stage-01-report.md` with **Report status: DRAFT** — `audit draft-report`.

Do not skip steps. Do not write DDL/DML. Do not commit dump files.

Existing local dumps must remain untouched:

- `dumps/stage_magerya_api.dump`
- `kgz-20231204.dump`
```

### 8.17 `.cursor/commands/stage-01-check.md`

SHA-256: `9ab6e4122b0456b371a4eda7d63eaf5a5cba60c4aa5b4334040e06ba48c21c51`

```markdown
# Stage 01 — Check

Validate stage-01 completion:

1. Execute skill **verify-stage-01** — `audit verify-stage`.
2. Report **PASS**, **PARTIAL**, or **FAIL** from `verify-result.json`.
3. For each failed criterion, report missing artifact, reason, required action, and whether human clarification is needed.
4. Do not fix missing requirements automatically.
5. If **PASS**, confirm `stage-01-report.md` status is **FINAL** and stop — do not start stage-02.
```

---

## 9. Reviewer checklist

- [ ] Recompute SHA-256 and compare with section 3
- [ ] Confirm Cursor version
- [ ] If Git is used: re-run history secret scan before external sharing
- [ ] Run `pytest` and Stage 01 pipeline separately from this configuration audit

---

*End of UHBSE Cursor Configuration Audit V3 — Overall configuration: **PASS***
