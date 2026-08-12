# Identity linkage assessment

Assessed at: 2026-08-01T16:52:05.567497+00:00
Method: HMAC-SHA256 aggregate linkage

## Verdict: **POTENTIAL_OVERLAP**

Identifier intersections exist (67 phone, 2340 email) but uniquely resolved subject pairs are unavailable; cross-field conflicts=21, consistent dual-identifier pairs=22

## Overlap aggregates

- Matched unique phone identifiers: 67
- Matched unique email identifiers: 2,340
- Uniquely resolved subject pairs (phone): 66
- Uniquely resolved subject pairs (email): 2,208
- Consistent subject pairs (phone+email): 22
- Cross-field conflicts: 21
- Population overlap estimate: **NOT_ESTIMABLE** — Source A phone coverage is 0.7%; missingness cannot be assumed random; only 22 consistent dual-identifier subject pairs — insufficient for population extrapolation

Observed unique-identifier overlap rates use unique identifiers as denominators; they are not extrapolated to full patient populations.

- No per-patient HMAC digests or raw identifiers written to artifacts.
- Plain SHA-256 without secret key was not used.
- Identifier intersections are not subject/patient matches when duplicates or conflicts exist.
- Population overlap is not extrapolated from observed unique-identifier rates.
- LINKAGE_PROVEN is not assigned at Stage 02.
