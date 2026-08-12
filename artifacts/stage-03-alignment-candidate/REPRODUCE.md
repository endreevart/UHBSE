# Reproduce — Stage 03 Alignment Candidate v0.1.2

## Preconditions

- Stage 01/02 FINAL; Stage 02 Maintenance 01 promotion FINAL
- Recovered baselines: `stage-03-design-v0.7.4-recovered-review.zip`, `stage-03-implementation-plan-v0.3.5-recovered-review.zip`
- Invalid baseline copies marked SUPERSEDED_INVALID_BASELINE_COPY (not overwritten)
- No raw DB connections; no clinical row reads; no ETL or live load

## Commands

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

audit stage-03-check
audit stage-03-implementation-plan-check

python -c "from pathlib import Path; from human_simulator.stage03_alignment.recovery import create_recovery_bundles; create_recovery_bundles(Path('.'))"

python -c "from pathlib import Path; from human_simulator.stage03_alignment.baseline import evaluate_baseline; import json; print(json.dumps(evaluate_baseline(Path('.')), indent=2))"

python -c "from pathlib import Path; from human_simulator.stage03_alignment.publish_alignment import publish_alignment_bundle; print(publish_alignment_bundle(Path('.')))"

pytest tests/test_stage_03_alignment_candidate.py tests/test_stage_03_conflict_resolution.py tests/test_pre_live_load_gate_hardening.py -q
```

## Expected candidate outcome

- Design **v0.7.5** (DRAFT) and Plan **v0.3.6** (DRAFT)
- Pre-live-load gate: **PARTIAL** — four contract blockers remain OPEN until secret provider is chosen
- Conflict blockers remain OPEN until Design v0.7.5 is promoted FINAL
