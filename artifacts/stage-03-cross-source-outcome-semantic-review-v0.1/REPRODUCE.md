# Reproduce — Cross-Source Outcome Semantic Review v0.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_cross_source_semantic_review_v01*.py -q
uv run --frozen audit --root . cross-source-semantic-review verify-v0.1
```

Private domain-review pack: `private/cross-source-outcome-review-v01/`
Decision log is append-only. No classifier / zero-shot in this stage.
