# Stage 03 Implementation Planning — Acceptance

**Implementation planning:** v0.3.6  
**Design baseline:** v0.7.5 (alignment candidate)

## Preconditions

- [ ] Stage 01 FINAL
- [ ] Stage 02 FINAL
- [ ] Stage 03 Design v0.7.5 verification PASS (candidate)
- [ ] Design content manifest unchanged from baseline

## Planning gate

- [ ] `audit --root . stage-03-implementation-plan-check` returns PASS
- [ ] `tests/test_verify_implementation_plan.py` passes
- [ ] `tests/test_stage03_contracts.py` passes
- [ ] `tests/test_review_bundle_validation.py` passes
- [ ] Implementation plan report remains DRAFT
- [ ] Gate return payload matches on-disk verification JSON

## Required planning content

- [ ] Derived database topology documented and isolated from raw sources
- [ ] Pilot limited to Source A
- [ ] All pilot entities mapped in design contracts
- [ ] Pilot read-set fully covered by snapshot fingerprint contract
- [ ] Pipeline defines load order, idempotency, rollback, reconciliation
- [ ] Executable snapshot fingerprint and canonical payload hash contracts defined
- [ ] Validation defines counts, duplicates, orphans, provenance, rerun checks
- [ ] Canonical ID uses id_namespace_version 0.7.0 with runtime-only secret
- [ ] Quarantine and reject reason codes defined
- [ ] Unresolved decisions tracked in `unresolved-implementation-decisions.yaml`
- [ ] Review bundle ZIP matches REVIEW_INDEX.md exactly

## Forbidden at this gate

- [ ] No database created
- [ ] No DDL files for canonical schema
- [ ] No ETL modules executed or authored for load
- [ ] No cross-source merge or global patient IDs
- [ ] No nested review ZIP inside review bundle

## Stop line

Planning PASS does **not** authorize implementation coding, migrations, or data load.
