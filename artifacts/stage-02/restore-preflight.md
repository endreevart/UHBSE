# Restore preflight — source B (kgz)

**Generated:** 2026-07-31T16:29:00.750023+00:00
**Target database:** `kgz_raw` (explicit, not from dump TOC)
**Dump path:** `kgz-20231204.dump`
**Overall preflight status:** **PASS**

## Checks

| Check | Status | Message |
|-------|--------|---------|
| `dump_exists` | PASS | Dump file found |
| `dump_format` | PASS | PostgreSQL custom format (PGDMP) |
| `dump_sha256` | PASS | SHA-256 computed |
| `dump_size` | PASS | Dump size recorded |
| `pg_restore_compat` | PASS | pg_restore --list succeeded |
| `disk_space` | PASS | Sufficient free disk space |
| `toc_entry_discrepancy` | PASS | TOC header vs list discrepancy explained |
| `port_5435` | PASS | Port 5435 belongs to expected kgz-db service |
| `kgz_raw_empty` | PASS | Target database is empty (no non-extension user tables) |
| `target_postgresql_version` | PASS | Target PostgreSQL version recorded |
| `dump_extensions_available` | PASS | All dump extensions available on target (including pg_stat_statements if present) |
| `source_a_unchanged` | PASS | Source A configuration unchanged; kgz-db isolated on port 5435 |
| `pg_restore_command` | PASS | pg_restore command uses --no-owner and --no-privileges; no --clean/--create/--drop |
| `restore_policy` | PASS | audit restore-second-source --confirm refuses restore when preflight status is FAIL or PARTIAL (any SKIP/FAIL/WARN check). |

## Check details

### `dump_exists`

- **path:** `kgz-20231204.dump`

### `dump_format`

- **format:** `postgresql_custom`
- **archive_version:** `1.14`

### `dump_sha256`

- **sha256:** `11214bb74a73fe4dd255bf91d92486ea52f340c7443975f2dc8b3e6ac961f2e8`

### `dump_size`

- **size_bytes:** `1651984549`
- **size_human:** `1.5 GB`

### `pg_restore_compat`

- **pg_restore_version:** `pg_restore (PostgreSQL) 16.14 (Homebrew)`
- **archive_version:** `1.14`
- **pg_restore_list_exit_code:** `0`
- **toc_entry_count:** `783`

### `disk_space`

- **required_bytes:** `3303969098`
- **required_human:** `3.1 GB`
- **free_bytes:** `687801688064`
- **free_human:** `640.6 GB`
- **multiplier:** `2.0`

### `toc_entry_discrepancy`

- **header_toc_entries:** `788`
- **listed_active_entries:** `783`
- **comment_lines:** `15`
- **discrepancy:** `5`
- **explanation:** `Archive header reports 788 embedded TOC entries. pg_restore --list outputs 783 active lines (matching '^\\d+;'). Comment/semicolon lines in list output: 15. Delta 5: header count includes archive metadata entries; list output excludes semicolon-prefixed comment lines and may omit non-restorable or duplicate-index entries present in the archive TOC.`

### `port_5435`

- **host:** `localhost`
- **port:** `5435`
- **port_open:** `True`
- **docker_compose_port:** `0.0.0.0:5435`
- **docker_container_name:** `human-simulator-kgz-db`
- **expected_service:** `kgz-db`
- **expected_container:** `human-simulator-kgz-db`
- **port_mapping_ok:** `True`
- **container_running_ok:** `True`

### `kgz_raw_empty`

- **table_count:** `0`
- **database:** `kgz_raw`

### `target_postgresql_version`

- **server_version:** `14.13 (Debian 14.13-1.pgdg110+1)`
- **version_string:** `PostgreSQL 14.13 (Debian 14.13-1.pgdg110+1) on x86_64-pc-linux-gnu`
- **current_database:** `kgz_raw`
- **redacted_url:** `postgresql+psycopg://kgz_raw:***@localhost:5435/kgz_raw`

### `dump_extensions_available`

- **required_extensions:** `['pg_stat_statements']`
- **available_extensions:** `['pg_stat_statements']`
- **already_installed:** `[]`
- **missing_from_available:** `[]`

### `source_a_unchanged`

- **expected_host:** `localhost`
- **expected_port:** `5434`
- **expected_database:** `magerya_api`
- **expected_user:** `magerya_api`
- **compose_mg_db_port_mapping_ok:** `True`
- **compose_kgz_db_isolated:** `True`

### `pg_restore_command`

- **command_redacted:** `docker compose exec -T kgz-db pg_restore -U kgz_raw -d kgz_raw --no-owner --no-privileges --role=kgz_raw < kgz-20231204.dump`
- **forbidden_flags_absent:** `('--clean', '--create', '--drop')`
- **required_flags_present:** `('--no-owner', '--no-privileges')`
- **forbidden_found:** `[]`
- **missing_required:** `[]`

### `restore_policy`

- **requires_preflight_status:** `PASS`

## Dump metadata

- **path:** `kgz-20231204.dump`
- **size_bytes:** `1651984549`
- **sha256:** `11214bb74a73fe4dd255bf91d92486ea52f340c7443975f2dc8b3e6ac961f2e8`
- **format_label:** `postgresql_custom`
- **archive_version:** `1.14`
- **toc_entry_count:** `783`
- **toc_header_count:** `788`
- **dump_extensions:** `['pg_stat_statements']`
- **pg_restore_version:** `pg_restore (PostgreSQL) 16.14 (Homebrew)`

## Planned pg_restore (redacted credentials)

```bash
docker compose exec -T kgz-db pg_restore -U kgz_raw -d kgz_raw --no-owner --no-privileges --role=kgz_raw < kgz-20231204.dump
```

Forbidden flags (absent): --clean, --create, --drop
Required flags (present): --no-owner, --no-privileges

## Restore policy

restore-second-source requires preflight status PASS; any FAIL, SKIP, or WARN blocks restore.

## pg_restore --list (sample, first entries)

```
;
; Archive created at 2023-12-04 08:21:14 MSK
;     dbname: magerya_base
;     TOC Entries: 788
;     Compression: gzip
;     Dump Version: 1.14-0
;     Format: CUSTOM
;     Integer: 4 bytes
;     Offset: 8 bytes
;     Dumped from database version: 12.7
;     Dumped by pg_dump version: 14.9 (Ubuntu 14.9-0ubuntu0.22.04.1)
;
;
; Selected TOC Entries:
;
7; 2615 673534 SCHEMA - quest_digital magerya_base
2; 3079 234346 EXTENSION - pg_stat_statements 
5096; 0 0 COMMENT - EXTENSION pg_stat_statements 
205; 1259 673535 TABLE public abac_rules magerya_base
206; 1259 673540 SEQUENCE public abac_rules_id_seq magerya_base
```

## Next step

Restore is **not** executed by preflight. After review, run in order:

```bash
cp db-kgz.env.example db-kgz.env   # set POSTGRES_PASSWORD locally (once)
docker compose up -d kgz-db
audit --root . restore-preflight
audit --root . restore-second-source --confirm
```

Restore refuses non-empty `kgz_raw`, requires `--confirm`, and blocks on any preflight FAIL/SKIP/WARN.
