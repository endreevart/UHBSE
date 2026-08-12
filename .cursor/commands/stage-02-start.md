# Stage 02 — Start

Second source audit and comparison. Read `AGENTS.md`, `docs/stage-02.md`, and
`docs/stage-02-acceptance.md`.

**Prerequisite:** Stage 01 gate **FINAL** (`artifacts/stage-01/stage-01-report.md`).

Run the pipeline in order:

1. **restore-second-source** — discover dump metadata; **stop for human confirmation before restore**
2. **profile-second-source** — structural + aggregate audit of source B (kgz)
3. **compare-source-audits** — `schema-diff.yaml`, `entity-crosswalk.yaml`
4. **assess-source-relationship** — `source-relationship-assessment.md`, `identity-linkage-assessment.md`
5. Create `artifacts/stage-02/stage-02-report.md` with **Report status: DRAFT** — `audit draft-report --stage 02`

## Hard stops

- Do **not** restore `kgz-20231204.dump` without explicit user confirmation.
- Do **not** merge databases or assume patients are the same across sources.
- Do **not** modify source A or source B (no DDL/DML).
- Do **not** commit dump files.
- Do **not** begin simulator or ML work.

## Immutable local dumps (do not delete)

- `dumps/stage_magerya_api.dump`
- `kgz-20231204.dump`
