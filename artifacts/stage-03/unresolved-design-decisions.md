# Stage 03 — Unresolved Design Decisions (v0.4)

## Stage 02 unresolved crosswalk mappings (17)

1. `patients:magerya_api.account_patient->None`
2. `patients:None->public.persons`
3. `visits:magerya_api.appointment_appointment->public.consultations`
4. `doctors:magerya_api.account_doctor->public.users`
5. `specialties:magerya_api.account_doctor->None`
6. `laboratory_results:magerya_api.document_analysisresult->quest_digital.analyses_constructor`
7. `laboratory_results:magerya_api.document_analysisresultitem->None`
8. `laboratory_results:None->quest_digital.lab_result`
9. `medical_documents:magerya_api.document_document->None`
10. `medical_documents:magerya_api.document_informationform->None`
11. `medical_documents:magerya_api.document_medicalreport->None`
12. `medical_documents:magerya_api.document_patientquestionnaire->None`
13. `medical_documents:magerya_api.document_procedurelist->None`
14. `measurements:None->public.profilaxys_analyses`
15. `measurements:None->public.profilaxys_profile`
16. `measurements:None->public.users_profile`
17. `appointments:magerya_api.appointment_appointment->public.consultations`

## v0.3 snapshot model decisions

### EvidenceStateSnapshot vs ScenarioCheckpoint

- **EvidenceStateSnapshot** (evidence layer, DERIVED/IMPUTED): baseline from real observations via `StateSnapshotComponent` rows.
- **ScenarioCheckpoint** (simulation layer, SYNTHETIC): saved scenario state for rollback/branching; references `SimulationRun` and `PredictedState` ids.
- Legacy **StateSnapshot** removed; DERIVED forbidden in simulation_scenario layer.

### Branch baseline XOR

`ScenarioBranch` must reference exactly one of:

- `baseline_snapshot_id` (EvidenceStateSnapshot), or
- `checkpoint_id` (ScenarioCheckpoint)

Enforced at implementation time; documented in constraints.

## v0.4 virtual intervention and runtime enforcement

### ScenarioIntervention vs evidence Intervention

- Virtual medications/supplements/nutrition/activity modeled only via `ScenarioIntervention` (SYNTHETIC).
- `based_on_evidence_intervention_id` used only when modifying an observed therapy.
- Value/missingness XOR rules documented in constraints; runtime enforcement deferred to Implementation.

### SimulationRun input XOR

Exactly one of `input_evidence_snapshot_id` or `input_checkpoint_id` required at runtime.

### Checkpoint state rows

`ScenarioCheckpointState` replaces opaque `predicted_state_ids` array.

## Source A temporal gaps

- `appointment_appointment`: no clinical start/end columns; no `occurred_at` mapping.

## Source B subject/lab gaps

- `public.persons`: NOT_MAPPED, empty table, NO_SUBJECT_ROOT
- `public.users`: multi-role HYPOTHESIS
- Source B lab header synthesis: HYPOTHESIS grouping rule only

## Explicit non-actions

- No canonical database, DDL, ETL, row migration
- Stage 01/02 artifacts unchanged
- Report remains **DRAFT**
- Implementation phase not started

## v0.7 semantic closure decisions

### Source B subject eligibility (public.users)

- `public.users` is multi-role **SUBJECT_ROOT_CANDIDATE**; unconditional Subject emission forbidden.
- Conservative eligibility rule (status **HYPOTHESIS**): emit Subject only when
  `public.consultations.patient_id` references `public.users.id`.
- Forbidden: `row_filter: always`, treating `is_doctor=false` as patient proof, emitting all users.
- `users_profile` / `profilaxys_profile` SubjectCharacteristic construction requires eligible
  source-local Subject (`require_eligible_subject: true`); no cross-source merge.

### Construction groups added (v0.7)

- `source_a_appointment_encounter`, `source_a_observation_header`, `source_a_observation_component`
- `source_b_consultations_encounter`, `source_b_lab_observation_header`, `source_b_analyses_constructor_component`

### Blocked groups

- `source_b_lab_observation_header`: synthetic Observation header from analyses_constructor grouping (**implementation_blocked: true**)
- `source_b_analyses_constructor_component`: depends on blocked header synthesis

### Canonical ID contract

- `canonical-id-contract.yaml`: HMAC-SHA256, runtime-only secret, domain separation, length-prefix UTF-8 serialization, hex output, artificial test vectors only.
- `subject_key_transformation_contract` (v0.7.5): keyed PRF fields defined; `key_reference` blocked pending `DECISION_REQUIRED_SECRET_PROVIDER`.

### v0.7.5 alignment decisions

#### Temporal precision (Encounter, Observation)

- Added `temporal_precision` enum (`day`, `hour`, `minute`, `second`, `unknown`) and optional `sequence_when_time_unknown`.
- `unknown` is required when clinical time is absent; `recorded_at` must not substitute clinical time.

#### Encounter.provider_id (Source A pilot)

- `provider_id` deferred with status `DEFERRED_UNTIL_PROVIDER_CONSTRUCTION`.
- `appointment_appointment.doctor_id` is not copied; Provider construction group is out of pilot scope.

### Collision policy

- `record_group` alone is not collision resolution; requires explicit combination/precedence/grouping rule or `target_collision_rule` listing all conflicting source columns.
