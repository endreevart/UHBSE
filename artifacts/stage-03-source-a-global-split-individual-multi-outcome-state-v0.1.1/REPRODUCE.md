# Reproduce — Global Split Individual Multi-Outcome State v0.1.1

Self-contained verification (no clinical DB):

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_global_state_v011*.py -q
uv run --frozen audit --root . global-state verify-v0.1.1
```

Private full rebuild requires configured Source A DB + HMAC:

```bash
uv run --frozen audit --root . global-state run-v0.1.1 --no-publish
```

Do not overwrite global-state v0.1 or trajectory-expansion v0.1.1 ZIPs.
Post-pack PASS exists only in the external attestation, not inside this ZIP.
