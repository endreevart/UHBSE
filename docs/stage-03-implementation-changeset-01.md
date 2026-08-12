# Stage 03 Implementation — Changeset 01: Canonical Storage Foundation

**Changeset version:** 0.2.3 — Contract Authority and Semantic Validation Hardening
**Design baseline:** v0.7.4 (immutable input)
**Implementation plan:** v0.3.5 (accepted input)
**Report status:** DRAFT

This is the first implementation changeset. It creates the infrastructure for an **empty**
canonical database and the versioned migrations for the pilot model. It does not extract,
transform or load any clinical data.

## What this changeset adds

| Area | Contents |
|------|----------|
| Isolated service | `canonical-db` in `docker-compose.yml`: PostgreSQL 16, own volume `uhbse_canonical_dev_data`, own bridge network, host port 5436 |
| Env template | `config/canonical-db.env.template`, placeholders only; the runtime `canonical-db.env` is git-ignored |
| Migrations | `migrations/canonical/0001_roles_and_schema.sql`, `0002_pilot_evidence_tables.sql`, `0003_pilot_grants.sql`, `0004_storage_contract_hardening.sql` |
| Schema contract | `src/human_simulator/canonical/schema_contract.py`, the declarative expectation used for fail-closed verification |
| Definition baseline | `src/human_simulator/canonical/definition_baseline.py` plus the pinned `canonical-definition-baseline.json` |
| Migration runner | `src/human_simulator/canonical/migrations.py`, forward-only with a checksum history table |
| Stage 02 blocker | `src/human_simulator/stage03/pre_live_load_gate.py` |
| Pre-live-load blockers | `src/human_simulator/stage03/pre_live_load_blockers.py` |
| Verifier | `src/human_simulator/stage03/verify_changeset_01.py` |
| Bundle attestation | `src/human_simulator/stage03/changeset_01_attestation.py` |
| Frozen evidence | `src/human_simulator/stage03/frozen_evidence.py`, the accepted hash of all 36 frozen inputs |
| Publication lock | `src/human_simulator/stage03/publication_lock.py` |
| Contract validator | `src/human_simulator/stage03/live_load_contracts.py`, structural validation of the two contracts that would unblock a live load |
| Contract schema | `artifacts/stage-03-implementation-changeset-01/live-load-contract-schema.yaml`, the required shape of those contracts |
| Design archive finding | `src/human_simulator/stage03/design_archive_finding.py`, the finding recomputed from the archive's own hash |

## Pilot scope

Seven entities from `artifacts/stage-03-implementation/pilot-slice.yaml`, in FK load order:

1. `SourceSystem`
2. `SourceRecord`
3. `Subject`
4. `SubjectCharacteristic`
5. `Encounter`
6. `Observation`
7. `ObservationComponent`

Provenance is embedded per entity as a validated `jsonb` column, following
`artifacts/stage-03/provenance-contract.yaml`. Subject identity stays source-local
(`source_system_id` + `source_subject_key`); no `global_patient_id` or `global_subject_id`
column exists anywhere in the schema.

## Migration mechanism

Migrations are **forward-only**; the accepted plan defines no down migrations, so the
`up → down → up` check does not apply and the runner refuses to invent one. Re-running the
runner applies nothing and mutates nothing. Every applied migration is recorded with its
SHA-256 and the schema-contract fingerprint in `canonical_migration.schema_migration_history`,
outside the evidence schema. Editing an already-applied migration fails closed with a
checksum-drift error.

A published migration is also immutable on disk. `ACCEPTED_MIGRATION_SHA256` in
`src/human_simulator/canonical/constants.py` records the accepted bytes of 0001-0003, and every
migration run re-checks them before applying anything. A schema correction may therefore only
arrive as a new forward-only file, which is what `0004_storage_contract_hardening.sql` is.

## v0.2 — Storage Verification Hardening

### Definition-level verification

Checking that a constraint *name* exists proves nothing: `CHECK (TRUE)` can be renamed onto any
constraint name and a name-only verifier will pass. The verifier now compares the normalized
definitions PostgreSQL itself reports — `pg_get_constraintdef` for primary keys, foreign keys,
unique constraints and check expressions, `pg_get_indexdef` for indexes, enum types with their
value order, table and schema owners, schema privileges, table privileges and default
privileges — against a pinned document:

