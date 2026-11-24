# Reproduce (private workspace) — Medication Knowledge Representation v0.1

Requires authorised local inputs that are **not** in the review ZIP:

* `private/intervention-association-v01/episodes/episodes_appointment_date_h365.jsonl`
* Source A read-only role (`mg_audit_ro`) via `db-audit.env`
* Canonical/derived env files as needed for prior stages

```bash
# After sourcing local env files (never commit secrets):
uv run --frozen audit --root . medication-knowledge run-v0.1 --no-publish
uv run --frozen audit --root . medication-knowledge verify-v0.1
uv run --frozen audit --root . medication-knowledge publish-v0.1
```

Do not place patient-level rows, credentials, tokens, or DSNs in review bundles.
