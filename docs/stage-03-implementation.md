# Stage 03 — Implementation Planning

**Phase:** implementation planning v0.3.6  
**Design baseline:** Stage 03 Design v0.7.5 (alignment candidate; prior v0.7.4 frozen in published archive)

## Objective

Prepare an executable plan for the canonical evidence layer without creating any database, DDL, or ETL runtime.

## First pilot

Source A (`magerya_api`) only, via read-only `mg_audit_ro`.

Pilot entities:

- SourceSystem
- SourceRecord
- Subject
- SubjectCharacteristic
- Encounter
- Observation
- ObservationComponent
- Provenance

## Artifacts

Directory: `artifacts/stage-03-implementation/`

| File | Purpose |
|------|---------|
| `implementation-plan.yaml` | Master plan and scope |
| `physical-storage-plan.yaml` | Derived DB topology (not created) |
| `pilot-slice.yaml` | Source A vertical slice |
| `pipeline-plan.yaml` | Extract/transform/validate/load order and executable contracts |
| `validation-plan.yaml` | Pilot reconciliation checks |
| `security-runtime-plan.yaml` | HMAC secret and runtime policy |
| `unresolved-implementation-decisions.yaml` | Open and resolved planning decisions |
| `design-baseline-manifest.sha256` | Frozen design v0.7.5 manifest (candidate) |

Publication artifacts (not in content manifest):

- `implementation-plan-report.md` (DRAFT)
- `implementation-plan-manifest.sha256`
- `implementation-plan-verification.json`

## Gate

```bash
audit --root . stage-03-implementation-plan-check
```

Side-effect-free read-only verification:

```python
verify_implementation_plan(repo_root, run_pytest=False, publish_artifacts=False)
```

## Explicit non-actions

- No canonical database
- No SQL DDL
- No ETL modules executed or authored for load
- No cross-source merge or global patient IDs
