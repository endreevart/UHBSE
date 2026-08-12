# Verify Implementation Plan

Use when validating Stage 03 implementation planning gate.

## Versions

- Design baseline: v0.7.5
- Implementation planning: v0.3.6

## Command

```bash
audit --root . stage-03-implementation-plan-check
```

## Side-effect-free check

```python
from pathlib import Path
from human_simulator.stage03.verify_implementation_plan import verify_implementation_plan

verify_implementation_plan(Path("."), run_pytest=False, publish_artifacts=False)
```

## Expectations

- Design manifest matches `design-baseline-manifest.sha256`
- Active docs, rules, skills, and commands reference v0.7.5 / v0.3.6
- Pilot read-set fully covered by snapshot fingerprint contract
- Review bundle ZIP matches REVIEW_INDEX.md exactly; no nested archives
- Gate return payload matches on-disk verification JSON
- No DDL/ETL/database creation artifacts
- Pilot Source A only
- Report remains DRAFT and matches plan version semantics
