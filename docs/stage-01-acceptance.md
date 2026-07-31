# Stage 01 — Acceptance criteria

Single source audit of clinic database `magerya_api`. All criteria must pass
before the stage gate is declared reached.

## Scope

- [ ] Exactly one clinic source audited (local `magerya_api` copy)
- [ ] No second clinic, no cross-clinic merge, no unified database
- [ ] No simulator design, ML/LLM, OMOP, or FHIR work

## Safety

- [ ] Original restored database access must be read-only
- [ ] Derived database writes are allowed only when explicitly required by the stage
- [ ] Stage 01 does not modify either database
- [ ] No row-level patient data in agent context, logs, or Git artifacts
- [ ] No names, phones, emails, addresses, identifiers, or document bodies exposed outside the local runtime
- [ ] No secrets committed to the repository

## Deliverables

- [ ] `artifacts/stage-01/source-audit.json` — connectivity, source identity, dump inventory
- [ ] `artifacts/stage-01/schema-profile.json` — tables, columns, constraints (sanitized outputs)
- [ ] `artifacts/stage-01/entity-candidates.yaml` — candidate entity mappings (not confirmed without evidence)
- [ ] `artifacts/stage-01/relation-graph.md` — FK graph for candidates
- [ ] `artifacts/stage-01/unknown-semantics.md` — relations marked UNKNOWN
- [ ] `artifacts/stage-01/evidence/` — SQL queries backing factual claims
- [ ] `artifacts/stage-01/stage-01-report.md` — summary with links to artifacts and **Report status: DRAFT**

## Quality

- [ ] Every factual claim references a query or generated artifact
- [ ] Undocumented field meanings marked **UNKNOWN** (not inferred)
- [ ] Unresolved questions listed explicitly in the report
- [ ] `docs/current-stage.md` updated to reflect completion

## Exit

When all boxes above are satisfied:

1. Run `audit verify-stage`
2. Promote `artifacts/stage-01/stage-01-report.md` to **Report status: FINAL**
3. List unresolved questions
4. Stop — do not begin Stage 02
5. Tell the user the stage gate has been reached
