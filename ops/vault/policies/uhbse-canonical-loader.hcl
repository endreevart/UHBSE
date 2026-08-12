# Policy: uhbse-canonical-loader
# Bound to Vault AppRole `uhbse-canonical-loader` only.
# This identity is NOT a PostgreSQL principal.
#
# Allows read of pilot secrets at fixed KV v2 paths (versioned reads).
# Denies list/write/delete and all other mounts.

# KV v2 data API
path "uhbse/data/canonical/hmac-subject-key" {
  capabilities = ["read"]
}

path "uhbse/data/canonical/loader-credential" {
  capabilities = ["read"]
}

# KV v2 metadata (version discovery without listing siblings)
path "uhbse/metadata/canonical/hmac-subject-key" {
  capabilities = ["read"]
}

path "uhbse/metadata/canonical/loader-credential" {
  capabilities = ["read"]
}
