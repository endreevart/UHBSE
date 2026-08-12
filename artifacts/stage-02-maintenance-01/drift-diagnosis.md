# Stage 02 Maintenance 01 — Relationship Manifest Drift Diagnosis

Maintenance version: 0.1
Report status: DRAFT
Defect: `stage02_relationship_manifest_drift`
Repair applied: **no**

## What is wrong

`relationship-manifest.sha256` records a SHA-256 for eight artifacts. Six match. Two do not:

| Artifact | Manifest records | File is |
|----------|------------------|---------|
| `subject-root-analysis.json` | `285ea434c7f13daa8ca10f859beb4743c468174a9d3785b4d2bd576b097d9083` | `9a685d76cc45cdb948b89d28cc13c6df61984dd15f21c424c5d42f21f76c98e8` |
| `identity-linkage-assessment.json` | `d5481701a6ee435dbdda2b15825bd09993196503f194cdd65eb918fbddc634cc` | `9bc39761915a77308569fef183523a7310bc8248ab62849e648206867c685cd6` |

The obvious repair is to recompute the manifest over the files on disk. That would turn an unexplained difference into a signed statement that the current bytes are correct, which is the one thing not yet established. So provenance comes first.

## Where the drift came from

Two controls pin the same two files, and they disagree.

* `artifacts/stage-02/relationship-manifest.sha256` pins all eight relationship artifacts.
* `human_simulator.stage03.prior_stage_integrity.ACCEPTED_SHA256` pins nine Stage 01/02 files, seven of them in Stage 02.

The intersection of the two sets is exactly `identity-linkage-assessment.json`, `subject-root-analysis.json` — precisely the two artifacts that drifted. The six artifacts the manifest alone pins still match it.

The timestamps inside the artifacts show what happened. Each assessment run writes all eight artifacts together, so a `.json` and its own `.md` sibling always agree about when they were assessed — unless something replaced one of them afterwards. They do not agree:

| Artifact | `assessed_at` in the JSON | `Assessed at` in the markdown |
|----------|---------------------------|-------------------------------|
| `identity-linkage-assessment.json` | `2026-07-31T22:38:21.077245+00:00` | `2026-08-01T16:52:05.567497+00:00` |
| `subject-root-analysis.json` | `2026-07-31T22:38:20.665954+00:00` | `2026-08-01T16:52:04.302478+00:00` |

The markdown timestamps are the ones the manifest was sealed at: `relationship-verification-report.json` carries the matching `verified_at` and records `relationship_manifest: PASS, verified 8 entries`, so at that moment all eight artifacts did match. Only the two `.json` files were later moved back to the earlier run — the bytes the prior-stage baseline pins. Nothing pins the markdown, so nothing reverted it. A `.json` disagreeing with its own `.md` is the fingerprint of a targeted restore, not of a regeneration.

### The mechanism, by name

`audit restore-prior-stage-baseline --confirm` copies controlled Stage 01/02 bytes out of `artifacts/external-review/stage-03-design-v0.7.1-review.zip`. Of the eight relationship artifacts it covers exactly `identity-linkage-assessment.json`, `subject-root-analysis.json`, and it does not cover the relationship manifest (`covers_the_relationship_manifest: False`). Its source copies of those two files hash to precisely the bytes now on disk (`source_matches_current_bytes: True`). Running it after the manifest was sealed therefore produces the observed state exactly, which is what `explains_the_observed_state: True` records. This is a design consequence of two controls overlapping, not corruption and not a fault in the restore.

## Which bytes are authoritative

The bytes currently on disk. Two controls already vouch for them:

* `subject-root-analysis.json` — `9a685d76cc45cdb948b89d28cc13c6df61984dd15f21c424c5d42f21f76c98e8` is pinned by the prior-stage baseline and published verbatim in 11 accepted review bundles.
* `identity-linkage-assessment.json` — `9bc39761915a77308569fef183523a7310bc8248ab62849e648206867c685cd6` is pinned by the prior-stage baseline and published verbatim in 11 accepted review bundles.


