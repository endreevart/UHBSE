# Future work (out of current stage)

Items deferred until the current stage gate passes. Do not implement until the preceding Stage 05 gate is explicitly accepted.

<!-- Example entry:
## [YYYY-MM-DD] Short title
- Requested by: ...
- Stage: 02+
- Notes: ...
-->

## [2026-11-06] Stage 05 Gate 1B — medication and regimen extractor pilot

- Requested by: stage plan
- Stage: 05 Gate 1B
- Status: OPEN
- Notes: opened on 2026-11-17. The candidate extractor counted 41407 Source B rows. The pilot is not accepted. Precision and recall are not measured. B_POSITIVE stays deferred and must not become a response label. Source A still open: recommendation items, the complete medication-code set, and document finality. Private manual labels and precision/recall. Not administration. No patient-level publication. No model.

## [2026-11-06] Stage 05 Gate 2 — exposure episode construction

- Requested by: stage plan; closed until Gate 1B is accepted
- Stage: 05 Gate 2
- Notes: link recommendation, self-report, and the next consultation or laboratory change. Check time windows, polypharmacy, and ambiguous attribution. No cross-source identity merge.

## [2026-11-06] Stage 05 Gate 3 — intervention-response modeling readiness

- Requested by: stage plan; closed until Gate 2 is accepted
- Stage: 05 Gate 3
- Notes: first point at which eligible cells may be recomputed and an associational response model may be considered. Not a treatment-effect or causal claim.
