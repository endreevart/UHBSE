# Reproduce — Source A Single-Outcome Trajectory Expansion v0.1

```bash
uv run --frozen audit --root . trajectory-expansion run-v0.1 --no-publish
uv run --frozen audit --root . trajectory-expansion verify-v0.1
uv run --frozen pytest tests/test_trajectory_expansion_v01.py -q
```

Conservative profile is stage-local. No medication / multi-outcome / intervention-response.
