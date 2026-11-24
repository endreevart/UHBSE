# REPRODUCE — Unified Source Expansion v0.1.2.1.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_source_expansion_v01211_unit.py -q
uv run --frozen audit --root . unified-source-expansion-v01211 run --full --no-publish
uv run --frozen audit --root . unified-source-expansion-v01211 verify
```

Do not overwrite prior Unified / Core / SDR / Roadmap review ZIPs.
Post-pack publication integrity is attested externally after `publish`.
