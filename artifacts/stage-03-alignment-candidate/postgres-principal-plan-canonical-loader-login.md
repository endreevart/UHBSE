# Plan — PostgreSQL LOGIN principal `canonical_loader_login`

**Status:** PROVISIONED (noop) — Report status: DRAFT  
**Alignment:** postgres-principal v0.1  
**Overall:** PASS

## Identity separation

| Layer | Name | Status |
|------|------|--------|
| Vault AppRole | `uhbse-canonical-loader` | provisioned |
| PostgreSQL LOGIN | `canonical_loader_login` | provisioned (noop) |
| PostgreSQL NOLOGIN group | `canonical_loader` | retained NOLOGIN |

## Attributes

LOGIN, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS  
Membership: `GRANT canonical_loader TO canonical_loader_login`

## Explicit non-closure

`canonical_loader_runtime_contract` remains **incomplete**.  
Open operational-security findings continue to **block live load**.

## Forbidden next steps (not started)

Changeset 02, migration 0005, ETL, extraction, clinical reads, canonical data load,
Design/Plan FINAL promotion.
