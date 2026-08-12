-- Stage 03 Implementation — Changeset 01 v0.2: Storage Verification Hardening
-- Migration 0004: provenance hardening for the pilot evidence tables.
--
-- Migrations 0001-0003 are immutable and are not touched. Every rule below is added as a
-- new, separately named CHECK constraint so the reviewed definitions of 0002 stay intact.
--
-- Authority:
--   artifacts/stage-03/provenance-contract.yaml :: profiles.SOURCE_BACKED.required_fields
--   artifacts/stage-03/provenance-contract.yaml :: profiles.COMPUTED.required_fields
--                                                  and forbidden_fields
--   artifacts/stage-03/provenance-contract.yaml :: origin_specific_rules.CORRECTED
--                                                  / NORMALIZED / ANNOTATED
--   artifacts/stage-03/provenance-contract.yaml :: purpose ("discriminated provenance
--                                                  profiles by record_origin")
--   artifacts/stage-03/canonical-model.yaml     :: layers.evidence.forbidden_origins
--   artifacts/stage-03/record-construction-contract.yaml :: x-source-backed-provenance,
--                                                  construction_groups constant_fields
--
-- Why jsonb_strip_nulls: the accepted contract lists required fields. A key whose JSON value
-- is null carries no value, so `provenance ? 'k'` alone is not sufficient. Stripping JSON
-- nulls first makes "present" and "carries a value" the same test, in one operator.
--
-- No new field, type or record_origin is introduced. This migration is DDL only and moves
-- no row. The canonical database is empty before and after it.

BEGIN;

SET LOCAL ROLE canonical_owner;

-- ---------------------------------------------------------------------------
-- 1. Required provenance fields must be present AND non-null, per profile.
--    The same expression is applied to every provenance-bearing pilot table so that
--    pg_get_constraintdef returns an identical definition for all six.
-- ---------------------------------------------------------------------------
DO $hardening$
DECLARE
    target_table text;
    required_values_present constant text := $expr$
        CASE
            WHEN provenance->>'record_origin'
                 IN ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
            THEN jsonb_strip_nulls(provenance) ?& ARRAY[
                     'record_origin','source_system','source_schema','source_relation',
                     'source_record_locator','transformation_id','transformation_version',
                     'transformed_at','input_artifact_sha256','confidence','mapping_status'
                 ]::text[]
            WHEN provenance->>'record_origin' IN ('DERIVED','IMPUTED')
            THEN jsonb_strip_nulls(provenance) ?& ARRAY[
                     'record_origin','input_record_references','computation_method',
                     'computation_version','uncertainty','transformation_id',
                     'transformation_version','transformed_at','input_artifact_sha256',
                     'confidence','mapping_status'
                 ]::text[]
            ELSE false
        END
    $expr$;
    origin_specific_fields constant text := $expr$
        (provenance->>'record_origin' IS DISTINCT FROM 'CORRECTED'
         OR jsonb_strip_nulls(provenance) ?& ARRAY[
                'prior_record_reference','correction_reason'
            ]::text[])
        AND (provenance->>'record_origin' IS DISTINCT FROM 'NORMALIZED'
         OR jsonb_strip_nulls(provenance) ? 'normalization_lineage')
        AND (provenance->>'record_origin' IS DISTINCT FROM 'ANNOTATED'
         OR jsonb_strip_nulls(provenance) ?& ARRAY[
                'annotation_text','annotated_at'
            ]::text[])
    $expr$;
    -- SOURCE_BACKED and COMPUTED are discriminated by record_origin, so a row may satisfy
    -- exactly one of them. 0002 already forbids source_record_locator on COMPUTED origins;
    -- this adds the mirror direction and pins the evidence-layer origin allow-list.
    profiles_mutually_exclusive constant text := $expr$
        provenance->>'record_origin' IN
            ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED','DERIVED','IMPUTED')
        AND (
            provenance->>'record_origin' NOT IN ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
            OR NOT provenance ?| ARRAY[
                   'input_record_references','computation_method','computation_version'
               ]::text[]
        )
        AND (
            provenance->>'record_origin' NOT IN ('DERIVED','IMPUTED')
            OR NOT provenance ?| ARRAY[
                   'source_system','source_schema','source_relation','source_record_locator'
               ]::text[]
        )
    $expr$;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        'source_record',
        'subject',
        'subject_characteristic',
        'encounter',
        'observation',
        'observation_component'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE canonical_evidence.%I DROP CONSTRAINT IF EXISTS %I',
            target_table, target_table || '_provenance_required_values_present'
        );
        EXECUTE format(
            'ALTER TABLE canonical_evidence.%I ADD CONSTRAINT %I CHECK (%s)',
            target_table, target_table || '_provenance_required_values_present',
            required_values_present
        );

        EXECUTE format(
            'ALTER TABLE canonical_evidence.%I DROP CONSTRAINT IF EXISTS %I',
            target_table, target_table || '_provenance_origin_specific_fields'
        );
        EXECUTE format(
            'ALTER TABLE canonical_evidence.%I ADD CONSTRAINT %I CHECK (%s)',
            target_table, target_table || '_provenance_origin_specific_fields',
            origin_specific_fields
        );

        EXECUTE format(
            'ALTER TABLE canonical_evidence.%I DROP CONSTRAINT IF EXISTS %I',
            target_table, target_table || '_provenance_profiles_exclusive'
        );
        EXECUTE format(
            'ALTER TABLE canonical_evidence.%I ADD CONSTRAINT %I CHECK (%s)',
            target_table, target_table || '_provenance_profiles_exclusive',
            profiles_mutually_exclusive
        );
    END LOOP;
END
$hardening$;

-- ---------------------------------------------------------------------------
-- 2. SubjectCharacteristic.status must agree with provenance.mapping_status.
--    canonical-model.yaml gives the column the mapping-status domain; the provenance
--    contract gives the same domain to provenance.mapping_status. Two disagreeing values
--    for one fact are not representable.
-- ---------------------------------------------------------------------------
ALTER TABLE canonical_evidence.subject_characteristic
    DROP CONSTRAINT IF EXISTS subject_characteristic_status_matches_provenance;
ALTER TABLE canonical_evidence.subject_characteristic
    ADD CONSTRAINT subject_characteristic_status_matches_provenance CHECK (
        status::text = provenance->>'mapping_status'
    );

-- ---------------------------------------------------------------------------
-- 3. SourceRecord locator columns must not contradict the provenance block.
--    record-construction-contract.yaml pins source_schema and source_relation as constant
--    fields on the row while provenance.source_relation is populated from the group's
--    fully qualified relation, so the qualified form is accepted as equivalent. Nothing is
--    normalised or rewritten: the row is simply rejected when the two disagree.
-- ---------------------------------------------------------------------------
ALTER TABLE canonical_evidence.source_record
    DROP CONSTRAINT IF EXISTS source_record_provenance_matches_columns;
ALTER TABLE canonical_evidence.source_record
    ADD CONSTRAINT source_record_provenance_matches_columns CHECK (
        provenance->>'record_origin' NOT IN
            ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
        OR (
            provenance->>'source_system' = source_system_id
            AND provenance->>'source_schema' = source_schema
            AND provenance->>'source_relation' IN (
                source_relation,
                source_schema || '.' || source_relation
            )
            AND provenance->>'source_record_locator' = source_record_locator
        )
    );

COMMIT;
