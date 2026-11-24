# REPRODUCE — Unified Source Expansion v0.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_source_expansion_unit.py -q
uv run --frozen audit --root . unified-source-expansion verify
```

Live full expansion:

```bash
uv run --frozen audit --root . unified-source-expansion run --full --no-publish
```

Publish (refuse-if-exists):

```bash
uv run --frozen audit --root . unified-source-expansion publish
```
