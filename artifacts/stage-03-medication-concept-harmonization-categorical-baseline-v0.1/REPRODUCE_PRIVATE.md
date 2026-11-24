# Reproduce (private) — Medication Concept Harmonization v0.1

Requires:

* `private/intervention-association-v01/episodes/episodes_appointment_date_h365.jsonl`
* Source A RO via `db-audit.env`
* Optional: `private/medication-concept-v01/provider-snapshots/{esklp,rxnorm}/`

```bash
uv run --frozen audit --root . medication-concept run-v0.1 --no-publish
uv run --frozen audit --root . medication-concept publish-v0.1
```
