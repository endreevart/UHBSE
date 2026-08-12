# Init and Unseal — UHBSE Vault (PGP-encrypted, Raft)

**Storage:** single-node Integrated Storage (Raft) at `/vault/data`  
**Forbidden:** plaintext init output under `/tmp`, Git, logs, review ZIP.

## Prerequisites

1. `./ops/vault/scripts/generate-tls.sh`
2. `./ops/vault/scripts/generate-operator-pgp.sh` (creates git-ignored PGP keys)
3. Fresh Raft volume (never reuse a filesystem-storage volume)
4. `docker compose up -d vault`
5. `VAULT_ADDR=https://127.0.0.1:8200` and `VAULT_CACERT=$PWD/ops/vault/tls/ca.crt`

## 1. Confirm uninitialized

```bash
VAULT_ADDR=https://127.0.0.1:8200 VAULT_CACERT="$PWD/ops/vault/tls/ca.crt" \
  docker exec -e VAULT_ADDR -e VAULT_CACERT human-simulator-vault \
  vault status -format=json | python3 -c 'import json,sys; print(json.load(sys.stdin)["initialized"])'
```

Must print `False` before first init.

## 2. Initialize with PGP (no plaintext /tmp)

Public keys (git-ignored, created by generate-operator-pgp.sh):

- `ops/vault/pgp/op1.asc`
- `ops/vault/pgp/op2.asc`
- `ops/vault/pgp/op3.asc`

Write encrypted init material only to operator custody (git-ignored):

```bash
mkdir -p ops/vault/operator-custody
chmod 700 ops/vault/operator-custody

VAULT_ADDR=https://127.0.0.1:8200 VAULT_CACERT="$PWD/ops/vault/tls/ca.crt" \
  docker exec -i -e VAULT_ADDR -e VAULT_CACERT human-simulator-vault \
  vault operator init \
    -key-shares=3 \
    -key-threshold=2 \
    -pgp-keys="$(cat ops/vault/pgp/op1.asc | docker exec -i human-simulator-vault sh -c 'cat > /tmp/op1.asc; echo /tmp/op1.asc')" \
    ...
```

Prefer the helper (keeps ciphertext out of `/tmp` on the host):

```bash
./ops/vault/scripts/init-pgp.sh
```

This writes **only** PGP-ciphertext JSON to:

`ops/vault/operator-custody/init-encrypted.json`

Fields `unseal_keys_b64` / `unseal_keys_hex` are base64 of **PGP ciphertext**, not raw shares.
`root_token` is PGP-encrypted for op1.

## 3. Unseal (decrypt locally, never log shares)

```bash
./ops/vault/scripts/unseal-pgp.sh
```

Uses threshold shares decrypted via local `gpg` against git-ignored private keys.
Does not print shares or write plaintext shares to disk.

## 4. Root token

Decrypt root token into a shell environment variable for bootstrap only:

```bash
# helper sets VAULT_TOKEN in the current shell via eval (not written to disk)
eval "$(./ops/vault/scripts/decrypt-root-token.sh --export)"
```

Revoke/rotate root after bootstrap when an operator token exists.

## 5. Next

1. `ops/vault/runbooks/bootstrap-kv-approle.md`
2. `ops/vault/runbooks/audit-and-log-rotation.md`
3. `./ops/vault/scripts/preflight.sh`
