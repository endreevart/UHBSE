# Stage 03 — Check (Design Phase)

Verify Stage 03 design gate readiness.

1. Read `docs/stage-03-acceptance.md`.
2. Execute skill **verify-stage-03-design**.
3. Run: `audit --root . stage-03-check`
4. Confirm all artifacts under `artifacts/stage-03/`.
5. Confirm `stage-03-design-report.md` has **Report status: DRAFT**.

Required content artifacts (see `STAGE03_CONTENT_ARTIFACTS` in verifier):

- `canonical-model.yaml`
- `provenance-contract.yaml`
- `temporal-contract.yaml`
- `state-snapshot-contract.yaml`
- `record-construction-contract.yaml`
- `source-a-mapping-draft.yaml`
- `source-b-mapping-draft.yaml`
- `field-semantics-register.yaml`
- `validation-rules.yaml`
- `unresolved-design-decisions.md`
- `design-content-manifest.sha256`

If PASS: update `docs/current-stage.md`, list unresolved design decisions, stop — do not start implementation or promote report to FINAL.

If FAIL: report missing items; do not create databases or modify Stage 01/02.
