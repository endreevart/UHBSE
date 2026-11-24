# REPRODUCE — Unified Source Expansion v0.1.2.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_source_expansion_v0121_unit.py -q
uv run --frozen audit --root . unified-source-expansion-v0121 run --full --no-publish
uv run --frozen audit --root . unified-source-expansion-v0121 verify
```

Do not overwrite prior Unified / Core / SDR / Roadmap review ZIPs.
