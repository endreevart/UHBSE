# Current stage

**Stage:** 03 — Canonical Clinical Event Model
**Phase:** Implementation — Changeset 01 (Canonical Storage Foundation) v0.2.3, Contract Authority and Semantic Validation Hardening
**Design baseline:** v0.7.5 (alignment candidate DRAFT; accepted frozen baseline v0.7.4)
**Implementation plan:** v0.3.6 (alignment candidate DRAFT; accepted frozen baseline v0.3.5)
**Last updated:** 2026-08-12

## Status

| Phase | Status |
|-------|--------|
| Design v0.7.4 | accepted frozen baseline |
| Design v0.7.5 | alignment candidate DRAFT (not FINAL) |
| Implementation planning v0.3.5 | accepted frozen baseline |
| Implementation planning v0.3.6 | alignment candidate DRAFT (not FINAL) |
| Stage 03 Alignment Candidate v0.1 | review bundle published (defective; superseded) |
| Stage 03 Alignment Candidate v0.1.1 | review bundle published; baseline recovery + publication pipeline fix |
| Stage 03 Alignment Candidate v0.1.2 | review bundle published; canonical DB baseline + self-contained manifest ZIP |
| Stage 03 Alignment vault-stop v0.2.1 | published; Vault checkpoint PASS; PG LOGIN hold |
| Stage 03 Alignment postgres-principal v0.1 | published DRAFT; LOGIN provisioned; runtime contract not closed |
| Stage 03 Alignment runtime-auth v0.1 | published DRAFT; PARTIAL_RUNTIME_VERIFIED; custody DECISION_REQUIRED |
| Stage 03 Alignment runtime-auth v0.1.1 | published DRAFT; live Vault Agent + restart/reauth PASS (publication integrity defect) |
| Stage 03 Alignment runtime-auth v0.1.2 | published DRAFT; atomic publication repair + evidence hardening; integrity PASS |
| Stage 03 Alignment security-remediation v0.1 | Phase 2 WAITING_FOR_THREE_CUSTODIANS — runbook corrected; no live rekey |
| Changeset 01 v0.1 — canonical storage foundation | published |
| Changeset 01 v0.2 — storage verification hardening | published, evidence defect found by external audit |
| Changeset 01 v0.2.1 — publication isolation fix | published |
| Changeset 01 v0.2.2 — pre-live-load gate hardening | published |
| Changeset 01 v0.2.3 — contract authority and semantic validation | published |
| Stage 02 Maintenance 01 — relationship manifest drift diagnosis | FINAL |
| Stage 02 Maintenance 01 — authorised repair application | FINAL |
| Changeset 02 and later | not started |
| Clinical extraction / ETL / load | not started, blocked |

Changeset 01 creates the empty canonical database and its migrations only. No clinical row has
been read, transformed or loaded.

v0.2 leaves migrations 0001-0003 byte identical and adds the forward-only
`0004_storage_contract_hardening.sql`. Verification now compares the normalized definitions
PostgreSQL reports — constraint expressions, index definitions, enum value order, owners and
privileges — against the pinned
`artifacts/stage-03-implementation-changeset-01/canonical-definition-baseline.json`, so a
constraint renamed onto `CHECK (TRUE)` fails. The integration/migration suite is mandatory:
absent, skipped or failing blocks publication.

v0.2.1 repairs how evidence is published, not what it contains. External audit found that the
v0.2 review archive carried Design evidence a test had regenerated in the working tree rather
than the bytes of the accepted Design v0.7.4 release. `design-content-manifest.sha256` covers the
eleven Design content artifacts, all of which were correct; the two *generated* evidence files
were covered by nothing. The frozen baseline now pins 36 inputs by hash — the nine Stage 01/02
files, the eleven Design content artifacts, the design manifest, the two Design evidence files,
the Plan artifacts, the plan manifest and migrations 0001-0004 — and re-checks them before and
after every mandatory suite. Publication-capable tests run in a throwaway workspace copy, the
publisher holds an exclusive inter-process lock, and the bundle builder refuses to package
Design evidence that does not match the audited hashes.

