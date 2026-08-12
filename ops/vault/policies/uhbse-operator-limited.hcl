# Policy: uhbse-operator-limited
# Human limited operator (userpass). NOT the loader AppRole.
# NOT a PostgreSQL principal.
#
# Allows: health/status, self token lifecycle, read loader AppRole metadata,
# controlled wrapped SecretID issuance for uhbse-canonical-loader only,
# read own/loader ACL policies, token lookup for operational verification.
#
# Denies by omission unless listed: root, sudo, auth method mutation,
# arbitrary policy writes, storage, audit configuration, KV secret material,
# unseal/rekey configuration changes.

# --- Health / seal status (no secrets) ---
path "sys/health" {
  capabilities = ["read"]
}

path "sys/seal-status" {
  capabilities = ["read"]
}

path "sys/leader" {
  capabilities = ["read"]
}

# --- Self token lifecycle ---
path "auth/token/lookup-self" {
  capabilities = ["read"]
}

path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/revoke-self" {
  capabilities = ["update"]
}

# Operator may look up a subject token (e.g. Agent sink) without retaining its value.
path "auth/token/lookup" {
  capabilities = ["update"]
}

# --- Auth method inventory (read-only; enabling/disabling requires sudo — not granted) ---
path "sys/auth" {
  capabilities = ["read", "list"]
}

# --- Loader AppRole scope only ---
path "auth/approle/role/uhbse-canonical-loader" {
  capabilities = ["read"]
}

path "auth/approle/role/uhbse-canonical-loader/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/uhbse-canonical-loader/secret-id" {
  capabilities = ["create", "update"]
}

# --- Policy read only (no create/update/delete granted on any policy path) ---
path "sys/policies/acl/uhbse-operator-limited" {
  capabilities = ["read"]
}

path "sys/policies/acl/uhbse-canonical-loader" {
  capabilities = ["read"]
}

path "sys/policy/uhbse-operator-limited" {
  capabilities = ["read"]
}

path "sys/policy/uhbse-canonical-loader" {
  capabilities = ["read"]
}

# --- Explicit denies for high-risk operations ---
path "sys/audit" {
  capabilities = ["deny"]
}

path "sys/audit/*" {
  capabilities = ["deny"]
}

path "sys/storage/*" {
  capabilities = ["deny"]
}

path "sys/raw/*" {
  capabilities = ["deny"]
}

path "sys/rekey/*" {
  capabilities = ["deny"]
}

path "sys/rotate" {
  capabilities = ["deny"]
}

# No KV / credential material for human operator
path "uhbse/data/*" {
  capabilities = ["deny"]
}

path "uhbse/metadata/*" {
  capabilities = ["deny"]
}

path "secret/*" {
  capabilities = ["deny"]
}
