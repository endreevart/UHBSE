# Recommended next stage (audit v0.1)

**RECOMMENDED_NEXT_STAGE:** Scenario A — Single-outcome trajectory expansion

## Why (evidence)

Source A shows many outcome×unit grains with ≥1000 strict consecutive pairs; medication primary grains remain 29–50. Next model stage supported by data is single-outcome trajectory expansion, not multi-outcome natural history yet (thresholds for B not accepted) and not another medication association train.

## What this is not

- Not Multi-Outcome Natural History Baseline (Scenario B) — thresholds not accepted
- Not medication intervention-response / treatment-effect
- Not scientific READY medication cohorts (primary grains 29–50; HUMAN_ACCEPTED=0)

## Episode accounting headline

- udca_oral_tablet_500mg: 1617 → 50 primary (67 unique medication events; ~24.1343 outcomes/event)
- levothyroxine_oral_tablet_50mcg: 1692 → 45 primary (58 unique medication events; ~29.1724 outcomes/event)
- udca_oral_tablet_250mg: 1005 → 29 primary (37 unique medication events; ~27.1622 outcomes/event)

## Negative controls

Status: `PASS`. Do not treat low p as M2>M1 signal.

## Thresholds

`THRESHOLD_DECISION_REQUIRED` — options in `threshold-options.json`; not written to policy.

## Non-actions

- No model training in this audit
- No ZIP publication
- No HUMAN_ACCEPTED
- Security remains PAUSED_NOT_ACCEPTED_BY_OWNER

