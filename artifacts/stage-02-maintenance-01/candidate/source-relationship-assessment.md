# Source relationship assessment

Assessed at: 2026-08-01T16:52:04.369443+00:00

## Verdict: **SAME_DOMAIN_DIFFERENT_SYSTEMS** (confidence: medium)

### Supporting evidence

- 5 shared clinical entity domains in crosswalk
- Different application schemas and data models (magerya_api vs public/quest_digital)
- Structurally similar patient, visit/event, and laboratory concepts with unresolved mappings
- 0 shared application relation names
- Aggregate identity linkage verdict=POTENTIAL_OVERLAP without population extrapolation

### Contradicting evidence

- No EVIDENCE_BACKED entity mappings in crosswalk
- Source B public.persons is empty while Source A has populated account_patient

### Unresolved questions

- Whether systems ever shared a deployment or data export path
- Exact laboratory result representation equivalence (header/value split differs)
- Source B patient root resolves via shared users table; staff/patient separation unclear

### Prohibited inferences

- Patients are not assumed equal across sources.
- No permanent patient crosswalk created.
- Schema similarity does not prove shared deployment or migration.
- Infrastructure relation-name overlap is not evidence of system relationship.
- Observed unique-identifier overlap rates must not be extrapolated to full populations.

## Clinical domain overlap

- Shared domains (5): patients, visits, doctors, laboratory_results, appointments
- Source A only: specialties, medical_documents
- Source B only: measurements

