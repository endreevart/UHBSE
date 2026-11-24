# Decision — Observation.encounter_id deferred (no migration 0005)

**Changeset:** Unified Source Expansion v0.1.2  
**Status:** ACCEPTED_FOR_THIS_CHANGESET  
**Owner gate:** migration 0005 not authorised

## Constraint

`canonical_evidence.observation` retains pilot CHECK:

```text
observation_encounter_null_in_pilot CHECK (encounter_id IS NULL)
```

## Decision

1. Source B Observation rows load with `encounter_id = NULL`.
2. Deterministic Encounter HMAC (`consultation_id`) is stored in provenance as `encounter_id_hmac`.
3. Encounter ownership remains ACCEPTED via already-loaded `canonical_evidence.encounter` rows.
4. Do **not** create migration 0005 in this changeset.
5. Design mapping may still be `SUPPORTED_TRANSFORMATION` when ownership/grouping/value/unit gates pass; the FK column remains deferred.

## Non-action

No schema change. No raw database writes. Separate owner decision required before enabling Observation→Encounter FK.
