-- Stage 03 Implementation — Changeset 01: Canonical Storage Foundation
-- Migration 0003: role privileges on the pilot evidence schema.
--
-- Authority:
--   artifacts/stage-03-implementation/physical-storage-plan.yaml :: database_roles, connection_policy
--
--   canonical_owner        owns objects, no runtime use
--   canonical_migrator     DDL only
--   canonical_loader       SELECT/INSERT on evidence tables (SELECT is required for
--                          idempotency and reconciliation checks); no UPDATE, no DELETE
--   canonical_validator_ro read-only validation queries only
--
-- pipeline-plan.yaml forbids UPDATE and DELETE on published evidence, so the loader role
-- receives INSERT and SELECT only. No role receives TRUNCATE or DDL on evidence tables.

BEGIN;

SET LOCAL ROLE canonical_owner;

GRANT USAGE ON SCHEMA canonical_evidence TO canonical_loader;
GRANT USAGE ON SCHEMA canonical_evidence TO canonical_validator_ro;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA canonical_evidence FROM canonical_loader;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA canonical_evidence FROM canonical_validator_ro;

GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA canonical_evidence TO canonical_loader;
GRANT SELECT ON ALL TABLES IN SCHEMA canonical_evidence TO canonical_validator_ro;

ALTER DEFAULT PRIVILEGES FOR ROLE canonical_owner IN SCHEMA canonical_evidence
    GRANT SELECT, INSERT ON TABLES TO canonical_loader;
ALTER DEFAULT PRIVILEGES FOR ROLE canonical_owner IN SCHEMA canonical_evidence
    GRANT SELECT ON TABLES TO canonical_validator_ro;

-- Enum types are used in column definitions; usage is required to insert typed values.
GRANT USAGE ON TYPE canonical_evidence.canonical_data_level TO canonical_loader;
GRANT USAGE ON TYPE canonical_evidence.canonical_mapping_status TO canonical_loader;
GRANT USAGE ON TYPE canonical_evidence.canonical_data_level TO canonical_validator_ro;
GRANT USAGE ON TYPE canonical_evidence.canonical_mapping_status TO canonical_validator_ro;

COMMIT;
