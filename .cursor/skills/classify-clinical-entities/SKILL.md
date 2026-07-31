---
name: classify-clinical-entities
description: Find candidate clinical entities in a profiled clinic schema.
disable-model-invocation: true
---

Using schema metadata and sanitized profiling outputs.
The local profiler may use row-level data, but this skill must not receive raw rows.

Identify candidate tables for:

- patients;
- visits;
- doctors;
- specialties;
- laboratory results;
- diagnoses;
- prescriptions;
- medications;
- procedures;
- ultrasound examinations;
- operations;
- medical documents;
- measurements;
- appointments.

Do not mark mappings as confirmed unless evidence exists.

Generate:

- artifacts/stage-01/entity-candidates.yaml;
- artifacts/stage-01/relation-graph.md;
- artifacts/stage-01/unknown-semantics.md.