```bash
# rebuild the baseline on a database this command creates and drops
audit --root . canonical-capture-baseline --no-publish
```

The capture refuses to run unless the accepted migration bytes produced the schema it reads, so
the pinned document can only ever describe reviewed DDL. Verification never repairs a drift it
finds; it reports and fails.

### Mandatory integration suite

`integration_migration_suite` is mandatory and may not be skipped. Absent, skipped, a non-zero
exit code, or a single failure or error, produces an overall release FAIL and blocks the review
bundle. An overall PASS therefore requires the migrations to have actually been applied to a
disposable PostgreSQL 16 database.

### Provenance hardening

Migration 0004 adds check constraints to all six provenance-bearing tables. A required key is
not satisfied by a JSON `null`. `CORRECTED` requires `prior_record_reference` and
`correction_reason`, `NORMALIZED` requires `normalization_lineage`, and `ANNOTATED` requires
`annotation_text` and `annotated_at`. The source-backed and computed profiles stay mutually
exclusive in both directions, `SYNTHETIC` and `PREDICTED` remain rejected in every evidence
table, `SubjectCharacteristic.status` must equal `provenance.mapping_status`, and a
`SourceRecord` row whose locator columns contradict its provenance block is rejected. No type or
field absent from the accepted contracts was introduced.

## v0.2.1 — Publication Isolation Fix

External audit accepted the v0.2 code, migration 0004, the mandatory integration gate and the
pre-live-load blockers, but found that the review archive carried Design evidence a test had
*regenerated* rather than the bytes of the accepted Design v0.7.4 release.

### How it happened

Two full test runs were executing concurrently while the bundle was being built. Both republished
Stage 03 evidence into the working tree, and the interleaving left the regenerated files in place
for the builder to package. `design-content-manifest.sha256` covers the eleven Design content
artifacts, and all eleven were correct throughout. The two *generated* evidence files — the design
report and the design verification — are listed by no manifest, so nothing compared them to an
accepted value. The damage was confined to evidence: the canonical schema, the definition
baseline, migrations 0001-0004, the Plan artifacts and the nine Stage 01/02 files were byte
identical the whole time.

### Frozen evidence

`frozen_evidence.py` pins the accepted SHA-256 of 36 inputs — the 9 controlled Stage 01/02 files,
the 11 Design content artifacts, the design manifest, the 2 generated Design evidence files, the
8 Plan artifacts, the plan manifest and migrations 0001-0004:

```bash
audit --root . frozen-evidence-check
```

The publisher fingerprints all 36 before and after each mandatory suite, so a suite that writes
into a frozen path is attributed to that suite and blocks publication. Nothing is ever repaired
automatically. Recovery copies bytes out of an accepted release archive and installs them only if
they hash to the audited values, which makes installing a regenerated file impossible:

```bash
audit --root . recover-design-evidence --confirm
```

The entry point is unreachable from any gate, suite or publisher, and the verifier proves that by
parsing those modules for a real import or call rather than grepping for the name.

### Test isolation

Every publication-capable test runs against a throwaway copy of the workspace and is deleted
afterwards. No test writes into `artifacts/stage-03/`, `artifacts/stage-03-implementation/`, the
changeset snapshot or `artifacts/external-review/`, and none needs backup-and-restore — a pattern
that cannot be correct when two runs overlap.

### Publication lock

The pipeline holds an `O_EXCL` lock for its whole run, so the winner is decided by the filesystem
rather than by a timing assumption. A second publisher fails immediately, naming the holder.
Nesting on the acquiring thread is allowed, because the publisher calls publishing steps inside
its own lock; any other thread or process is refused. A stale lock is recognised by the liveness
of the owning pid on the same host, or by age elsewhere. The lock file records a pid, a host, an
operation name and a timestamp, and never travels into a review bundle. Read-only gates do not
take it.

### Bundle validation

The builder compares both Design evidence files to their accepted hashes and refuses to build
otherwise. `release-verification.json` records `frozen_design_report_match`,
`frozen_design_verification_match`, `all_frozen_evidence_unchanged`, `publication_lock_verified`
and `automatic_restore_performed: false`.

