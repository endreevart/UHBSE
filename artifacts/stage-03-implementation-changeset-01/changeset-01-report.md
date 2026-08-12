# Stage 03 Implementation — Changeset 01: Canonical Storage Foundation

## v0.2.3 — Contract Authority and Semantic Validation Hardening

Report status: DRAFT
Changeset: stage-03-implementation-changeset-01 v0.2.3
Design baseline: v0.7.4 (frozen)
Implementation plan: v0.3.5 (accepted, unchanged)
Generated: 2026-08-07T14:02:45.615851+00:00
Content manifest SHA-256: dde9decbe04c6031fdd94d7e4221f8fbf63ecc81a9cfedb78b84646f7c6d7e6b
Schema contract fingerprint: 99e3610fb9f828ec8982de766c57da754547ad007a76059062e549ca07872536

## Result

- Overall status: **PASS**
- Checks passed: 109/109

## Baseline precondition

- Status: PASS
- Controlled Stage 01/02 files: 9, all unchanged: True
- Design v0.7.4 manifest: verified 11 entries
- Implementation plan v0.3.5 manifest: verified 8 entries
- Automatic restoration of a prior stage: not performed

## Delivered

- Isolated PostgreSQL 16 service `canonical-db` (uhbse_canonical_dev on port 5436, volume uhbse_canonical_dev_data, network canonical-net)
- Schema `canonical_evidence` with exactly 7 pilot tables
- Forward-only migrations 0001-0003 with checksum-guarded history
- Four canonical roles with least privilege, created NOLOGIN
- Executable pre-live-load gate `stage02_relationship_integrity_pre_live_load`

## v0.2.3 — Contract Authority and Semantic Validation Hardening

v0.2.2 replaced word search with structured contracts, which was the right shape of fix and still left two ways to obtain a PASS that meant nothing. The first was authority: a contract was accepted from any YAML file under the Stage 03 directories, including the changeset's own, so a changeset could have written the contract that unblocked the changeset. The second was meaning: fields were checked for presence and shape, not for what they said. `classify_algorithm` matched by substring, so an algorithm named `not-hmac-sha256` read as a keyed PRF while stating the opposite, and any occurrence of `SET ROLE` satisfied the loader flow, including `SET ROLE postgres`.

A third weakness was structural. Deriving blocker checks from `accepted-artifact-conflicts.yaml` removed the risk of two hand-maintained lists drifting apart, but it made the check set depend on a file: deleting the registry made two blockers vanish and the gate reported fewer failures than before.

- `contract-authority-policy.yaml` names one authoritative path per contract, each owned by an accepted release. `subject_key_transformation_contract` belongs to Stage 03 Design at `artifacts/stage-03/canonical-id-contract.yaml`; `canonical_loader_runtime_contract` belongs to the Implementation Plan at `artifacts/stage-03-implementation/security-runtime-plan.yaml`
- A contract counts only if it sits at that exact path, is listed in the owning release manifest, that manifest verifies by SHA-256, and exactly one definition exists. Zero definitions keep the blocker OPEN; two definitions fail `contract_definitions_are_unambiguous`, because a contract that exists twice is a contract nobody owns
- The changeset directory is structurally excluded as a contract source. Recursive discovery is gone: the scope is still walked, but only to detect and name strays
- Algorithm identifiers match by equality against a fixed set. `not-hmac-sha256`, `fake-hmac-sha256`, `hmac-sha256-unkeyed` and an unqualified `HMAC` all fail
- Field values are validated for meaning: `transformation_id` must name the transformation the record construction contract references, key and credential fields must be secret-store references rather than values, collision handling must stop the load, `set_role_flow` must state `SET ROLE canonical_loader` and no other role, grants are checked against an allowlist, and a revocation procedure must name a revoking action
- `accepted_artifact_conflict_registry_valid` validates the registry as an artifact in its own right. Absent, unparsable, malformed, duplicated, self-inconsistent or manifest-mismatched each add a failure rather than removing checks
- No contract instance was created and no blocker was resolved. All five stay OPEN

## v0.2.2 — Pre-live-load Gate Hardening

