# Stage 02 Report

Generated: 2026-07-31T22:38:16.583936+00:00

**Report status:** FINAL

## Sources

### Source A (magerya_api)
- Extraction: `live_readonly_profile`
- Audit user: `mg_audit_ro`
- Schema fingerprint SHA-256: `01272eab2d7d29ee4cd5a90a81e724f02e691c8da5e27ce65afb19a91227919e`

### Source B (kgz_raw)
- Audit user: `kgz_audit_ro`
- Restore: `Restore completed; post-restore verification finished (timing backfilled)`
- Database: `kgz_raw`

## Completed substeps

1. restore-second-source (confirmed)
2. profile-second-source via kgz_audit_ro
3. compare-source-audits
4. assess-source-relationship
5. verify-stage-02

## Confirmed results

- Gate status: **PASS** (53/53 checks)
- Subject root A: **SUBJECT_ROOT_CONFIRMED**
- Subject root B: **SUBJECT_ROOT_CANDIDATE**
- Identity verdict: **POTENTIAL_OVERLAP**
- Source relationship: **SAME_DOMAIN_DIFFERENT_SYSTEMS**
- Unresolved crosswalk mappings: **17**

## Identity assessment limitations

- Population overlap: **NOT_ESTIMABLE** — Source A phone coverage is 0.7%; missingness cannot be assumed random; only 22 consistent dual-identifier subject pairs — insufficient for population extrapolation
- Identifier intersections are not treated as confirmed patient matches.
- Duplicate identifiers, cross-field conflicts, and asymmetric missingness prevent population extrapolation.
- No per-patient HMAC digests or raw identifiers are stored in artifacts.

## Explicit non-actions

- No merge of Source A and Source B databases
- No canonical database created
- No permanent patient crosswalk created
- No Stage 03 work started

## Unresolved crosswalk mappings

- `patients:magerya_api.account_patient->None`
- `patients:None->public.persons`
- `visits:magerya_api.appointment_appointment->public.consultations`
- `doctors:magerya_api.account_doctor->public.users`
- `specialties:magerya_api.account_doctor->None`
- `laboratory_results:magerya_api.document_analysisresult->quest_digital.analyses_constructor`
- `laboratory_results:magerya_api.document_analysisresultitem->None`
- `laboratory_results:None->quest_digital.lab_result`
- `medical_documents:magerya_api.document_document->None`
- `medical_documents:magerya_api.document_informationform->None`
- `medical_documents:magerya_api.document_medicalreport->None`
- `medical_documents:magerya_api.document_patientquestionnaire->None`
- `medical_documents:magerya_api.document_procedurelist->None`
- `measurements:None->public.profilaxys_analyses`
- `measurements:None->public.profilaxys_profile`
- `measurements:None->public.users_profile`
- `appointments:magerya_api.appointment_appointment->public.consultations`

## Unresolved questions (carried to Stage 03)

- Whether systems ever shared a deployment or data export path
- Exact laboratory result representation equivalence (header/value split differs)
- Source B patient root resolves via shared users table; staff/patient separation unclear

## Artifacts

- `verify-stage-02.json`
- `stage-02-final-manifest.sha256`
- `compare-verification-report.json`
- `relationship-verification-report.json`
- `entity-crosswalk.yaml`
- `subject-root-analysis.json`
- `identity-linkage-assessment.json`
- `source-relationship-assessment.json`

**PASS** — Stage 02 gate reached.
