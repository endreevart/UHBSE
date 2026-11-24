# Reproduce — Privacy + Cross-Source Harmonization v0.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_privacy_cross_source_v01*.py -q
uv run --frozen audit --root . privacy-cross-source verify-v0.1
```

Private rebuild needs Source A/B + canonical DB + HMAC runtime secrets (never in ZIP).
