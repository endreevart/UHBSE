# Reproduce — Medication Reference Acquisition v0.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_medication_reference_acquisition_v01_unit.py -q
uv run --frozen audit --root . medication-reference verify-v0.1
```

Private provider caches, decision logs and full medication strings are not in this ZIP.
Clinical use and causal interpretation are prohibited.