The v0.2 gate was weaker than its own documentation. It consulted a hand-maintained blocker list that omitted the two conflicts already recorded as `BLOCKS_LIVE_LOAD` and `OPEN`, so an executable guard and the artifact describing it disagreed. It also decided resolution by searching artifacts for words: any file containing `hash` proved subject-key opacity, and any file mentioning `SET ROLE` proved a loader runtime principal existed. `SHA256(account_patient.id)` would have satisfied the first while remaining reversible by exhaustive search over a bounded integer space, and a sentence stating that no `SET ROLE` path exists would have satisfied the second.

- All five open reasons are now FAIL checks of the gate, and conflicts become checks automatically: any entry in `accepted-artifact-conflicts.yaml` that is `OPEN` and `BLOCKS_LIVE_LOAD` blocks the load without being restated in code
- Word search is gone. A subject key is opaque only under a complete `subject_key_transformation_contract` whose algorithm is a keyed PRF; unkeyed digests, and the bare words `hash`, `opaque`, `pseudonym` and `digest`, are rejected
- A loader principal exists only under a complete `canonical_loader_runtime_contract`; `TBD`, an empty field and a prose mention of `SET ROLE` are rejected
- `live-load-contract-schema.yaml` states the required shape of both contracts. It is a schema, not a contract: writing an instance would close a blocker by self-assertion, so this changeset writes none and both blockers stay OPEN
- The gate hashes all 36 frozen inputs before and after evaluation, opens no database connection, reads no clinical row, writes no manifest and restores nothing
- A missing blocker is itself a failure: `required_blocker_checks_present` fails if a mandatory check disappears, so deleting a source artifact cannot silently unblock

## v0.2.1 — Publication Isolation Fix

External audit of v0.2 found that the review archive carried Design evidence a test had regenerated in the working tree, rather than the bytes of the accepted Design v0.7.4 release. Two full test runs were executing concurrently during publication; both republished Stage 03 evidence, and the interleaving left the regenerated files in place for the builder to package. The eleven Design content artifacts were correct throughout, because a manifest covers them; the two generated evidence files were covered by nothing.

- The accepted bytes were recovered from an accepted release and are pinned: `stage-03-design-report.md` and `stage-03-design-verification.json`
- The frozen baseline now pins 36 inputs by hash and is re-checked before and after every mandatory suite, so a suite that writes into a frozen path blocks publication
- Every publication-capable test runs in a throwaway workspace copy; none writes into `artifacts/stage-03/`, `artifacts/stage-03-implementation/`, the changeset snapshot or `artifacts/external-review/`
- The publication pipeline holds an exclusive inter-process lock, so two publishers cannot interleave writes into one snapshot or archive
- The bundle builder refuses to package Design evidence that does not match the audited hashes, and never regenerates it
- Recovery is a confirmed human action (`audit recover-design-evidence --confirm`) that installs only bytes hashing to the audited values, and is unreachable from any gate, suite or publisher

## v0.2 hardening

- Migrations 0001-0003 are byte-pinned in `ACCEPTED_MIGRATION_SHA256`; every schema correction arrives through the new forward-only `0004_storage_contract_hardening.sql`
- `canonical-definition-baseline.json` pins the normalized definitions PostgreSQL itself reports for every constraint, index, enum, owner and privilege, so a renamed `CHECK (TRUE)` cannot pass a name-only comparison
- The integration/migration suite is mandatory: absent, skipped or failing blocks publication
- Migration 0004 hardens provenance on 6 evidence tables: required keys must be present and non-null, origin-specific fields are enforced, source-backed and computed profiles stay mutually exclusive, and SYNTHETIC and PREDICTED remain rejected
- The Stage 02 gate inputs travel with the review bundle, so a clean extraction fails for the same reason as the publisher workspace

## Stage 02 blocker

- Gate: `stage02_relationship_integrity_pre_live_load`
- Status: **FAIL**
- Failed checks: relationship_manifest_hashes_match, stage02_relationship_manifest_drift, canonical_loader_runtime_principal_undefined, source_subject_key_opacity_undefined, temporal_precision_field_absent_from_model, encounter_provider_id_population_disagreement
- Blocks 7 live operations; does not block 4 storage operations
- Repairs performed: 0; Stage 02 modified: no

