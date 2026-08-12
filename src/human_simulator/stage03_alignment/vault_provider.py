"""Vault provisioning identity and path constants (Alignment v0.2)."""

from __future__ import annotations

# Confirmed provider decision — no secret values.
PROVIDER = "hashicorp_vault"
VAULT_MODE = "production"
DEV_MODE_PROHIBITED = True

KV_MOUNT = "uhbse"
LOGICAL_HMAC_PATH = "canonical/hmac-subject-key"
LOGICAL_LOADER_PATH = "canonical/loader-credential"

CONTRACT_HMAC_REFERENCE = "vault://uhbse/canonical/hmac-subject-key?version=1"
CONTRACT_LOADER_REFERENCE = "vault://uhbse/canonical/loader-credential?version=1"

VAULT_APPROLE = "uhbse-canonical-loader"
POSTGRES_LOGIN_PRINCIPAL = "canonical_loader_login"
POSTGRES_NOLOGIN_GROUP = "canonical_loader"

POLICY_NAME = "uhbse-canonical-loader"
