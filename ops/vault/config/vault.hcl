# UHBSE Vault — Stage 03 Alignment vault-stop v0.2.1
#
# Production mode. Dev mode prohibited.
# Single-node Integrated Storage (Raft) — must be set BEFORE first initialization.
#
# Secrets (init material, tokens, AppRole secret_id, HMAC, passwords) must never
# enter Git, logs, test snapshots, or review artifacts.

storage "raft" {
  path    = "/vault/data"
  node_id = "uhbse-vault-1"
}

listener "tcp" {
  # Container listens on all interfaces inside vault-net.
  # Host publish is loopback-only: 127.0.0.1:8200 (see docker-compose).
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_cert_file   = "/vault/tls/server.crt"
  tls_key_file    = "/vault/tls/server.key"
  tls_min_version = "tls12"
}

# Docker topology (this compose):
# - service DNS name: vault
# - container_name: human-simulator-vault
# - host clients / docker exec use loopback publish 127.0.0.1:8200
# api_addr must match how clients reach the listener from the process network namespace.
api_addr     = "https://127.0.0.1:8200"
cluster_addr = "https://127.0.0.1:8201"

ui = false

# Required in many container runtimes without IPC_LOCK privileges beyond cap_add.
disable_mlock = true

default_lease_ttl = "24h"
max_lease_ttl     = "72h"

log_level  = "info"
log_format = "json"
