# Reproduce — Population / Multi-Outcome / Intervention v0.1

```bash
uv sync --frozen --extra dev
uv run --frozen audit --root . population-multi-outcome-v01 run --full --no-publish
uv run --frozen audit --root . population-multi-outcome-v01 verify
uv run --frozen audit --root . population-multi-outcome-v01 publish
```

Security stage remains `PAUSED_NOT_ACCEPTED_BY_OWNER`.
