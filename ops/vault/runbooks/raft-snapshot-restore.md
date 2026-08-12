# Raft Snapshot / Restore — UHBSE Vault

Applies to single-node Integrated Storage (Raft) at `/vault/data`.

## Snapshot (operator)

Vault must be initialized and unsealed. Operator token required.

```bash
export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT="$PWD/ops/vault/tls/ca.crt"
# VAULT_TOKEN set in shell only

mkdir -p ops/vault/operator-custody/snapshots
chmod 700 ops/vault/operator-custody ops/vault/operator-custody/snapshots

OUT="ops/vault/operator-custody/snapshots/raft-$(date -u +%Y%m%dT%H%M%SZ).snap"
vault operator raft snapshot save "$OUT"
chmod 600 "$OUT"
```

Or via helper:

```bash
./ops/vault/scripts/raft-snapshot.sh
```

Snapshots contain secret material — **git-ignored**, offline custody only. Never attach to review ZIP.

## Restore

1. Stop writers / put Vault in maintenance.
2. `docker compose stop vault`
3. Replace Raft data only with a known-good procedure:
   - preferred: `vault operator raft snapshot restore` against a running sealed/unsealed node per HashiCorp docs for your version;
   - disaster: restore volume from offline backup taken consistently with snapshot policy.
4. `docker compose start vault`
5. Unseal (`./ops/vault/scripts/unseal-pgp.sh`)
6. `./ops/vault/scripts/preflight.sh`

## Verification after restore

- `vault status` → initialized=true, sealed=false (strict TLS)
- KV mount `uhbse/` present
- metadata for both secret paths present
- audit device still enabled
- preflight overall PASS

## Non-goals

Do not snapshot into `artifacts/` or `artifacts/external-review/`.
