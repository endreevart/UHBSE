# REPRODUCE — Source A Scientific Baseline v0.2 + Shadow Transfer v0.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_scientific_baseline_v02_unit.py tests/test_cross_source_shadow_v01_unit.py -q
uv run --frozen audit --root . scientific-baseline-v02 run --full --no-publish
uv run --frozen audit --root . scientific-baseline-v02 verify
uv run --frozen audit --root . source-a-v02-shadow-transfer-v01 publish
```

Do not overwrite prior Unified / Core / SDR / Roadmap review ZIPs.
Scientific cross-source transfer remains blocked until T3 domain review.
