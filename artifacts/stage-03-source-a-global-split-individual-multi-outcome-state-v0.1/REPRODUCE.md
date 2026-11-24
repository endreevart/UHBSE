# Reproduce — Global Split Individual Multi-Outcome State v0.1

Self-contained verification (no clinical DB):

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_global_state_v01*.py -q
uv run --frozen audit --root . global-state verify-v0.1
```

Private full rebuild requires configured Source A DB + HMAC:

```bash
uv run --frozen audit --root . global-state run-v0.1 --no-publish
```

Do not overwrite trajectory expansion v0.1 / v0.1.1 ZIPs.
