# Reproduce — Medication Concept Harmonization v0.1

Public verification only. Full recomputation needs private episodes (see REPRODUCE_PRIVATE.md).

```bash
uv sync --frozen --extra dev

uv run --frozen pytest tests/test_medication_concept_harmonization_v01_unit.py -q

uv run --frozen audit --root . medication-concept verify-v0.1
```

SOURCE_RECORD_EXACT_JOIN is not accepted drug-concept harmonization.
Legacy ordinal M2ID is invalid for authoritative comparison.
Clinical use and causal interpretation are prohibited.
