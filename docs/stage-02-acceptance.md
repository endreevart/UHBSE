# Stage 02 — Acceptance criteria

Second source audit and comparison of `kgz-20231204.dump` against the Stage 01
baseline from `dumps/stage_magerya_api.dump`. All criteria must pass before the
stage gate is declared reached.

## Scope

- [ ] Stage 01 gate already **FINAL** (`artifacts/stage-01/stage-01-report.md`)
- [ ] Source A (`magerya_api`) remains the unchanged Stage 01 baseline — not re-restored unless required for connectivity
- [ ] Source B restored from `kgz-20231204.dump` as a **separate** immutable database
- [ ] Restoration of B performed only after documented human confirmation
- [ ] No merged database, no canonical store, no cross-source record union
- [ ] No simulator design, ML/LLM, OMOP, or FHIR work

## Safety

- [ ] Both original restored databases accessed read-only
- [ ] No DDL/DML on source A or source B during Stage 02
- [ ] No row-level patient data in agent context, logs, or Git artifacts
- [ ] No names, phones, emails, addresses, identifiers, or document bodies exposed outside the local runtime
- [ ] No secrets committed to the repository
- [ ] Identity linkage claims avoid assuming equal patients without proof

## Source B bootstrap

- [ ] `artifacts/stage-02/source-b-audit.json` — dump path, restore timestamp, connection identity, PostgreSQL version, read-only verification
- [ ] Source B runs on a connection profile distinct from source A (separate port and/or database)
- [ ] Dump file `kgz-20231204.dump` unchanged on disk

## Source B audit (same class as Stage 01)

- [ ] `artifacts/stage-02/schema-profile-kgz.json` — tables, columns, constraints (sanitized)
- [ ] `artifacts/stage-02/entity-candidates-kgz.yaml` — candidate entities (not confirmed without evidence)
- [ ] `artifacts/stage-02/relation-graph-kgz.md` — FK graph for B
- [ ] `artifacts/stage-02/unknown-semantics-kgz.md` — UNKNOWN relations for B
- [ ] `artifacts/stage-02/evidence/` — SQL/query records backing B audit claims

## Comparison deliverables

- [ ] `artifacts/stage-02/schema-diff.yaml` — structural diff A vs B (tables, columns, keys, indexes)
- [ ] `artifacts/stage-02/entity-crosswalk.yaml` — candidate A↔B entity mappings with confidence levels
- [ ] `artifacts/stage-02/source-relationship-assessment.md` — system-level relationship hypothesis with evidence
- [ ] `artifacts/stage-02/identity-linkage-assessment.md` — patient-linkage verdict without assumed equality

## Quality

- [ ] Every factual claim references a query, diff rule, or generated artifact
- [ ] Undocumented field meanings marked **UNKNOWN** (not inferred)
- [ ] Entity crosswalk entries distinguish `STRUCTURAL_MATCH` from `EVIDENCE_BACKED`
- [ ] Relationship assessment uses defined hypothesis codes (`SHARED_LINEAGE`, `PARALLEL_DEPLOYMENT`, etc.) or **UNKNOWN**
- [ ] Identity assessment uses defined verdict codes; `LINKAGE_PROVEN` only with explicit documented proof
- [ ] Unresolved questions listed in the report
- [ ] `docs/current-stage.md` updated to reflect Stage 02 completion

## Report

- [ ] `artifacts/stage-02/stage-02-report.md` — summary with links to all artifacts and **Report status: DRAFT**
- [ ] Report sections cover: source B audit summary, schema diff highlights, crosswalk summary, relationship hypothesis, identity linkage verdict, unresolved questions

## Exit

When all boxes above are satisfied:

1. Run `audit verify-stage --stage 02` (or skill **verify-stage-02**)
2. Promote `artifacts/stage-02/stage-02-report.md` to **Report status: FINAL**
3. List unresolved questions
4. Stop — do not begin Stage 03
5. Tell the user the stage gate has been reached
