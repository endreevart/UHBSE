# Stage 02 Maintenance 01 — Relationship Manifest Drift Diagnosis

**Maintenance version:** 0.1
**Report status:** FINAL
**Defect:** `stage02_relationship_manifest_drift`
**Repair applied:** yes

## Purpose

Stage 02 is FINAL, but `artifacts/stage-02/relationship-manifest.sha256` disagrees with two of the
eight artifacts it covers. That disagreement is the first of the five open pre-live-load blockers.

This maintenance changeset diagnosed the drift and applied the authorised manifest-only repair.
Only `artifacts/stage-02/relationship-manifest.sha256` changed; the eight relationship artifacts
and nine controlled Stage 01/02 files are unchanged.

## Why not simply recompute the manifest

Recomputing produces a manifest that verifies. It also converts an unexplained difference into a
signed statement that the bytes on disk are correct — which is exactly the claim that had not been
established. The recomputed manifest would be indistinguishable from one sealed over corrupted
artifacts.

So the provenance and the semantics come first, and the repair is only proposed once both hold.

## What the diagnosis establishes

The drift is a collision between two controls that pin the same files.

* `artifacts/stage-02/relationship-manifest.sha256` pins all eight relationship artifacts.
* `human_simulator.stage03.prior_stage_integrity.ACCEPTED_SHA256` pins nine Stage 01/02 files.

Their intersection is exactly `subject-root-analysis.json` and `identity-linkage-assessment.json` —
precisely the two that drifted. `audit restore-prior-stage-baseline --confirm` restores the
intersection and does not touch the manifest, so running it after the manifest was sealed leaves
the two out of step by construction.

Two independent observations confirm the sequence. The markdown sibling of each drifted file still
records the assessment run the manifest was sealed at, while the `.json` records an earlier one; a
regeneration writes both together, so only a targeted restore explains the split. And the restore
source archive's copies of both files hash to exactly the bytes now on disk.

The difference between every observed copy of these artifacts is `assessed_at` and nothing else.
Every verdict, aggregate, denominator and conflict definition is identical across all published
copies and across a fresh read-only reproduction.

## Authoritative bytes

The bytes currently in `artifacts/stage-02/` are authoritative:

| Artifact | Authoritative SHA-256 |
|----------|------------------------|
| `subject-root-analysis.json` | `9a685d76cc45cdb948b89d28cc13c6df61984dd15f21c424c5d42f21f76c98e8` |
| `identity-linkage-assessment.json` | `9bc39761915a77308569fef183523a7310bc8248ab62849e648206867c685cd6` |

They are pinned by the prior-stage integrity baseline, published verbatim in accepted review
bundles, and confirmed semantically current by reproduction. The bytes the manifest expects appear
in no published release and cannot be reconstructed from any accepted artifact.

## Proposed repair

Re-seal `relationship-manifest.sha256` over the accepted artifact bytes. Zero artifacts change; one
manifest changes. The candidate is in `artifacts/stage-02-maintenance-01/candidate/`.

Applied to a throwaway copy, it makes the relationship manifest verify, clears
`stage02_relationship_manifest_drift`, and leaves the pre-live-load gate at FAIL on the remaining
four blockers — which is correct, because this changeset resolves one defect's diagnosis, not the
live-load gate.

## Authorised repair application

After diagnosis, the manifest-only repair is applied through a separate, explicitly confirmed
command:

```bash
audit --root . stage-02-maintenance-01-apply --confirm
```

Only `artifacts/stage-02/relationship-manifest.sha256` may change. The eight relationship
artifacts are not copied from the candidate. Without `--confirm` the command refuses. Post-apply
checks run immediately; on failure the original manifest is restored and `rolled_back: true` is
recorded. No database connections are opened during apply.

## Commands

```bash
audit --root . stage-02-maintenance-01              # diagnose, prepare candidate, publish bundle
audit --root . stage-02-maintenance-01 --no-publish # diagnose only
audit --root . stage-02-maintenance-01-apply --confirm  # apply manifest repair and publish promotion bundle
pytest tests/test_stage_02_maintenance_01.py
```

The diagnosis re-runs `assess-source-relationship` in a throwaway workspace copy, which needs both
sources reachable through `mg_audit_ro` and `kgz_audit_ro` and `LINKAGE_HMAC_KEY` in the local
environment.

## Data handling

Row-level values were processed inside the local runtime to compute keyed digests for the aggregate
linkage. No row value reached an artifact, a log, a report or this repository. Both sources were
queried through their dedicated read-only roles, and row-count fingerprints taken before and after
confirm the raw databases are unchanged.

## Not in this changeset

* Design v0.7.5 and Plan v0.3.6 are not created.
* Changeset 02 is not started; no ETL, extraction or load.
* No canonical schema or migration change.
* The published Changeset 01 review bundle is not republished.
