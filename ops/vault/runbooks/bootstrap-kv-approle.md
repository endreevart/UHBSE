# Bootstrap KV v2 + AppRole — UHBSE Vault

**Identity separation (mandatory):**

| Layer | Name |
|------|------|
| Vault AppRole | `uhbse-canonical-loader` |
| PostgreSQL LOGIN | `canonical_loader_login` (not created while plan is on hold) |
| PostgreSQL NOLOGIN | `canonical_loader` |

## Prerequisites

- Raft Vault initialized, unsealed, strict TLS
- `VAULT_TOKEN` in shell (from PGP-decrypt helper)
- `VAULT_CACERT` set — **no** `-tls-skip-verify`

## Commands

```bash
export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT="$PWD/ops/vault/tls/ca.crt"

vault secrets enable -path=uhbse -version=2 kv
vault policy write uhbse-canonical-loader ops/vault/policies/uhbse-canonical-loader.hcl
vault auth enable approle

vault write auth/approle/role/uhbse-canonical-loader \
  token_policies="uhbse-canonical-loader" \
  token_ttl=1h \
  token_max_ttl=4h \
  secret_id_ttl=24h \
  bind_secret_id=true
```

Write version-1 secret shells (values from stdin / generator — never Git):

```bash
# HMAC material and loader password are operator-generated; not logged.
./ops/vault/scripts/bootstrap-kv-approle.sh
```

Contract references:

```text
vault://uhbse/canonical/hmac-subject-key?version=1
vault://uhbse/canonical/loader-credential?version=1
```

Then enable audit (`ops/vault/runbooks/audit-and-log-rotation.md`) and run:

```bash
./ops/vault/scripts/preflight.sh
```
