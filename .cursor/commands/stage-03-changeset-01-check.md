# Stage 03 Implementation Changeset 01 — Check

**Changeset:** Canonical Storage Foundation v0.1
**Design baseline:** v0.7.4 (immutable)
**Implementation plan:** v0.3.5 (accepted)

1. Verify the frozen baseline first; it is read-only and repairs nothing:
   `audit --root . changeset-01-baseline`
2. Run the changeset gate: `audit --root . changeset-01-check`
   Use `--no-publish` for a read-only run that writes nothing.
3. Confirm the Stage 02 blocker still reports the open defect (expected non-zero exit):
   `audit --root . stage-02-pre-live-load-gate`
4. Run: `pytest tests/test_canonical_schema_contract.py tests/test_canonical_migrations_static.py tests/test_stage02_pre_live_load_gate.py tests/test_changeset_01_verifier.py -q -m 'not publisher_only and not integration'`
5. With the isolated canonical service running and `canonical-db.env` sourced, run the
   migration suite: `pytest -q -m integration`
6. Keep `artifacts/stage-03-implementation-changeset-01/changeset-01-report.md` at **DRAFT**.

Do not extract, load or read clinical rows. Do not repair the Stage 02 manifest drift here;
that belongs to a separate maintenance changeset.