v0.2.2 repairs the guard itself. The v0.2 gate enforced three of the five open reasons: it read a
hand-maintained blocker list and ignored the two conflicts already recorded in
`accepted-artifact-conflicts.yaml` as `severity: BLOCKS_LIVE_LOAD` and `status: OPEN`. It also
decided resolution by searching artifacts for words, so `SHA256(account_patient.id)` — reversible
by exhaustive search over a bounded integer space — would have closed the subject-key blocker, and
a sentence saying no `SET ROLE` path is defined would have closed the loader blocker. Conflicts
are now derived directly from the artifact, so recording one is sufficient to block the load, and
resolution requires a complete structured contract described in
`artifacts/stage-03-implementation-changeset-01/live-load-contract-schema.yaml`. That file is a
schema, not a contract: writing an instance would close a blocker by self-assertion, so none
exists and both contract blockers stay OPEN.

v0.2.3 fixes who may write such a contract, and what its values have to mean. v0.2.2 accepted a
contract from any YAML file under the Stage 03 directories, including the changeset's own, so a
changeset could have authored the contract that unblocked the changeset; and it compared algorithm
names by substring, so `not-hmac-sha256` read as a keyed PRF while stating the opposite, and any
occurrence of `SET ROLE` satisfied the loader flow, including `SET ROLE postgres`.
`contract-authority-policy.yaml` now names one authoritative path per contract:
`subject_key_transformation_contract` belongs to Stage 03 Design at
`artifacts/stage-03/canonical-id-contract.yaml`, and `canonical_loader_runtime_contract` belongs to
the Implementation Plan at `artifacts/stage-03-implementation/security-runtime-plan.yaml`. A
contract counts only at that exact path, listed in its owning release manifest, with the manifest
verifying by SHA-256, and with exactly one definition in scope; zero definitions keep the blocker
OPEN and two fail as ambiguous. Values are checked for what they say — exact algorithm
identifiers, secret-store references rather than secrets, fail-closed collision handling,
`SET ROLE canonical_loader` and no other role, an allowlist of grants, and a revocation procedure
naming a revoking action.

The conflict registry is now validated as an artifact in its own right. Deriving blocker checks
from a file meant damaging the file removed checks: deleting
`accepted-artifact-conflicts.yaml` made two blockers vanish and the gate reported fewer failures
than before. `accepted_artifact_conflict_registry_valid` fails if the registry is absent,
unparsable, malformed, self-inconsistent, duplicated or does not match the accepted changeset
manifest. No conflict identifier is written in Python.

Stage 02 Maintenance 01 diagnosed and repaired the oldest blocker,
`stage02_relationship_manifest_drift`. The cause was two controls pinning the same files:
`relationship-manifest.sha256` covers eight relationship artifacts, `ACCEPTED_SHA256` covers nine
Stage 01/02 files, and their intersection was exactly the two artifacts that drifted.
`restore-prior-stage-baseline` restores that intersection and does not touch the manifest, so
running it after the manifest was sealed left the two out of step by construction — confirmed by
the restore source archive holding precisely the bytes now on disk, and by each drifted `.json`
disagreeing with its own markdown sibling, which a regeneration could not produce. Across every
published copy and a fresh read-only reproduction, the only difference was `assessed_at`: no
verdict, aggregate, denominator or conflict definition moved. The authorised repair re-sealed
`relationship-manifest.sha256` over the accepted bytes without copying the eight artifacts from
the candidate. The pre-live-load gate now FAILs on four remaining blockers only. See
`docs/stage-02-maintenance-01.md` and `artifacts/stage-02-maintenance-01/promotion-report.json`.

One finding remains open and is now stated with hashes rather than adjectives. The archive
`artifacts/external-review/stage-03-design-v0.7.4-review.zip`, at the SHA-256 recorded in
`artifacts/stage-03-implementation-changeset-01/design-archive-evidence-finding.json`, does not
carry the audited Design evidence bytes. No sidecar was ever published for that archive, so no
accepted hash exists for it and what it contained at first publication cannot be established; no
historical corruption is asserted. The audited bytes in this workspace were recovered from the
accepted `stage-03-implementation-changeset-01-v0.1-review.zip` and corroborated by
`stage-03-implementation-plan-v0.3.4-review.zip`. Republishing the Design archive is out of scope.

## Gates

