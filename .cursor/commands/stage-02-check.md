# Stage 02 — Check

Verify Stage 02 gate readiness.

1. Read `docs/stage-02-acceptance.md`.
2. Execute skill **verify-stage-02**.
3. Confirm all required artifacts under `artifacts/stage-02/`.
4. Confirm `stage-02-report.md` has **Report status: DRAFT** before verify; promote to **FINAL** on PASS.

Required comparison deliverables:

- `artifacts/stage-02/schema-diff.yaml`
- `artifacts/stage-02/entity-crosswalk.yaml`
- `artifacts/stage-02/source-relationship-assessment.md`
- `artifacts/stage-02/identity-linkage-assessment.md`

If PASS: list unresolved questions, update `docs/current-stage.md`, stop — do not begin Stage 03.

If FAIL or PARTIAL: report missing items and required actions; do not restore or modify databases.
