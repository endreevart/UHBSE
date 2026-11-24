# REPRODUCE — Unified Source Expansion v0.1.2

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_source_expansion_v012_unit.py -q
uv run --frozen audit --root . unified-source-expansion-v012 verify
```

Live run:

```bash
uv run --frozen audit --root . unified-source-expansion-v012 run --full --no-publish
```
