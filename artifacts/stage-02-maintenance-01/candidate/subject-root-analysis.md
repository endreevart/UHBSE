# Subject root analysis

Assessed at: 2026-08-01T16:52:04.302478+00:00

## Source A

- Hypothesis: `magerya_api.account_patient`
- Verdict: **SUBJECT_ROOT_CONFIRMED**
- Reason: dedicated patient table with PK and multiple incoming foreign keys
- Rows: 43,856
- Distinct IDs: 43,856
- Incoming FK count: 37

## Source B

- Persons hypothesis: `public.persons` → **NO_SUBJECT_ROOT**
- Consultations anchor rows: 88,867
- Distinct patient_id values: 49,564
- Overall verdict: **SUBJECT_ROOT_CANDIDATE**
- Reason: 100% consultations.patient_id coverage in public.users.id, but only CANDIDATE because public.users is multi-role and there is no explicit patient-only FK/root

### patient_id candidate coverage

| Target | Match rate | Orphan count |
|--------|------------|--------------|
| public.users.id | 1.0000 | 0 |
| public.persons.id | 0.0000 | 88,867 |
| public.profilaxys_profile.id | 0.1653 | 74,180 |
| public.profilaxys_profile.user_id | 0.1511 | 75,440 |
| public.users_profile.user_id | 1.0000 | 0 |
| public.profilaxys_users.id | 0.1511 | 75,440 |

## Notes

- Aggregates only; no patient IDs or PII emitted.
- CONFIRMED requires explicit FK or coverage >= threshold.
