-- Stage 03 Implementation — Changeset 01: Canonical Storage Foundation
-- Migration 0002: pilot evidence tables for Source A.
--
-- Authority:
--   artifacts/stage-03/canonical-model.yaml            :: entities, relationships, constraints
--   artifacts/stage-03/provenance-contract.yaml        :: profiles, mapping_status_values
--   artifacts/stage-03/temporal-contract.yaml          :: entity_time_roles, missing_time_policy
--   artifacts/stage-03-implementation/pilot-slice.yaml :: pilot_entities, forbidden_in_pilot
--   artifacts/stage-03-implementation/pipeline-plan.yaml :: table_load_order, fk_dependencies
--   artifacts/stage-03/record-construction-contract.yaml :: constant_fields pinning pilot nulls
--
-- Scope is exactly the seven pilot table entities. Provenance is embedded jsonb; a separate
-- provenance table is forbidden by physical-storage-plan.yaml :: provenance_storage.
-- Columns referencing entities outside the pilot (Provider, Concept, Unit) and the deferred
-- Observation.encounter_id exist per the canonical model but are constrained to NULL, because
-- the accepted construction contract pins them to null and their target tables are out of
-- pilot scope. This is fail-closed: a future load cannot populate them silently.

BEGIN;

SET LOCAL ROLE canonical_owner;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'canonical_data_level' AND n.nspname = 'canonical_evidence'
    ) THEN
        CREATE TYPE canonical_evidence.canonical_data_level AS ENUM (
            'PATIENT_EVENT',
            'OBSERVATION_HEADER',
            'OBSERVATION_VALUE',
            'ATTRIBUTE_CONTAINER',
            'REFERENCE_CATALOG',
            'WORKFLOW',
            'PAYLOAD',
            'UNKNOWN'
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'canonical_mapping_status' AND n.nspname = 'canonical_evidence'
    ) THEN
        CREATE TYPE canonical_evidence.canonical_mapping_status AS ENUM (
            'CONFIRMED_SCHEMA',
            'CANDIDATE',
            'HYPOTHESIS',
            'UNRESOLVED',
            'NOT_MAPPED'
        );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 1. SourceSystem — bootstrap entity, no row provenance
--    provenance-contract.yaml :: entity_exceptions.SourceSystem
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_evidence.source_system (
    source_system_id      text NOT NULL,
    source_label          text NOT NULL,
    audit_stage_reference text NULL,
    CONSTRAINT source_system_pkey PRIMARY KEY (source_system_id),
    CONSTRAINT source_system_id_not_blank CHECK (btrim(source_system_id) <> ''),
    CONSTRAINT source_system_label_not_blank CHECK (btrim(source_label) <> '')
);

-- ---------------------------------------------------------------------------
-- 2. SourceRecord — one per participating source row, HMAC locator
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_evidence.source_record (
    source_record_id      text NOT NULL,
    source_system_id      text NOT NULL,
    source_schema         text NOT NULL,
    source_relation       text NOT NULL,
    source_record_locator text NOT NULL,
    locator_scheme        text NOT NULL,
    locator_key_version   text NOT NULL,
    source_created_at     timestamptz NULL,
    source_updated_at     timestamptz NULL,
    provenance            jsonb NOT NULL,
    CONSTRAINT source_record_pkey PRIMARY KEY (source_record_id),
    CONSTRAINT source_record_source_system_fkey FOREIGN KEY (source_system_id)
        REFERENCES canonical_evidence.source_system (source_system_id),
    CONSTRAINT source_record_locator_unique UNIQUE (source_record_locator),
    CONSTRAINT source_record_locator_scheme_allowed
        CHECK (locator_scheme = 'deterministic_hmac_locator'),
    CONSTRAINT source_record_locator_not_blank CHECK (btrim(source_record_locator) <> ''),
    CONSTRAINT source_record_key_version_not_blank CHECK (btrim(locator_key_version) <> ''),
    CONSTRAINT source_record_provenance_profile_valid CHECK (
        jsonb_typeof(provenance) = 'object'
        AND provenance ? 'record_origin'
        AND provenance->>'record_origin' IN
            ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED','DERIVED','IMPUTED')
        AND provenance->>'mapping_status' IN
            ('CONFIRMED_SCHEMA','CANDIDATE','HYPOTHESIS','UNRESOLVED','NOT_MAPPED')
        AND (
            provenance->>'record_origin' NOT IN ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
            OR provenance ?& ARRAY[
                'record_origin','source_system','source_schema','source_relation',
                'source_record_locator','transformation_id','transformation_version',
                'transformed_at','input_artifact_sha256','confidence','mapping_status'
            ]::text[]
        )
        AND (
            provenance->>'record_origin' NOT IN ('DERIVED','IMPUTED')
            OR (
                provenance ?& ARRAY[
                    'record_origin','input_record_references','computation_method',
                    'computation_version','uncertainty','transformation_id',
                    'transformation_version','transformed_at','input_artifact_sha256',
                    'confidence','mapping_status'
                ]::text[]
                AND NOT provenance ? 'source_record_locator'
            )
        )
    )
);