## v0.2.3 — Contract Authority and Semantic Validation Hardening

v0.2.2 replaced word search with structured contracts. That was the right shape of fix, and it
still allowed two kinds of PASS that would have meant nothing.

**Anyone could write the contract.** A contract was accepted from any YAML file under the Stage 03
directories, including `artifacts/stage-03-implementation-changeset-01/` — the changeset's own. A
changeset could therefore have authored the contract that unblocked the changeset. A blocker names
a decision an accepted release has not taken; only an accepted release taking it can close one.

**Well-formed values could be wrong.** `classify_algorithm` matched by substring, so
`not-hmac-sha256`, `fake-hmac-sha256` and `hmac-sha256-unkeyed` all read as keyed PRFs — the first
two saying the opposite of how they were read. Any occurrence of `SET ROLE` satisfied the loader
flow, including `SET ROLE postgres`.

### Contract authority

`contract-authority-policy.yaml` fixes one authoritative path per contract, each owned by an
accepted release:

| Contract | Authoritative path | Owning release |
|----------|--------------------|----------------|
| `subject_key_transformation_contract` | `artifacts/stage-03/canonical-id-contract.yaml` | Stage 03 Design |
| `canonical_loader_runtime_contract` | `artifacts/stage-03-implementation/security-runtime-plan.yaml` | Stage 03 Implementation Plan |

Design owns subject-key opacity because it is a property of the canonical model and a
data-protection decision, not a loader detail; the same artifact already defines the keyed
transformation for `source_record_locator`, which is why no equivalent blocker exists for the
locator. The Plan owns the runtime principal because which account connects, with which
credentials and privileges, is a runtime security decision.

A contract is accepted only when all of these hold: it sits at the exact authoritative path, that
path is listed in the owning release manifest, the manifest verifies by SHA-256 against every file
it lists, and exactly one definition exists in scope. Zero definitions keep the blocker OPEN — the
current state. Two definitions fail `contract_definitions_are_unambiguous`, because a contract
that exists twice is a contract nobody owns, and reporting that as merely "absent" would
understate it. Recursive discovery is gone; the scope is still walked, but only to detect and name
strays.

### Semantic validation

Algorithm identifiers match by equality against a fixed set, never by containment. Beyond that,
values are checked for what they say:

