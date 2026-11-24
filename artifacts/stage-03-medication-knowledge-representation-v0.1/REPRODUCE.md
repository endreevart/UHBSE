# Reproduce — Medication Knowledge Representation v0.1

Public verification only. Full scientific recomputation requires private
row-level episodes and is documented in `REPRODUCE_PRIVATE.md`.

```bash
uv sync --frozen --extra dev

uv run --frozen pytest \
  tests/test_medication_knowledge_representation_v01_unit.py \
  tests/test_intervention_association_v011_unit.py \
  tests/test_intervention_association_v01_unit.py -q

uv run --frozen audit --root . medication-knowledge verify-v0.1

uv run --frozen audit --root . intervention-association verify-v0.1.1
```

Artifact verification ≠ full model recomputation.
Clinical use and causal interpretation are prohibited.
