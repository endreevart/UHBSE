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