| Field | Rule |
|-------|------|
| `transformation_id` | must equal `subject_key_from_id` |
| `key_reference`, `credential_source_reference` | must be a secret-store reference (`vault://`, `aws-secretsmanager://`, …), never a literal or anything shaped like key material |
| `key_version` | must be comparable: `v1`, `1.2` or an ISO date, so a rotation is detectable |
| `input_encoding` | must be an exact token; prose is rejected, because two encodings of one id produce two keys |
| `collision_handling` | must stop the load (`abort`, `quarantine`, `reject`); `ignore`, `continue`, `overwrite` and `skip` are rejected |
| `group_role` / `login_principal` | must be `canonical_loader` and must *not* be `canonical_loader`, respectively; the login principal must be a valid unquoted PostgreSQL identifier and not a superuser-adjacent name |
| `set_role_flow` | must state `SET ROLE canonical_loader`; any other role, including `postgres`, fails |
| `minimal_grants` | allowlist `SELECT`, `INSERT`, `USAGE`; `ALL`, `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `BYPASSRLS` and write grants are rejected |
| `audit_identity` | must record `session_user` and name the login principal, or an action under the group role cannot be attributed |
| `rotation_and_revocation_procedure` | a mapping whose `revocation` names a real action: `REVOKE`, `DROP ROLE`, `ALTER ROLE … NOLOGIN` or disabling the credential |

### The registry is an artifact, not just a source

Deriving blocker checks from `accepted-artifact-conflicts.yaml` removed the risk of two
hand-maintained lists drifting apart and introduced a quieter one: the check set depends on a file,
so damaging the file removes checks. Deleting the registry made two blockers vanish and the gate
reported *fewer* failures than before — fail-open behaviour dressed as a smaller problem.

`accepted_artifact_conflict_registry_valid` validates the registry itself. It fails when the file
is absent, the YAML is unparsable, `conflicts` is missing or the wrong type or empty, an entry
lacks `id`, `severity` or `status`, an id is duplicated, a severity or status is unknown,
`open_conflict_count` disagrees with the entries, an OPEN blocking conflict is not enforced as a
gate check, or the bytes do not match the accepted changeset manifest. No conflict identifier
appears in Python; a test asserts it.

### What this changed in the workspace

Nothing was unblocked. No contract instance was created, no conflict was moved to `RESOLVED`, and
the gate still reports FAIL on all five blockers. `tests/test_contract_authority.py` proves the
mechanism can reach PASS — in a throwaway workspace where the Stage 02 manifest is re-sealed, both
authoritative contracts are semantically valid, both conflicts are resolved and every manifest
verifies — and proves that breaking any single one of those keeps it FAIL.

## v0.2.2 — Pre-live-load Gate Hardening

The v0.2 gate was weaker than the artifacts that described it, in two independent ways.

**It enforced three of five reasons.** The gate consulted a hand-maintained blocker list. Two
conflicts had already been recorded in `accepted-artifact-conflicts.yaml` as
`severity: BLOCKS_LIVE_LOAD` and `status: OPEN`, and the gate ignored both. A guard that
disagrees with its own documentation is worse than no guard, because it invites trust it has
not earned.

**It closed blockers on words.** Resolution was decided by substring search. Any accepted
artifact containing `hash` proved subject-key opacity, and any artifact mentioning `SET ROLE`
proved a loader runtime principal existed. `SHA256(account_patient.id)` would have satisfied the
first — a digest of a bounded integer space is reversible by exhaustive search in negligible
time, so it makes nothing opaque — and a sentence stating that no `SET ROLE` path is yet defined
would have satisfied the second.

### One registry, no second list

`pre_live_load_blockers.py` is now the only producer of blockers, from three sources: the Stage
02 manifest, structured contract validation, and every conflict in
`accepted-artifact-conflicts.yaml` that is `OPEN` and `BLOCKS_LIVE_LOAD`. Conflict blockers are
derived, never restated in code, so recording a conflict is sufficient to block the load and the
two lists cannot drift apart. A test asserts that no conflict id appears as a literal in the
module.

If a mandatory blocker vanishes — because a source artifact was deleted, for instance — the gate
fails `required_blocker_checks_present` rather than quietly reporting fewer failures.

### Structured contracts

`live_load_contracts.py` validates two contracts by shape, not by vocabulary:

| Contract | Required fields |
|----------|-----------------|
| `subject_key_transformation_contract` | `transformation_id`, `algorithm`, `key_reference`, `key_version`, `namespace`, `input_encoding`, `output_encoding`, `rotation_policy`, `collision_handling` |
| `canonical_loader_runtime_contract` | `login_principal`, `group_role`, `group_role_is_nologin`, `credential_source_reference`, `connection_path`, `set_role_flow`, `minimal_grants`, `audit_identity`, `rotation_and_revocation_procedure` |

Every field must be present, non-empty and not a placeholder; `TBD`, `TODO`, `none`, `unknown`
and the empty string are treated as missing. The subject-key algorithm must be a keyed PRF —
HMAC-SHA256, HMAC-SHA512, KMAC, keyed BLAKE2 — and `HMAC` alone is rejected because the
underlying function is unnamed. Unkeyed digests are rejected however they are spelled. A
`credential_source_reference` carrying a literal credential is a validation failure, and a
`set_role_flow` without an explicit `SET ROLE` statement is too.

`artifacts/stage-03-implementation-changeset-01/live-load-contract-schema.yaml` records this
requirement. It is a schema, not a contract: writing an instance here would close a blocker by
self-assertion, so none exists and both contract blockers remain OPEN.

### Fail-closed and read-only

One open blocker is enough for FAIL. A test resolves three of the five and leaves one artifact
conflict open, and the gate still fails; PASS is demonstrated only in an isolated fixture where
all five are structurally closed. The gate hashes all 36 frozen inputs before and after
evaluation and records both sets, writes no manifest, restores no frozen evidence, opens no
database connection and reads no clinical row.

### Open finding, stated with hashes

v0.2.1 said the published Design archive "does not carry the audited bytes" without recording
the archive's own hash, which made the claim unverifiable.
`design-archive-evidence-finding.json` now records the SHA-256 of the archive inspected, the
SHA-256 of both Design evidence members inside it, the audited values and the source of the
recovered bytes. The finding is a statement about that artifact at that hash and nothing more:
no sidecar was ever published for the Design archive, so no accepted hash exists for it, what it
contained at first publication cannot be established, and no historical corruption is asserted.
Republishing the Design archive is out of scope here.

## Roles

`canonical_owner`, `canonical_migrator`, `canonical_loader` and `canonical_validator_ro` are
all `NOLOGIN`; they are privilege containers assumed by the runtime, not login accounts.
The loader may `SELECT` and `INSERT` only. The validation role may `SELECT` only, and is
verified to be unable to insert, update, delete or create.

## Commands

```bash
# read-only baseline re-verification of the frozen inputs
audit --root . changeset-01-baseline

