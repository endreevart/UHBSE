# Reproduce — Semantic Review corrective v0.1.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_cross_source_semantic_review_v011*.py -q
uv run --frozen audit --root . cross-source-semantic-review run-v0.1.1 --no-publish
uv run --frozen audit --root . cross-source-semantic-review verify-v0.1.1
uv run --frozen audit --root . cross-source-semantic-review publish-v0.1.1
```
