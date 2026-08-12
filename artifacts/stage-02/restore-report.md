# Restore report — source B (kgz)

**Started:** 2026-07-31T16:29:00.750023+00:00
**Completed:** 2026-07-31T16:48:46.608756+00:00
**Target database:** `kgz_raw`
**Preflight status:** PASS
**Restore performed:** True
**pg_restore exit code:** 0
**pg_restore version (in kgz-db container):** `pg_restore (PostgreSQL) 14.13 (Debian 14.13-1.pgdg110+1)`
**Message:** Restore completed; post-restore verification finished (timing backfilled)

## Restore timing

- **restore_timing_not_captured:** `True`
- **timing_source:** `preflight generated_at plus observed pg_restore duration (~408s); post-restore timestamps captured by complete_post_restore`
- **restore_started_at_estimated:** `2026-07-31T16:29:00.750023+00:00`
- **restore_completed_at_estimated:** `2026-07-31T16:35:48.750023+00:00`
- **restore_duration_seconds_estimated:** `408`
- **post_restore_completed_at:** `2026-07-31T16:48:46.608756+00:00`

## CLI failure and recovery

- **failed_step:** `create_readonly_audit_user`
- **error_type:** `ProgrammingError`
- **error_summary:** `CREATE ROLE ... PASSWORD :pwd bind rejected by PostgreSQL (SQLAlchemy text bind)`
- **recovery:** `manual: python -m human_simulator.stage02.complete_post_restore after psycopg.sql fix`
- **bind_parameter_fix:** `CREATE ROLE uses psycopg.sql composable via driver_connection cursor`
- **resolved:** `True`

## pg_restore message counts

- **error_lines:** `0`
- **warning_lines:** `0`
- **stderr_line_count:** `1`
- **stdout_line_count:** `0`

## Post-restore inventory

- **schema_count:** `5`
- **table_count:** `132`
- **view_count:** `4`
- **sequence_count:** `102`
- **function_count:** `949`
- **extensions:** `[{'name': 'fuzzystrmatch', 'version': '1.1'}, {'name': 'pg_stat_statements', 'version': '1.9'}, {'name': 'plpgsql', 'version': '1.0'}, {'name': 'postgis', 'version': '3.4.3'}, {'name': 'postgis_tiger_geocoder', 'version': '3.4.3'}, {'name': 'postgis_topology', 'version': '3.4.3'}]`
- **database_size_bytes:** `14612792099`
- **server_version:** `14.13 (Debian 14.13-1.pgdg110+1)`

## Read-only audit user

- **username:** `kgz_audit_ro`
- **redacted_connection:** `postgresql://kgz_audit_ro:***@localhost:5435/kgz_raw`
- **default_transaction_read_only:** `True`
- **schemas_granted:** `['public', 'quest_digital', 'tiger', 'tiger_data', 'topology']`

## Read-only verification

- **username:** `kgz_audit_ro`
- **can_select:** `True`
- **insert_blocked:** `True`
- **update_blocked:** `True`
- **delete_blocked:** `True`
- **ddl_blocked:** `True`
- **role_flags:** `{'rolcreatedb': False, 'rolcreaterole': False, 'rolsuper': False, 'rolcanlogin': True}`
- **sample_table:** `public.abac_rules`
- **sample_table_class:** `application`
- **default_transaction_read_only:** `True`
- **read_only_ok:** `True`

## Auditor connection (use for profiling B)

`postgresql+psycopg://kgz_audit_ro:***@localhost:5435/kgz_raw`

## Source A verification

- **expected_database:** `magerya_api`
- **expected_port:** `5434`
- **current_fingerprint_sha256:** `01272eab2d7d29ee4cd5a90a81e724f02e691c8da5e27ce65afb19a91227919e`
- **current_table_count:** `206`
- **current_schema_count:** `4`
- **unchanged:** `True`
- **baseline_status:** `established_now`
- **baseline_note:** `no_prior_stage01_baseline; fingerprint saved for future comparisons`
- **unchanged_rationale:** `restore targeted kgz-db only; baseline captured post-restore for stage-01 gate`

Log excerpt: `artifacts/stage-02/restore-pg_restore.log`
