-- Stage 03 Implementation — Changeset 01: Canonical Storage Foundation
-- Migration 0001: canonical roles and evidence schema.
--
-- Authority:
--   artifacts/stage-03-implementation/physical-storage-plan.yaml :: database_roles, planned_topology
--   artifacts/stage-03-implementation/security-runtime-plan.yaml :: database_roles
--
-- Roles are created NOLOGIN. Login credentials are assigned at runtime from an
-- environment file outside git and are never part of any migration or artifact.
-- Forward-only: the accepted plan defines no reverse DDL for canonical evidence
-- (pipeline-plan.yaml :: rollback limits rollback to staging rows and states that
-- published records are never deleted).

BEGIN;

DO $$
DECLARE
    target_role text;
BEGIN
    FOREACH target_role IN ARRAY ARRAY[
        'canonical_owner',
        'canonical_migrator',
        'canonical_loader',
        'canonical_validator_ro'
    ]
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = target_role) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', target_role);
        END IF;
        EXECUTE format('ALTER ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', target_role);
    END LOOP;
END
$$;

-- The migrating session must be able to create objects owned by canonical_owner.
DO $$
BEGIN
    IF NOT pg_has_role(current_user, 'canonical_owner', 'MEMBER') THEN
        EXECUTE format('GRANT canonical_owner TO %I', current_user);
    END IF;
    IF NOT pg_has_role(current_user, 'canonical_migrator', 'MEMBER') THEN
        EXECUTE format('GRANT canonical_migrator TO %I', current_user);
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS canonical_evidence AUTHORIZATION canonical_owner;

-- No implicit access for anyone outside the declared roles.
REVOKE ALL ON SCHEMA canonical_evidence FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Only the migration role may add objects to the evidence schema.
GRANT USAGE ON SCHEMA canonical_evidence TO canonical_migrator;
GRANT CREATE ON SCHEMA canonical_evidence TO canonical_migrator;

COMMENT ON SCHEMA canonical_evidence IS
    'UHBSE canonical evidence layer, pilot scope Source A only. Design baseline v0.7.4, implementation plan v0.3.5.';

COMMIT;