An independent recount finds 2 manifest mismatches, not one. The gate previously reported only the first, because the Stage 02 verifier returns on the first difference it sees; it now enumerates all of them. The defect and its scope are unchanged, and nothing in Stage 02 was rewritten.

- `subject-root-analysis.json`: manifest records `285ea434c7f13daa…`, file is `9a685d76cc45cdb9…`
- `identity-linkage-assessment.json`: manifest records `d5481701a6ee435d…`, file is `9bc39761915a7730…`

## Open pre-live-load blockers

- `stage02_relationship_manifest_drift` (OPEN): Do the Stage 02 relationship artifacts still carry the bytes their manifest records? Blocks live load: True; blocks schema-only migration 0004: False
- `canonical_loader_runtime_principal_undefined` (OPEN): Which login principal connects and assumes canonical_loader, from which credential source, by which connection path and SET ROLE flow, with which minimal grants, audit identity and rotation procedure? Blocks live load: True; blocks schema-only migration 0004: False
- `source_subject_key_opacity_undefined` (OPEN): Does an accepted artifact define subject_key_from_id as a keyed pseudorandom transformation with a key reference, key version, namespace, encodings, rotation policy and collision handling? Blocks live load: True; blocks schema-only migration 0004: False
- `temporal_precision_field_absent_from_model` (OPEN): Has the accepted-artifact conflict temporal_precision_field_absent_from_model been resolved? Blocks live load: True; blocks schema-only migration 0004: False
- `encounter_provider_id_population_disagreement` (OPEN): Has the accepted-artifact conflict encounter_provider_id_population_disagreement been resolved? Blocks live load: True; blocks schema-only migration 0004: False

## Finding: Design v0.7.4 review archive

- Finding: `design_v0_7_4_archive_evidence_mismatch`
- Status: **REPRODUCED_CURRENT_ARTIFACT**
- Archive: `artifacts/external-review/stage-03-design-v0.7.4-review.zip`
- Archive SHA-256: `20368132847e291595cf38550bdef9141a74f49967c21c88f66369bc7b718fa9`
- Accepted archive SHA-256 recorded: False (no sidecar was ever published for this archive)

| Design evidence file | SHA-256 in archive | Audited SHA-256 |
| --- | --- | --- |
| `stage-03-design-report.md` | `b748d07810fba253f204ae9bfcad4e59c081566df62aa647c2026f51fd8c4c67` | `6f30b6aaa25a2efa9a6ead3ab7f76563fa688f1f61d94818c2562015d70a6785` |
| `stage-03-design-verification.json` | `df91f0b8127db60d901e3a0b7050540f5192725bae282bf7129bb53a22356b5f` | `ae4a426aa5cb44e03cf509afed54c917af25a2d6283486ab393ae19159f8254c` |

The archive present now, SHA-256 20368132847e291595cf38550bdef9141a74f49967c21c88f66369bc7b718fa9, does not carry the audited Design evidence bytes. This is a statement about this artifact only.

No sidecar was ever published for this archive, so no accepted hash exists for it. What the archive contained at first publication therefore cannot be established, and this finding does not assert it.

The audited bytes in the working tree were recovered from `stage-03-implementation-changeset-01-v0.1-review.zip`, `stage-03-implementation-plan-v0.3.4-review.zip`, each of which carries them.

## Schema-only migration result

- Migration status: PASS
- Applied in this run: []
- Database is empty: True
- Row counts: {'encounter': 0, 'observation': 0, 'observation_component': 0, 'source_record': 0, 'source_system': 0, 'subject': 0, 'subject_characteristic': 0}

## Checks

