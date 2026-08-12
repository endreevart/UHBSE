---
name: verify-stage-02
description: Verify whether the Stage 02 second-source comparison gate has been reached.
disable-model-invocation: true
---

Verify every criterion from `docs/stage-02-acceptance.md`.

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

Expect `artifacts/stage-02/stage-02-report.md` to exist with **Report status: DRAFT**
before verification completes.

Check specifically:

- source B restored only after documented confirmation;
- all comparison deliverables present (`schema-diff.yaml`, `entity-crosswalk.yaml`,
  `source-relationship-assessment.md`, `identity-linkage-assessment.md`);
- no language assuming patient equality without proof;
- Stage 01 baseline remains valid.

If all criteria pass, promote the report status to **FINAL** and stop.

Planned CLI: `audit verify-stage --stage 02`
