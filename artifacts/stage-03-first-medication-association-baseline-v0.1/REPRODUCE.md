# Reproduce — Medication-Association Baseline v0.1

```bash
uv run --frozen audit --root . intervention-association verify-v0.1
uv run --frozen audit --root . intervention-association run-v0.1 --no-publish
uv run --frozen pytest tests/test_intervention_association_v01_unit.py -q
```

Row-level episode JSONL remains workspace-only under `private/intervention-association-v01/`.
Clinical use and causal interpretation are prohibited.
