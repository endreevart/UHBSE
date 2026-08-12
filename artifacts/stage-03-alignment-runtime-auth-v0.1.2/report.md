# Runtime Auth v0.1.2 — Report

**Report status:** DRAFT

## Component statuses

{
  "direct_approle_api_smoke": "PASS",
  "vault_agent_configuration_static_validation": "PASS",
  "vault_agent_runtime_execution": "PASS",
  "vault_agent_restart_reauthentication": "PASS",
  "wrapped_secret_id_independence": "PASS",
  "agent_token_policy_lookup": "PASS"
}

## Contract

- status: **PARTIAL_RUNTIME_VERIFIED**
- complete: false
- open_blockers: initial_root_token_available, limited_operator_identity_absent, vault_key_custody_decision_required, pgp_keys_shared_keyring_empty_passphrase, multi_custodian_separation_absent

## Publication

Atomic publisher computes publication_integrity_status from verification results only.
