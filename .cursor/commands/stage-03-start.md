# Stage 03 — Start (Design Phase)

Begin Canonical Clinical Event Model design.

1. Read `docs/stage-03.md` and `docs/stage-03-acceptance.md`.
2. Run preconditions: `audit --root . stage-03-check`
   - If preconditions FAIL, stop and report blockers.
3. Execute skill **design-canonical-model**.
4. Ensure `artifacts/stage-03/` contains all design deliverables.
5. Keep `stage-03-design-report.md` at **Report status: DRAFT**.

Forbidden:

- canonical database, DDL, ETL, row migration;
- patient merge across sources;
- modifying Stage 01/02 artifacts;
- FINAL report promotion.

Stop after design artifacts and validation — do not start implementation.
