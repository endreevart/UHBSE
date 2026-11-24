# Reproduce — Population / Intervention Readiness v0.1.1

```bash
uv sync --frozen --extra dev
uv run --frozen audit --root . population-multi-outcome-v011 run --full --no-publish
uv run --frozen audit --root . population-multi-outcome-v011 verify
uv run --frozen audit --root . population-multi-outcome-v011 publish
```

Security stage remains `PAUSED_NOT_ACCEPTED_BY_OWNER`.
Do not overwrite accepted v0.1 review ZIP.
