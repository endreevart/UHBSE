---
name: verify-stage-03-design
description: Validate Stage 03 canonical model design artifacts and preconditions.
disable-model-invocation: true
---

Verify Stage 03 design per `docs/stage-03-acceptance.md`.

Do not fix missing requirements automatically unless the user asks.

Check:

- Stage 01 FINAL, Stage 02 FINAL, verify-stage-02 PASS;
- stage-02-final-manifest.sha256 valid;
- 17 unresolved mappings; population overlap NOT_ESTIMABLE; Subject B CANDIDATE;
- all design artifacts present under artifacts/stage-03/;
- content artifact list matches STAGE03_CONTENT_ARTIFACTS in constants;
- record construction contract and construction group completeness;
- canonical ID contract (HMAC-SHA256, domain separation, test vectors);
- Source B subject eligibility (no unconditional public.users emission);
- mapping target collision policy explicit (record_group alone insufficient);
- canonical model layers and 29 required entities including SubjectCharacteristic;
- provenance, temporal, and state-snapshot contracts;
- scenario_event_precedence_contract in canonical model constraints;
- mapping drafts have status/evidence/lossiness; demographic mappings validated;
- no global patient ID, no PII/credentials;
- design-content-manifest.sha256 valid and excludes itself, report, verification JSON;
- stage-03-design-report.md remains DRAFT;
- no stale legacy manifest references in active Stage 03 docs/rules/skills/commands.

Run: `audit --root . stage-03-check`

Return PASS or FAIL with failed checks and required actions.

Do not promote report to FINAL.
Do not start implementation phase.
