# Reproduce v0.2.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_cross_source_lab_semantic_v021*.py tests/test_cross_source_lab_semantic_v02*.py -q
uv run --frozen audit --root . cross-source-lab-semantic run-v0.2.1 --no-publish
uv run --frozen audit --root . cross-source-lab-semantic publish-v0.2.1
```
