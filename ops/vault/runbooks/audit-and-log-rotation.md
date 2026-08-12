# Audit Device and Log Rotation — UHBSE Vault

Enable **after** initialization and unseal. Audit logs may contain sensitive request metadata — treat as secret-adjacent.

## Enable persistent file audit

Inside the container, audit path is the mounted volume `/vault/audit`:

```bash
export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT="$PWD/ops/vault/tls/ca.crt"
# VAULT_TOKEN in environment only

vault audit enable file file_path=/vault/audit/vault-audit.log
vault audit list -format=json
```

Or:

```bash
./ops/vault/scripts/enable-audit.sh
```

Preflight checks that a file audit device is enabled (path recorded, contents not copied to artifacts).

## Log rotation (host)

Docker volume `uhbse_vault_audit` holds the audit file. Rotate on the host with logrotate (example):

```
# /etc/logrotate.d/uhbse-vault-audit  (operator-managed; not required in Git)
/var/lib/docker/volumes/humansimulator_uhbse_vault_audit/_data/vault-audit.log {
  weekly
  rotate 12
  compress
  delaycompress
  missingok
  notifempty
  copytruncate
}
```

Alternatively copy-truncate via operator cron against the volume mount path discovered with `docker volume inspect uhbse_vault_audit`.

After rotation, confirm Vault still appends (no restart required with `copytruncate`).

## Evidence rules

- Do not commit audit log contents
- Preflight may record `audit_device_enabled=true` and device type/path only
- `secrets_recorded_in_artifacts` must remain false
