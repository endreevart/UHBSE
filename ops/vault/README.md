# UHBSE Vault (vault-stop v0.2.1)

Production HashiCorp Vault — single-node Raft, TLS, PGP-encrypted init.

## Confirmed references

| Item | Value |
|------|--------|
| KV mount | `uhbse` (KV v2) |
| Paths | `canonical/hmac-subject-key`, `canonical/loader-credential` |
| URIs | `vault://uhbse/canonical/hmac-subject-key?version=1`, `vault://uhbse/canonical/loader-credential?version=1` |
| AppRole | `uhbse-canonical-loader` |
| PG LOGIN | `canonical_loader_login` (HOLD — not created) |
| PG NOLOGIN | `canonical_loader` |

## Operator sequence

```bash
./ops/vault/scripts/generate-tls.sh
./ops/vault/scripts/generate-operator-pgp.sh
docker compose up -d vault
./ops/vault/scripts/init-pgp.sh
./ops/vault/scripts/unseal-pgp.sh
eval "$(./ops/vault/scripts/decrypt-root-token.sh --export)"
./ops/vault/scripts/bootstrap-kv-approle.sh
./ops/vault/scripts/enable-audit.sh
./ops/vault/scripts/preflight.sh
```

See runbooks for snapshot/restore and audit log rotation.