CREATE INDEX IF NOT EXISTS source_record_source_relation_idx
    ON canonical_evidence.source_record (source_system_id, source_schema, source_relation);

-- ---------------------------------------------------------------------------
-- 3. Subject — source-local identity only, no global subject identifier
--    canonical-model.yaml :: Subject.identity
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_evidence.subject (
    subject_id         text NOT NULL,
    source_system_id   text NOT NULL,
    source_subject_key text NOT NULL,
    subject_role_hint  text NULL,
    provenance         jsonb NOT NULL,
    CONSTRAINT subject_pkey PRIMARY KEY (subject_id),
    CONSTRAINT subject_source_system_fkey FOREIGN KEY (source_system_id)
        REFERENCES canonical_evidence.source_system (source_system_id),
    CONSTRAINT subject_source_local_identity_unique UNIQUE (source_system_id, source_subject_key),
    CONSTRAINT subject_source_subject_key_not_blank CHECK (btrim(source_subject_key) <> ''),
    CONSTRAINT subject_provenance_profile_valid CHECK (
        jsonb_typeof(provenance) = 'object'
        AND provenance ? 'record_origin'
        AND provenance->>'record_origin' IN
            ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED','DERIVED','IMPUTED')
        AND provenance->>'mapping_status' IN
            ('CONFIRMED_SCHEMA','CANDIDATE','HYPOTHESIS','UNRESOLVED','NOT_MAPPED')
        AND (
            provenance->>'record_origin' NOT IN ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
            OR provenance ?& ARRAY[
                'record_origin','source_system','source_schema','source_relation',
                'source_record_locator','transformation_id','transformation_version',
                'transformed_at','input_artifact_sha256','confidence','mapping_status'
            ]::text[]
        )
        AND (
            provenance->>'record_origin' NOT IN ('DERIVED','IMPUTED')
            OR (
                provenance ?& ARRAY[
                    'record_origin','input_record_references','computation_method',
                    'computation_version','uncertainty','transformation_id',
                    'transformation_version','transformed_at','input_artifact_sha256',
                    'confidence','mapping_status'
                ]::text[]
                AND NOT provenance ? 'source_record_locator'
            )
        )
    )
);

