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