```bash
audit --root . changeset-01-baseline           # read-only frozen-input re-verification
audit --root . changeset-01-check              # changeset gate (--no-publish for read-only)
audit --root . stage-02-pre-live-load-gate     # expected non-zero while four blockers remain open
audit --root . stage-02-maintenance-01         # drift diagnosis; applies no repair
audit --root . stage-02-maintenance-01-apply --confirm  # promotion when repair already applied
audit --root . canonical-capture-baseline --no-publish  # rebuild pinned definitions, throwaway DB
audit --root . frozen-evidence-check           # read-only hash check of all 36 frozen inputs
audit --root . stage-03-check --no-publish
audit --root . stage-03-implementation-plan-check --no-publish
```

Prior-stage integrity evaluation is read-only. If controlled Stage 01/02 bytes ever drift, the
gate fails and does not repair anything; restoring the accepted baseline is a separate,
explicitly confirmed action:

```bash
audit --root . restore-prior-stage-baseline --confirm
```

The same rule governs Design evidence. Recovery copies bytes out of an accepted release archive
and installs them only if they hash to the audited values, so a regenerated file can never be
installed. No gate, suite or publisher can reach it:

```bash
audit --root . recover-design-evidence --confirm
```

Release evidence for every gate and suite lives in
`artifacts/stage-03-implementation-changeset-01/release-verification.json` for this changeset and
in `artifacts/stage-03-implementation/release-verification.json` for the planning release.

## Blocking defect

`stage02_relationship_manifest_drift` is **resolved** by Stage 02 Maintenance 01. Only
`artifacts/stage-02/relationship-manifest.sha256` changed; the eight relationship artifacts and
nine controlled Stage 01/02 files are unchanged.

The executable gate `stage02_relationship_integrity_pre_live_load` still reports FAIL on four
remaining blockers and blocks every future live extraction, load and ETL command. It does not block
the empty canonical database or its migrations.

An independent recount in v0.2.1 found two manifest mismatches, not one:
`subject-root-analysis.json` and `identity-linkage-assessment.json`. The gate previously reported
only the first, because the Stage 02 verifier returns on the first difference it sees; it now
enumerates all of them. Maintenance 01 re-sealed the manifest over the accepted artifact bytes.

## Open pre-live-load blockers

Recorded in `artifacts/stage-03-implementation-changeset-01/pre-live-load-blockers.yaml` and
enforced as FAIL checks of `stage02_relationship_integrity_pre_live_load`. Four blockers block
the first live load; none blocks schema-only migration 0004. One open blocker is enough for FAIL.

| Blocker | Derived from | Question | Status |
|---------|--------------|----------|--------|
| `stage02_relationship_manifest_drift` | Stage 02 manifest | Do the Stage 02 relationship artifacts still carry the bytes their manifest records? | **RESOLVED** (Maintenance 01) |
| `canonical_loader_runtime_principal_undefined` | `security-runtime-plan.yaml` (Plan-owned) | Which login principal connects and assumes `canonical_loader`, from which credential source, by which connection path and `SET ROLE` flow, with which minimal grants, audit identity and rotation procedure? | OPEN |
| `source_subject_key_opacity_undefined` | `canonical-id-contract.yaml` (Design-owned) | Does the accepted Design release define `subject_key_from_id` as a keyed PRF with key reference, key version, namespace, encodings, rotation policy and fail-closed collision handling? | OPEN |
| `temporal_precision_field_absent_from_model` | `accepted-artifact-conflicts.yaml` | Has the temporal contract / canonical model contradiction been resolved? | OPEN |
| `encounter_provider_id_population_disagreement` | `accepted-artifact-conflicts.yaml` | Has the `provider_id` population contradiction between design and plan been resolved? | OPEN |

Two further checks guard the mechanism rather than a decision:
`accepted_artifact_conflict_registry_valid` fails if the registry that supplies the last two rows
is damaged, and `contract_definitions_are_unambiguous` fails if a contract is defined more than
once. Authority is fixed by
`artifacts/stage-03-implementation-changeset-01/contract-authority-policy.yaml`; the changeset
directory can never be a contract source.

The gate is read-only: it hashes all 36 frozen inputs before and after evaluation, opens no
database connection, reads no clinical row, writes no manifest and restores nothing.

## Pilot

Source A (`magerya_api`) only — see `artifacts/stage-03-implementation/pilot-slice.yaml`.

Canonical storage: `uhbse_canonical_dev.canonical_evidence`, isolated PostgreSQL 16 service on
host port 5436, schema created and empty.