-- ---------------------------------------------------------------------------
-- 4. SubjectCharacteristic — stable demographics with raw values preserved
--    canonical-model.yaml :: constraints.subject_characteristic_*
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_evidence.subject_characteristic (
    characteristic_id   text NOT NULL,
    subject_id          text NOT NULL,
    characteristic_code text NULL,
    concept_id          text NULL,
    raw_code            text NOT NULL,
    raw_value           text NOT NULL,
    date_value          date NULL,
    numeric_value       numeric NULL,
    text_value          text NULL,
    categorical_value   text NULL,
    boolean_value       boolean NULL,
    raw_unit            text NULL,
    normalized_unit     text NULL,
    effective_at        timestamptz NULL,
    recorded_at         timestamptz NULL,
    status              canonical_evidence.canonical_mapping_status NOT NULL,
    provenance          jsonb NOT NULL,
    CONSTRAINT subject_characteristic_pkey PRIMARY KEY (characteristic_id),
    CONSTRAINT subject_characteristic_subject_fkey FOREIGN KEY (subject_id)
        REFERENCES canonical_evidence.subject (subject_id),
    -- at least one of characteristic_code or concept_id; XOR-only identity is forbidden
    CONSTRAINT subject_characteristic_identity_present CHECK (
        characteristic_code IS NOT NULL OR concept_id IS NOT NULL
    ),
    -- exactly one typed value representation
    CONSTRAINT subject_characteristic_typed_value_xor CHECK (
        (CASE WHEN date_value        IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN numeric_value     IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN text_value        IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN categorical_value IS NOT NULL THEN 1 ELSE 0 END)
      + (CASE WHEN boolean_value     IS NOT NULL THEN 1 ELSE 0 END)
      = 1
    ),
    CONSTRAINT subject_characteristic_raw_value_preserved CHECK (btrim(raw_value) <> ''),
    CONSTRAINT subject_characteristic_raw_code_not_blank CHECK (btrim(raw_code) <> ''),
    -- Concept and Unit are outside pilot scope; construction contract pins both to null
    CONSTRAINT subject_characteristic_concept_null_in_pilot CHECK (concept_id IS NULL),
    CONSTRAINT subject_characteristic_normalized_unit_null_in_pilot CHECK (normalized_unit IS NULL),
    CONSTRAINT subject_characteristic_provenance_profile_valid CHECK (
        jsonb_typeof(provenance) = 'object'
        AND provenance ? 'record_origin'
        AND provenance->>'record_origin' IN
            ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED','DERIVED','IMPUTED')
        AND provenance->>'mapping_status' IN
            ('CONFIRMED_SCHEMA','CANDIDATE','HYPOTHESIS','UNRESOLVED','NOT_MAPPED')
        AND (
            provenance->>'record_origin' NOT IN ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
            OR provenance ?& ARRAY[
                'record_origin','source_system','source_schema','source_relation',
                'source_record_locator','transformation_id','transformation_version',
                'transformed_at','input_artifact_sha256','confidence','mapping_status'
            ]::text[]
        )
        AND (
            provenance->>'record_origin' NOT IN ('DERIVED','IMPUTED')
            OR (
                provenance ?& ARRAY[
                    'record_origin','input_record_references','computation_method',
                    'computation_version','uncertainty','transformation_id',
                    'transformation_version','transformed_at','input_artifact_sha256',
                    'confidence','mapping_status'
                ]::text[]
                AND NOT provenance ? 'source_record_locator'
            )
        )
    )
);

CREATE INDEX IF NOT EXISTS subject_characteristic_subject_idx
    ON canonical_evidence.subject_characteristic (subject_id);

