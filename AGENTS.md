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