A third check rules out the alternative rather than supporting the claim: the bytes the manifest expects are vouched for by nothing at all.

The bytes the manifest expects appear in **no** published release. Every review bundle in `artifacts/external-review/` was searched, along with the whole working tree; `285ea434c7f13daa8ca10f859beb4743c468174a9d3785b4d2bd576b097d9083` and `d5481701a6ee435dbdda2b15825bd09993196503f194cdd65eb918fbddc634cc` occur nowhere. They cannot be restored, because no accepted artifact contains them.

## The difference is a timestamp, not a finding

38 comparisons were made: every published copy of both artifacts, plus a fresh read-only reproduction, each against the working copy. With `assessed_at` removed, every body is identical — `all_semantically_identical: True`.

That covers the verdicts (`identity_verdict`, `overall_verdict`, `coverage_threshold_confirmed`), the aggregates and their denominators (`source_a_aggregates`, `source_b_aggregates`, `overlap_aggregates`), the `conflict_definition`, the HMAC posture (`hmac_key_persisted_in_artifacts: false`) and the subject resolution paths. No verdict moved, no denominator moved, no conflict definition changed.

## Read-only reproduction

`assess-source-relationship` was re-run against a throwaway copy of the workspace: assessment completed in a throwaway workspace with status PASS. Both sources were queried through their dedicated read-only audit roles, `raw_databases_unchanged` is `True` from row-count fingerprints taken before and after, and `validate_relationship_artifacts` reported 0 safety findings. The reproduction's body matches the working artifacts; only `assessed_at` moved to the time of the run.

Row-level values were processed inside the local runtime to compute keyed digests for the aggregate linkage, which is what this assessment does. No row value reached an artifact, a log or this report. `artifacts/stage-02/` was not written by the reproduction: it ran entirely in the throwaway copy, which was discarded.

## Candidate repair

`artifacts/stage-02-maintenance-01/candidate/` holds the eight artifacts with the bytes an accepted release published, unmodified, and a manifest sealed over exactly those bytes. Zero artifacts are regenerated; one manifest is re-sealed.

Candidate manifest: `13aae26b37032730c533740bc513872cb2a6890429b64ebd2fb923ffcf672974`

Applied to a throwaway copy of the workspace:

* `relationship_manifest_hashes_match` — PASS (verified 8 entries in relationship-manifest.sha256)
* `verify-stage-02` — PASS across 51 evaluated checks, including `relationship_manifest` = PASS. Its `full_test_suite` and `test_result_not_skipped` checks were not evaluated: verify-stage-02 runs the whole pytest suite as a check, which inside a throwaway copy would re-enter the publication pipeline.
* `stage02_relationship_integrity_pre_live_load` — FAIL
* `stage02_relationship_manifest_drift` cleared — True

The gate still fails, and must: clearing the manifest drift leaves 4 of the five pre-live-load blockers open (`canonical_loader_runtime_principal_undefined`, `encounter_provider_id_population_disagreement`, `source_subject_key_opacity_undefined`, `temporal_precision_field_absent_from_model`). This maintenance changeset resolves one defect's *diagnosis*, not the live-load gate.

## What was not done

* artifacts/stage-02/ not written
* no automatic restore performed
* no repair applied
* relationship manifest not resolved in the working tree
* Design v0.7.5 not created
* Plan v0.3.6 not created
* Changeset 02 not started
* no ETL, extraction or load
* no canonical schema or migration change
* no published archive overwritten

## Residual observations

* subject-root-analysis.md and identity-linkage-assessment.md still record the 2026-08-01T16:52Z run while their .json siblings record 2026-07-31T22:38Z — action: none. both markdown files match the manifest and were published in accepted bundles; regenerating them to agree would create fresh unattested bytes and a second drift.
* assessed_at makes every relationship artifact non-reproducible byte for byte — action: recorded for a future changeset. changing artifact generation is out of scope for a diagnosis.
