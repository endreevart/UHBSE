# REPRODUCE — Unified Source Expansion v0.1.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_source_expansion_v011_unit.py -q
uv run --frozen audit --root . unified-source-expansion-v011 run --full --no-publish
uv run --frozen audit --root . unified-source-expansion-v011 verify
```