| Check | Category | Status | Detail |
| --- | --- | --- | --- |
| baseline_status_pass | baseline | PASS | baseline status='PASS' |
| controlled_prior_stage_nine_files_unchanged | baseline | PASS | 9 controlled files, all_unchanged=True |
| design_baseline_v074_manifest_verified | baseline | PASS | verified 11 entries (design v0.7.4) |
| implementation_plan_v035_manifest_verified | baseline | PASS | verified 8 entries (plan v0.3.5) |
| baseline_check_performed_no_auto_restore | baseline | PASS | no prior-stage restoration was performed |
| implementation_gate_open_for_this_changeset | gate_state | PASS | gate_open=True changeset='stage-03-implementation-changeset-01' |
| authorized_changeset_paths_exist | gate_state | PASS | 6 authorized paths |
| forbidden_capabilities_still_closed | gate_state | PASS | 11 capabilities remain forbidden |
| canonical_service_declared | infrastructure | PASS | canonical-db service present |
| canonical_service_postgres_16 | infrastructure | PASS | image='postgres:16' |
| canonical_service_planned_port | infrastructure | PASS | ports=['5436:5432'] |
| canonical_service_dedicated_volume | infrastructure | PASS | volumes=['uhbse_canonical_dev_data:/var/lib/postgresql/data'] |
| canonical_service_planned_database | infrastructure | PASS | POSTGRES_DB='uhbse_canonical_dev' |
| canonical_network_isolated_from_raw_services | infrastructure | PASS | canonical=['canonical-net'] raw=[] |
| canonical_env_file_not_committed | infrastructure | PASS | canonical-db.env untracked (runtime-only) |
| canonical_env_file_referenced_by_compose | infrastructure | PASS | env_file=['canonical-db.env'] |
| canonical_env_file_gitignored | infrastructure | PASS | canonical-db.env listed in .gitignore |
| canonical_env_template_present | infrastructure | PASS | config/canonical-db.env.template |
| canonical_env_template_has_no_secret_values | infrastructure | PASS | all secret assignments are placeholders |
| migrations_discoverable | migrations | PASS | 4 migrations, contiguous from 0001 |
| migrations_contain_no_data_statements | migrations | PASS | no INSERT/UPDATE/DELETE/COPY/TRUNCATE/DROP or cross-database extension |
| migrations_are_idempotent_by_construction | migrations | PASS | guarded CREATE statements present |
| down_migrations_absent_as_planned | migrations | PASS | accepted plan defines no reverse DDL; up->down->up not applicable |
| migrations_reference_no_raw_relations | migrations | PASS | no raw source relation names in migrations |
| published_migrations_are_immutable | hardening | PASS | 3 accepted migrations byte identical |
| schema_corrections_use_a_new_forward_only_migration | hardening | PASS | 0004_storage_contract_hardening.sql present |
| definition_baseline_is_committed_and_self_consistent | hardening | PASS | canonical-definition-baseline.json pins normalized definitions |
| definition_baseline_traces_to_the_accepted_migrations | hardening | PASS | pinned definitions were produced by exactly these migration bytes |
| definition_baseline_covers_every_pinned_section | hardening | PASS | 8 of 8 sections pinned |
| provenance_hardening_constraints_are_pinned | hardening | PASS | 18 hardening constraints pinned |
| integration_migration_suite_is_mandatory | hardening | PASS | a missing, skipped or failing integration suite blocks publication |
| stage_02_gate_inputs_travel_with_the_bundle | hardening | PASS | 9 gate inputs bundled so a clean extraction fails identically |
| pre_live_load_blockers_are_recorded_open | hardening | PASS | open: ['canonical_loader_runtime_principal_undefined', 'encounter_provider_id_population_disagreement', 'source_subject_key_opacity_undefined', 'stage02_relationship_manifest_drift', 'temporal_precision_field_absent_from_model'] |
| open_blockers_do_not_block_schema_only_migration | hardening | PASS | migration 0004 stays applicable while live load is blocked |
| frozen_design_report_match | isolation | PASS | stage-03-design-report.md carries the audited bytes |
| frozen_design_verification_match | isolation | PASS | stage-03-design-verification.json carries the audited bytes |
| all_frozen_evidence_unchanged | isolation | PASS | 36 frozen inputs byte identical |
| automatic_restore_performed | isolation | PASS | no evidence was repaired automatically; recovery is a confirmed human action |
| frozen_baseline_covers_every_category | isolation | PASS | 7 categories pinned including the two generated Design evidence files no manifest covers |
| recovery_unreachable_from_the_pipeline | isolation | PASS | no gate, suite or publisher can repair frozen evidence |
| publication_tests_are_isolated | isolation | PASS | every publishing test runs in a throwaway workspace copy |
| publication_lock_verified | isolation | PASS | the publication pipeline runs under an exclusive inter-process lock |
| publication_lock_excluded_from_bundle | isolation | PASS | no transient publication-lock artifact is a review bundle member; uv.lock is a dependency lockfile, is unrelated to publication locking, and is bundled |
| stage_02_manifest_mismatches_enumerated | isolation | PASS | independent check reports subject-root-analysis.json, identity-linkage-assessment.json; Stage 02 not modified |
| every_open_blocking_conflict_is_a_gate_check | hardening | PASS | 2 OPEN BLOCKS_LIVE_LOAD conflicts enforced as FAIL checks |
| all_five_pre_live_load_blockers_fail_closed | hardening | PASS | gate FAIL with blockers ['canonical_loader_runtime_principal_undefined', 'encounter_provider_id_population_disagreement', 'source_subject_key_opacity_undefined', 'stage02_relationship_manifest_drift', 'temporal_precision_field_absent_from_model'] |
| blocker_resolution_requires_a_structured_contract | hardening | PASS | neither contract exists, so both blockers stay OPEN: no accepted release defines subject_key_transformation_contract at its authoritative path artifacts/stage-03/canonical-id-contract.yaml; no accepted release defines canonical_loader_runtime_contract at its authoritative path artifacts/stage-03-implementation/security-runtime-plan.yaml |
| unkeyed_digests_cannot_close_the_subject_key_blocker | hardening | PASS | only keyed PRFs are accepted; bare SHA-256, hash, digest and unqualified HMAC are rejected |
| gate_evaluation_is_read_only | hardening | PASS | 36 frozen inputs identical before and after; no repair, no manifest written, no database connection, no clinical row read |
| design_archive_finding_is_hash_bound | hardening | PASS | REPRODUCED_CURRENT_ARTIFACT; archive sha256 20368132847e291595cf38550bdef9141a74f49967c21c88f66369bc7b718fa9; no historical corruption asserted without the hash of a corrupted archive |
| contract_authority_excludes_the_changeset_directory | hardening | PASS | a changeset cannot author the contract that unblocks it; authoritative paths are canonical_loader_runtime_contract -> artifacts/stage-03-implementation/security-runtime-plan.yaml (Stage 03 Implementation Plan), subject_key_transformation_contract -> artifacts/stage-03/canonical-id-contract.yaml (Stage 03 Design) |
| authoritative_paths_are_release_manifest_covered | hardening | PASS | each authoritative path is listed in its owning release manifest |
| algorithm_matching_is_exact_not_substring | hardening | PASS | names that contain a canonical identifier without being one are rejected |
| accepted_artifact_conflict_registry_valid | hardening | PASS | 2 conflicts, 2 open and blocking, registry sha256 cc5f3a8b815d1533bef6361ed8f2472cee157b681315e1da604a51ee3752b54b; every OPEN blocking conflict is a gate check |
| conflict_registry_validity_is_a_gate_check | hardening | PASS | damaging the registry adds a failure instead of silently removing blocker checks |
| no_conflict_identifier_is_hardcoded | hardening | PASS | conflict checks are derived from the registry alone |
| no_contract_instance_was_created | hardening | PASS | both contract blockers stay OPEN: no accepted release defines either contract |
| schema_contract_covers_exactly_pilot_entities | schema_contract | PASS | 7 tables for 7 pilot entities |
| provenance_is_embedded_not_a_table | schema_contract | PASS | Provenance has no table; it is an embedded jsonb column |
| provenance_column_present_where_required | schema_contract | PASS | 6/6 entities requiring provenance carry the column |
| source_system_carries_no_row_provenance | schema_contract | PASS | provenance-contract entity_exceptions.SourceSystem honoured |
| no_forbidden_identifier_columns | schema_contract | PASS | no global_patient_id, global_subject_id or raw primary key columns |
| subject_identity_is_source_local_unique | schema_contract | PASS | unique (source_system_id, source_subject_key) |
| source_locator_unique | schema_contract | PASS | unique source_record_locator |
| canonical_id_unique_index_per_entity | schema_contract | PASS | single-column canonical identifier primary key on every pilot table |
| fk_graph_matches_pipeline_load_order | schema_contract | PASS | every foreign key target is loaded earlier |
| subject_characteristic_typed_value_xor_declared | schema_contract | PASS | exactly-one typed value constraint declared over the five typed columns |
| subject_characteristic_identity_not_xor | schema_contract | PASS | at least one of characteristic_code or concept_id; XOR-only identity forbidden |
| raw_value_preserved_after_normalization | schema_contract | PASS | subject_characteristic.raw_value is NOT NULL |
| observation_component_typed_value_not_invented | schema_contract | PASS | no XOR invented for an entity the model does not constrain |
| temporal_columns_are_timestamptz | schema_contract | PASS | all *_at columns are timezone-aware |
| missing_clinical_time_requires_documented_reason | schema_contract | PASS | encounter and observation require missingness_reason when clinical time is null |
| pilot_null_only_columns_match_accepted_plan | schema_contract | PASS | deferred and out-of-scope references are constrained to NULL |
| provenance_profile_check_on_every_provenance_table | schema_contract | PASS | profile validation constraint present |
| schema_contract_fingerprint_stable | schema_contract | PASS | contract_fingerprint=99e3610fb9f828ec... |
| all_planned_roles_declared | roles | PASS | 4 roles declared |
| roles_created_nologin | roles | PASS | roles are NOLOGIN and no password appears in any migration |
| loader_receives_select_and_insert_only | roles | PASS | canonical_loader holds SELECT and INSERT only |
| loader_denied_update_delete_truncate | roles | PASS | no UPDATE, DELETE or TRUNCATE granted to canonical_loader |
| validator_receives_select_only | roles | PASS | canonical_validator_ro is read-only |
| schema_owned_by_canonical_owner | roles | PASS | canonical_evidence owned by canonical_owner |
| public_schema_create_revoked | roles | PASS | no implicit object creation for PUBLIC |
| canonical_code_reads_no_raw_relations | safety | PASS | no raw source relation appears in canonical storage code |
| canonical_target_guard_present | safety | PASS | canonical tooling refuses raw databases and raw ports |
| raw_target_guard_present | safety | PASS | raw tooling refuses the canonical database |
| no_pilot_cohort_or_load_code | safety | PASS | no cohort selection, extraction or load implementation present |
| changeset_artifacts_have_no_secrets_or_dsn | safety | PASS | no literal credential-bearing DSN or secret included: no connection string, password, secret, token or key value appears in a changeset artifact |
| pre_live_load_gate_executable | stage_02_blocker | PASS | gate_id=stage02_relationship_integrity_pre_live_load |
| pre_live_load_gate_fails_on_current_stage_02_drift | stage_02_blocker | PASS | gate status=FAIL, failed checks=['relationship_manifest_hashes_match', 'stage02_relationship_manifest_drift', 'canonical_loader_runtime_principal_undefined', 'source_subject_key_opacity_undefined', 'temporal_precision_field_absent_from_model', 'encounter_provider_id_population_disagreement'] |
| pre_live_load_gate_did_not_modify_stage_02 | stage_02_blocker | PASS | Stage 02 bytes identical before and after gate evaluation |
| gate_blocks_every_live_operation | stage_02_blocker | PASS | 7 live operations blocked while the gate fails |
| gate_does_not_block_empty_storage_or_migrations | stage_02_blocker | PASS | storage creation and migration operations never consult the live-load gate |
| gate_performs_no_repair | stage_02_blocker | PASS | gate repaired nothing and restored nothing |
| artifact_changeset-01-plan.yaml | artifacts | PASS | present |
| artifact_unresolved-changeset-01-decisions.yaml | artifacts | PASS | present |
| artifact_accepted-artifact-conflicts.yaml | artifacts | PASS | present |
| artifact_canonical-schema-contract.json | artifacts | PASS | present |
| artifact_canonical-definition-baseline.json | artifacts | PASS | present |
| artifact_pre-live-load-blockers.yaml | artifacts | PASS | present |
| artifact_live-load-contract-schema.yaml | artifacts | PASS | present |
| artifact_contract-authority-policy.yaml | artifacts | PASS | present |
| plan_declares_frozen_versions | artifacts | PASS | design='0.7.4' plan='0.3.5' |
| plan_declares_no_data_load | artifacts | PASS | implementation_status='empty_storage_and_migrations_only' |
| detected_artifact_conflicts_recorded | artifacts | PASS | 2 conflicts recorded, none repaired |
| no_design_or_plan_artifact_modified_for_conflicts | artifacts | PASS | conflicts recorded without touching frozen artifacts |
| blocking_decisions_declared_consistently | artifacts | PASS | 3 decisions block the next phase |
| report_status_draft | artifacts | PASS | changeset report is DRAFT and never claims FINAL |
| changeset_manifest_hashes_match | artifacts | PASS | 8 content entries verified |
| changeset_manifest_excludes_generated_evidence | artifacts | PASS | manifest excludes report, verification and release evidence |

