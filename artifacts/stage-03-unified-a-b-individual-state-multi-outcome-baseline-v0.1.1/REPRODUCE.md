# Reproduce v0.1.1

```bash
uv run --frozen audit --root . unified-individual-state run-v0.1.1 --no-publish
uv run --frozen audit --root . unified-individual-state verify-v0.1.1
uv run --frozen audit --root . unified-individual-state publish-v0.1.1
```

Private row-level data stays under `private/unified-individual-state-v011/`.
Do not overwrite v0.1 ZIP.
