# Reproduce — Medication-Association Baseline v0.1.1

```bash
uv run --frozen audit --root . intervention-association verify-v0.1.1
uv run --frozen audit --root . intervention-association run-v0.1.1 --no-publish
uv run --frozen pytest tests/test_intervention_association_v011_unit.py -q
```

Authoritative comparison: M1 vs M2C (signed feature hashing).
Legacy ordinal M2 is diagnostic only.
Clinical use and causal interpretation are prohibited.
