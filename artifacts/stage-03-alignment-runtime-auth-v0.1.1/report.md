# Runtime Auth Correction v0.1.1 — Report

**Report status:** DRAFT

## Component statuses

| Component | Status |
|-----------|--------|
| direct_approle_api_smoke | PASS |
| vault_agent_configuration_static_validation | PASS |
| vault_agent_runtime_execution | PASS |
| vault_agent_restart_reauthentication | PASS |

## Contract

- status: **PARTIAL_RUNTIME_VERIFIED**
- complete: false
- open_blockers: initial_root_token_available, limited_operator_identity_absent, multi_custodian_separation_absent, pgp_keys_shared_keyring_empty_passphrase, vault_key_custody_decision_required

## Invariants

- schema fingerprint unchanged: True
- row counts remain zero: True
- postgres principal unchanged: True
- clinical_rows_read: 0
- raw_db_connections: 0
- canonical_rows_written: 0

## Classification note

Static HCL validation and direct Python AppRole login do **not** prove Vault Agent execution.
`vault_agent_runtime_execution` is PASS only after a live Process Supervisor Agent cycle.