## Test suites

| Suite | Exit | Collected | Selected | Deselected | Passed | Failed | Skipped | Seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| changeset_01_gate_suite | 0 | 156 | 152 | 4 | 152 | 0 | 0 | 171.972 |
| clean_review_bundle_suite | 0 | 367 | 359 | 8 | 359 | 0 | 0 | 205.609 |
| full_repository_suite | 0 | 803 | 791 | 12 | 791 | 0 | 0 | 442.395 |
| integration_migration_suite | 0 | 803 | 91 | 712 | 91 | 0 | 0 | 3.697 |

Literal commands:

- `changeset_01_gate_suite`: `uv run pytest tests/test_canonical_schema_contract.py tests/test_canonical_migrations_static.py tests/test_stage02_pre_live_load_gate.py tests/test_changeset_01_verifier.py tests/test_changeset_01_review_bundle.py -q -m 'not publisher_only and not integration'`
- `clean_review_bundle_suite`: `uv run pytest tests/test_verify_stage_03_design.py tests/test_verify_implementation_plan.py tests/test_stage03_contracts.py tests/test_review_bundle_validation.py tests/test_prior_stage_integrity.py tests/test_canonical_schema_contract.py tests/test_canonical_migrations_static.py tests/test_stage02_pre_live_load_gate.py tests/test_changeset_01_verifier.py tests/test_changeset_01_review_bundle.py -q -m 'not publisher_only and not integration' -k 'not test_published_verification_matches_final_report_bytes and not test_full_pytest_suite_preserves_publication_artifacts and not test_full_pytest_suite_does_not_mutate_prior_stage_artifacts and not test_implementation_plan_clean_extraction_gate and not test_unpacked_zip_pytest_preserves_publication_artifacts'`
- `full_repository_suite`: `uv run pytest -q -m 'not verify_stage02_gate and not publisher_only' -k 'not test_implementation_plan_clean_extraction_gate'`
- `integration_migration_suite`: `uv run pytest -q -m integration`