# changeset gate; --no-publish writes nothing
audit --root . changeset-01-check

# Stage 02 blocker; expected to exit non-zero while the drift is open
audit --root . stage-02-pre-live-load-gate

# apply migrations to the isolated canonical database (schema only)
audit --root . canonical-migrate

# read-only hash check of all 36 frozen inputs
audit --root . frozen-evidence-check

# gate hardening regression tests
uv run pytest tests/test_pre_live_load_gate_hardening.py -q
```

## Open items

- `stage02_relationship_manifest_drift` remains open. The executable gate
  `stage02_relationship_integrity_pre_live_load` reports FAIL and blocks all future live
  extraction, load and ETL. It does not block creating the empty database or applying
  migrations, and it repairs nothing. An independent recount in v0.2.1 finds **two** mismatched
  artifacts, `subject-root-analysis.json` and `identity-linkage-assessment.json`; the gate
  previously reported only the first because the Stage 02 verifier returns on the first
  difference it sees. Nothing in Stage 02 was rewritten.
- The `stage-03-design-v0.7.4-review.zip` present in this workspace does not carry the audited
  Design evidence bytes at the SHA-256 recorded in `design-archive-evidence-finding.json`.
  Republishing it is out of scope for this changeset.
- Two conflicts between accepted artifacts are recorded in
  `artifacts/stage-03-implementation-changeset-01/accepted-artifact-conflicts.yaml`. Both are
  blocking for live load and non-blocking for empty storage creation. Neither is repaired here.
  From v0.2.2 both are enforced as gate checks automatically.
- Five pre-live-load blockers are open, all recorded in
  `artifacts/stage-03-implementation-changeset-01/pre-live-load-blockers.yaml` and all reported
  as failed checks by `stage02_relationship_integrity_pre_live_load`:
  `stage02_relationship_manifest_drift`, `canonical_loader_runtime_principal_undefined`,
  `source_subject_key_opacity_undefined`, `temporal_precision_field_absent_from_model` and
  `encounter_provider_id_population_disagreement`. Each blocks the first live load; none blocks
  schema-only migration 0004.
- Neither contract instance exists. Until an accepted release supplies a complete
  `subject_key_transformation_contract` and `canonical_loader_runtime_contract`, a load today
  would write the raw `account_patient.id` into a field the model declares opaque, under a role
  no account can authenticate as. From v0.2.3 those contracts can only arrive at
  `artifacts/stage-03/canonical-id-contract.yaml` and
  `artifacts/stage-03-implementation/security-runtime-plan.yaml` respectively, as part of a
  Design or Plan release; no changeset can supply either.

## Not in this changeset

No clinical row reads, no ETL, no pilot cohort, no data in the canonical database, no change to
the raw databases, no Source B, no patient linkage, no simulation or prediction, and no change
to Design v0.7.4 or Plan v0.3.5.

v0.2.2 additionally starts no Stage 02 maintenance, repairs no manifest drift, creates no
migration 0005, changes no canonical schema, resolves no pre-live-load blocker, writes no
contract instance, overwrites no published archive and does not begin Changeset 02.

v0.2.3 keeps every one of those non-actions and adds: no Design or Plan update, no conflict moved
to `RESOLVED`, no database connection of any kind, and no change to the published v0.1, v0.2,
v0.2.1 or v0.2.2 archives, sidecars or attestations.
