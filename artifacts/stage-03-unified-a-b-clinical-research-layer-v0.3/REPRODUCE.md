# Reproduce v0.3

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_research_layer_v03*.py -q
uv run --frozen audit --root . unified-research-layer run-v0.3 --no-publish
uv run --frozen audit --root . unified-research-layer publish-v0.3
```