-- ---------------------------------------------------------------------------
-- 5. Encounter — clinical time may be absent; absence must be documented
--    temporal-contract.yaml :: entity_time_roles.Encounter, missing_time_policy
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_evidence.encounter (
    encounter_id       text NOT NULL,
    subject_id         text NOT NULL,
    provider_id        text NULL,
    encounter_type     text NULL,
    occurred_at        timestamptz NULL,
    recorded_at        timestamptz NULL,
    completed_at       timestamptz NULL,
    cancelled_at       timestamptz NULL,
    confirmed_at       timestamptz NULL,
    status             text NULL,
    data_level         canonical_evidence.canonical_data_level NOT NULL,
    missingness_reason text NULL,
    provenance         jsonb NOT NULL,
    CONSTRAINT encounter_pkey PRIMARY KEY (encounter_id),
    CONSTRAINT encounter_subject_fkey FOREIGN KEY (subject_id)
        REFERENCES canonical_evidence.subject (subject_id),
    -- Provider is outside pilot scope: pilot-slice.yaml deferred_fields, doctor_id not copied
    CONSTRAINT encounter_provider_null_in_pilot CHECK (provider_id IS NULL),
    -- missing clinical time must carry a documented reason, never a substituted timestamp
    CONSTRAINT encounter_missing_clinical_time_documented CHECK (
        occurred_at IS NOT NULL OR missingness_reason IS NOT NULL
    ),
    CONSTRAINT encounter_provenance_profile_valid CHECK (
        jsonb_typeof(provenance) = 'object'
        AND provenance ? 'record_origin'
        AND provenance->>'record_origin' IN
            ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED','DERIVED','IMPUTED')
        AND provenance->>'mapping_status' IN
            ('CONFIRMED_SCHEMA','CANDIDATE','HYPOTHESIS','UNRESOLVED','NOT_MAPPED')
        AND (
            provenance->>'record_origin' NOT IN ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
            OR provenance ?& ARRAY[
                'record_origin','source_system','source_schema','source_relation',
                'source_record_locator','transformation_id','transformation_version',
                'transformed_at','input_artifact_sha256','confidence','mapping_status'
            ]::text[]
        )
        AND (
            provenance->>'record_origin' NOT IN ('DERIVED','IMPUTED')
            OR (
                provenance ?& ARRAY[
                    'record_origin','input_record_references','computation_method',
                    'computation_version','uncertainty','transformation_id',
                    'transformation_version','transformed_at','input_artifact_sha256',
                    'confidence','mapping_status'
                ]::text[]
                AND NOT provenance ? 'source_record_locator'
            )
        )
    )
);

CREATE INDEX IF NOT EXISTS encounter_subject_idx
    ON canonical_evidence.encounter (subject_id);

-- ---------------------------------------------------------------------------
-- 6. Observation — header level; encounter link deferred for pilot
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_evidence.observation (
    observation_id        text NOT NULL,
    subject_id            text NOT NULL,
    encounter_id          text NULL,
    observed_at           timestamptz NULL,
    specimen_collected_at timestamptz NULL,
    result_available_at   timestamptz NULL,
    recorded_at           timestamptz NULL,
    status                text NULL,
    data_level            canonical_evidence.canonical_data_level NOT NULL,
    raw_code              text NULL,
    normalized_concept    text NULL,
    raw_value             text NULL,
    raw_unit              text NULL,
    normalized_unit       text NULL,
    reference_range       jsonb NULL,
    abnormal_flag         text NULL,
    uncertainty           jsonb NULL,
    missingness_reason    text NULL,
    provenance            jsonb NOT NULL,
    CONSTRAINT observation_pkey PRIMARY KEY (observation_id),
    CONSTRAINT observation_subject_fkey FOREIGN KEY (subject_id)
        REFERENCES canonical_evidence.subject (subject_id),
    -- pipeline-plan.yaml :: fk_dependencies Observation.encounter_id deferred_null_for_pilot
    CONSTRAINT observation_encounter_null_in_pilot CHECK (encounter_id IS NULL),
    CONSTRAINT observation_normalized_concept_null_in_pilot CHECK (normalized_concept IS NULL),
    CONSTRAINT observation_normalized_unit_null_in_pilot CHECK (normalized_unit IS NULL),
    CONSTRAINT observation_missing_clinical_time_documented CHECK (
        observed_at IS NOT NULL OR missingness_reason IS NOT NULL
    ),
    CONSTRAINT observation_reference_range_is_object CHECK (
        reference_range IS NULL OR jsonb_typeof(reference_range) = 'object'
    ),
    CONSTRAINT observation_uncertainty_is_object CHECK (
        uncertainty IS NULL OR jsonb_typeof(uncertainty) = 'object'
    ),
    CONSTRAINT observation_provenance_profile_valid CHECK (
        jsonb_typeof(provenance) = 'object'
        AND provenance ? 'record_origin'
        AND provenance->>'record_origin' IN
            ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED','DERIVED','IMPUTED')
        AND provenance->>'mapping_status' IN
            ('CONFIRMED_SCHEMA','CANDIDATE','HYPOTHESIS','UNRESOLVED','NOT_MAPPED')
        AND (
            provenance->>'record_origin' NOT IN ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
            OR provenance ?& ARRAY[
                'record_origin','source_system','source_schema','source_relation',
                'source_record_locator','transformation_id','transformation_version',
                'transformed_at','input_artifact_sha256','confidence','mapping_status'
            ]::text[]
        )
        AND (
            provenance->>'record_origin' NOT IN ('DERIVED','IMPUTED')
            OR (
                provenance ?& ARRAY[
                    'record_origin','input_record_references','computation_method',
                    'computation_version','uncertainty','transformation_id',
                    'transformation_version','transformed_at','input_artifact_sha256',
                    'confidence','mapping_status'
                ]::text[]
                AND NOT provenance ? 'source_record_locator'
            )
        )
    )
);

