---
name: restore-second-source
description: Restore kgz-20231204.dump as a separate immutable PostgreSQL source B.
disable-model-invocation: true
---

Read `AGENTS.md`, `docs/stage-02.md`, and applicable project rules.

Restore source B from `kgz-20231204.dump` into a **separate** database instance.
Do not touch source A (`magerya_api` on port 5434) except for read-only baseline reads.

## Confirmation gate (mandatory)

**Do not run restoration without explicit human confirmation.**

Before any restore:

1. Present planned container/service name, host port, database name, and restore script.
2. Report dump file size and estimated disk need.
3. Run `pg_restore --list kgz-20231204.dump` to discover database name, encoding, and extensions — **list only, no restore**.
4. Stop and wait for user approval.

Proceed only after the user confirms (e.g. “confirm restore” or explicit approval in chat).

## After confirmation

1. Start the dedicated B database service (separate volume from A).
2. Restore `kgz-20231204.dump` using the B-specific restore script.
3. Verify connectivity and read-only enforcement on B.
4. Record PostgreSQL version and database metadata.

## Output

Write `artifacts/stage-02/source-b-audit.json` with:

- dump path and file hash (SHA-256 of dump file);
- restore timestamp (UTC);
- connection parameters (host, port, database, user — no password);
- read-only verification result;
- PostgreSQL version;
- discovered extensions.

## Constraints

- Do not modify `kgz-20231204.dump` on disk.
- Do not restore into source A's database or volume.
- Do not merge A and B.
- Do not print row-level data or secrets.

Planned CLI: `audit restore-preflight` then `audit restore-second-source --confirm`
