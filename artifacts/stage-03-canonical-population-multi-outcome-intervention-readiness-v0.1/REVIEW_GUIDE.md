# Review guide

1. Read verification.json statuses separately — do not collapse into one optimistic PASS.
2. Confirm canonical_population != scientific_cohort.
3. Confirm scientifically_interpretable is never true while domain gates remain open.
4. Confirm permutation_p_value uses (k+1)/(n+1) and is never literal 0.0.
5. Confirm medicine-appointment row counts are not labeled as intervention counts.
6. Confirm no PII/secrets in artifacts.