CREATE INDEX IF NOT EXISTS observation_subject_idx
    ON canonical_evidence.observation (subject_id);

-- ---------------------------------------------------------------------------
-- 7. ObservationComponent — analyte level rows under an Observation header
--    The accepted model defines no typed-value XOR for this entity; none is invented.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_evidence.observation_component (
    component_id      text NOT NULL,
    observation_id    text NOT NULL,
    raw_code          text NULL,
    raw_value         text NULL,
    numeric_value     numeric NULL,
    text_value        text NULL,
    categorical_value text NULL,
    boolean_value     boolean NULL,
    raw_unit          text NULL,
    normalized_unit   text NULL,
    reference_range   jsonb NULL,
    abnormal_flag     text NULL,
    sequence_order    integer NULL,
    provenance        jsonb NOT NULL,
    CONSTRAINT observation_component_pkey PRIMARY KEY (component_id),
    CONSTRAINT observation_component_observation_fkey FOREIGN KEY (observation_id)
        REFERENCES canonical_evidence.observation (observation_id),
    CONSTRAINT observation_component_normalized_unit_null_in_pilot CHECK (normalized_unit IS NULL),
    CONSTRAINT observation_component_reference_range_is_object CHECK (
        reference_range IS NULL OR jsonb_typeof(reference_range) = 'object'
    ),
    CONSTRAINT observation_component_sequence_order_non_negative CHECK (
        sequence_order IS NULL OR sequence_order >= 0
    ),
    CONSTRAINT observation_component_provenance_profile_valid CHECK (
        jsonb_typeof(provenance) = 'object'
        AND provenance ? 'record_origin'
        AND provenance->>'record_origin' IN
            ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED','DERIVED','IMPUTED')
        AND provenance->>'mapping_status' IN
            ('CONFIRMED_SCHEMA','CANDIDATE','HYPOTHESIS','UNRESOLVED','NOT_MAPPED')
        AND (
            provenance->>'record_origin' NOT IN ('OBSERVED','CORRECTED','NORMALIZED','ANNOTATED')
            OR provenance ?& ARRAY[
                'record_origin','source_system','source_schema','source_relation',
                'source_record_locator','transformation_id','transformation_version',
                'transformed_at','input_artifact_sha256','confidence','mapping_status'
            ]::text[]
        )
        AND (
            provenance->>'record_origin' NOT IN ('DERIVED','IMPUTED')
            OR (
                provenance ?& ARRAY[
                    'record_origin','input_record_references','computation_method',
                    'computation_version','uncertainty','transformation_id',
                    'transformation_version','transformed_at','input_artifact_sha256',
                    'confidence','mapping_status'
                ]::text[]
                AND NOT provenance ? 'source_record_locator'
            )
        )
    )
);

CREATE INDEX IF NOT EXISTS observation_component_observation_idx
    ON canonical_evidence.observation_component (observation_id);

COMMIT;