- Overall release status: **PASS**
- Prior-stage bytes unchanged across all suites: True

## Explicit non-actions

- No clinical row was read from Source A or Source B
- No extraction, transformation, load or ETL was executed
- No pilot cohort was created
- No data was loaded into the canonical database
- No raw database was modified
- No Stage 01 or Stage 02 artifact was modified
- Source B was not connected
- No patient linkage or merge was performed
- No simulation or prediction work was started
- Design v0.7.4 and Plan v0.3.5 were not changed
- No literal credential-bearing DSN or secret was included in any artifact; no PII, HMAC value or raw value was stored
- No Stage 02 maintenance was started and the manifest drift was not repaired
- No pre-live-load blocker was resolved; the two contracts remain unwritten
- Migrations 0001-0004 were not modified and no migration 0005 was created
- The canonical schema and the definition baseline were not changed
- No schema drift found by the verifier was repaired automatically
- No frozen evidence was restored automatically; recovery required explicit confirmation and installed only audited bytes
- Design evidence was recovered from an accepted release, never regenerated
- The v0.2 and v0.2.1 review bundles were not overwritten
- The Design v0.7.4 review bundle was not republished
- Changeset 02 was not started

## Status

Report status: DRAFT. Stage 03 is not promoted to FINAL and Changeset 02 has not been started.
