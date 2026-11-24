# Reproduce — Source A Single-Outcome Trajectory Expansion v0.1.1

Self-contained artifact / model / engine verification (no clinical DB):

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_trajectory_expansion_v011*.py -q
uv run --frozen audit --root . trajectory-expansion verify-v0.1.1
```

Private full-data rebuild (requires configured Source A read-only DB + HMAC):

```bash
uv run --frozen audit --root . trajectory-expansion run-v0.1.1 --no-publish
```

Do not claim clinical rebuild without configured private sources.
v0.1 ZIP must remain unchanged (`stage-03-source-a-single-outcome-trajectory-expansion-v0.1-review.zip`).
