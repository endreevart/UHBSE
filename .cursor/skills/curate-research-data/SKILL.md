---
name: curate-research-data
description: Correct, annotate and enrich research data with provenance.
disable-model-invocation: true
---

Work only with derived datasets.

Allowed operations:

- correction;
- normalization;
- expert annotation;
- calculation of derived values;
- imputation;
- generation of synthetic experimental records.

Never modify the original restored database.

Every operation must preserve provenance and record_origin.
