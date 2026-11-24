# Current stage

**Stage:** 05 Gate 1B extractor pilot v0.1
**Phase:** OPEN — candidate extraction executed — precision/recall not measured — Gate 2 closed
**Last updated:** 2026-11-17

Published v0.1.1 bundle and Gate 1A decision records stay frozen. Gate 1B is open. Gate 2 and Gate 3 are not open.

## Published v0.1.1 bundle

Point correction of v0.1 evidence provenance and clean-extraction replay.
Not a new scientific stage. Not model training. The bundle stays frozen.

`INTERVENTION_RESPONSE_READINESS_STATUS`=NOT_READY
`TECHNICAL_AUDIT_STATUS`=PASS
`DOMAIN_ACCEPTED_MAPPING_COUNT`=0
`UPSTREAM_EVIDENCE_SNAPSHOT_STATUS`=PASS
`CORE_READINESS_REPLAY_STATUS`=PASS

SHA-256: `1a53215e69e5de22c57c1396fab3d93d0124c667315331a450e0712a166b20ef`

## Commands

```bash
audit --root . intervention-readiness run-v0.1 --no-publish
audit --root . intervention-readiness verify-v0.1.1
audit --root . intervention-readiness publish-v0.1.1
```

Stop after the v0.1.1 bundle. Do not start mapping acquisition, cohort construction,
or intervention-response training.

## Exposure source discovery v0.1 (owner-approved, DRAFT)

Aggregate-only, read-only discovery of recommendation and intake fields in both sources.
Artifacts: `artifacts/exposure-source-discovery-v0.1/` (report status DRAFT, privacy PASS_AGGREGATE_ONLY).
Field meanings remain UNKNOWN pending owner review. Readiness result unchanged.

```bash
uv run --frozen python -m human_simulator.exposure_source_discovery_v01.discover
uv run --frozen python -m human_simulator.exposure_source_discovery_v01.discover followup
```

## Exposure source discovery v0.2 (owner-approved, technical FINAL)

Semantic, identity and temporal validation of the v0.1 sources. Not Stage 05 Gate 1.
Artifacts: `artifacts/exposure-source-discovery-v0.2/`.
Technical discovery PASS. Identity linkage NOT_ESTABLISHED. Field meanings remain
UNKNOWN_PENDING_HUMAN_REVIEW. Candidate tier is not accepted. Readiness remains NOT_READY.
No external-review ZIP.

```bash
uv run --frozen --no-sync python -m human_simulator.exposure_source_discovery_v02.orchestrator
```

## Exposure source discovery v0.2.1 (accounting correction)

Closes the v0.2 feedback temporal ledger. Not Stage 05 Gate 1.
Artifacts: `artifacts/exposure-source-discovery-v0.2.1/`.
v0.2 temporal accounting stays `NOT_RECONCILED`; the v0.2.1 exclusive ledger is technical FINAL.
Identity linkage remains `NOT_ESTABLISHED`. Readiness remains `NOT_READY`.
No external-review ZIP.

```bash
uv run --frozen --no-sync python -m human_simulator.exposure_source_discovery_v021.orchestrator
```

## Exposure source discovery v0.2.2 (owner decision ingestion)

Records the system architect's answers as schema-valid decisions (9 of 15 answers; "не помню"
answers stay UNKNOWN). Not Stage 05 Gate 1. Artifacts: `artifacts/exposure-source-discovery-v0.2.2/`.
Source A `medicines` holds drugs and supplements; `activity` is a lifestyle section, so the v0.2
dose-like signal there is not medication evidence. Source B identity is an owner statement with a
recall caveat, not data proof. Timezone is Europe/Moscow by owner statement.
Administration mappings 0, domain-accepted mappings 0, readiness `NOT_READY`. No external-review ZIP.

```bash
uv run --frozen --no-sync python -m human_simulator.exposure_source_discovery_v022.orchestrator
```

## Stage 05 Gate 1A v0.1 (human evidence gate)

Attests the frozen v0.2.2 answers. No database access and no model.
Artifacts: `artifacts/stage-05-gate-1a-v0.1/`.
Execution `PASS`. Attestation `INCOMPLETE`: 4 of 14 questions accepted
(medicines section, feedback author, timing, period).
Feedback semantics `PARTIALLY_ATTESTED`. Subject identity
`INSUFFICIENT_ATTESTATION_NOT_DATA_PROOF`. Patient-reported intake
`NOT_ACCEPTED_INSUFFICIENT_ATTESTATION`.
Eligible cells 0. Readiness `NOT_READY`. No external-review ZIP.

```bash
uv run --frozen --no-sync python -m human_simulator.stage05_gate_1a_v01.orchestrator
```

## Stage 05 Gate 1A completion v0.1

Qualifies the accepted `B_TIMING` and `B_PERIOD` decisions as workflow intent, not row-level proof.
Does not rewrite the 14 Gate 1A v0.1 records. Artifacts: `artifacts/stage-05-gate-1a-completion-v0.1/`.
`GATE_1A_STATUS`=`PARTIALLY_ATTESTED_OPEN`. `GATE_1B_STATUS`=`BLOCKED`.
Readiness `NOT_READY`. No Source B form schema was found in the Magerya code copy.
v0.2.2 answer hashes were recomputed from `owner-answer-record.json` and match the decision records.

```bash
uv run --frozen --no-sync python -m human_simulator.stage05_gate_1a_completion_v01.orchestrator
```

## Stage 05 Gate 1A primary evidence recovery v0.1

Reads catalogs and the configured Magerya checkout. Does not rewrite Gate 1A v0.1 or completion records.
Artifacts: `artifacts/stage-05-gate-1a-evidence-recovery-v0.1/`.
`GATE_1A_EVIDENCE_RECOVERY_STATUS`=`PASS`. `GATE_1A_STATUS`=`PARTIALLY_ATTESTED_OPEN`.
`GATE_1B_STATUS`=`BLOCKED`. `SOURCE_B_APPLICATION_CODE_ACCESS_STATUS`=`NOT_AVAILABLE`.
No new superseding record. Timing and period assign 0 rows.
`B_IDENTITY` has a consultation-row foreign key and no subject-key foreign key.
Readiness `NOT_READY`. No external-review ZIP. Gate 1B was not started.

```bash
uv run --frozen --no-sync python -m human_simulator.stage05_gate1a_evidence_recovery_v01.orchestrator
```

## Stage 05 Gate 1A owner attestation v0.1

Records the 2026-11-17 answers for the six Source B blockers. Does not rewrite earlier decision records.
Artifacts: `artifacts/stage-05-gate-1a-owner-attestation-v0.1/`.
`GATE_1A_STATUS`=`SOURCE_B_ROUTE_ACCEPTED_SOURCE_A_OPEN`.
`GATE_1B_STATUS`=`READY_FOR_EXPLICIT_OWNER_OPENING`. Gate 1B was not started.
`drugs` and `vitamins` are current intake and stay separate. `change_drugs` is replacement.
`decline_drugs` is discontinuation. `drugs_first` is previously prescribed.
`feedback.user_id` and `consultations.patient_id` are the same `users.id`, without a database foreign key.
Short yes and no are free text. `B_POSITIVE` stays deferred.
Readiness `NOT_READY`. Source A stays open.

```bash
uv run --frozen --no-sync python -m human_simulator.stage05_gate1a_owner_attestation_v01.orchestrator
```

## Stage 05 Gate 1B extractor pilot v0.1

The owner opened Gate 1B on 2026-11-17. Artifacts: `artifacts/stage-05-gate-1b-extractor-pilot-v0.1/`.
`GATE_1B_STATUS`=`OPEN`. `GATE_1B_PILOT_STATUS`=`EXECUTED_PRECISION_RECALL_NOT_MEASURED`.
`GATE_1B_ACCEPTED`=`false`. `PRECISION_RECALL_STATUS`=`NOT_MEASURED`.
The candidate extractor read 41407 Source B rows for `drugs`, `vitamins`, `change_drugs`, `decline_drugs`, and `drugs_first`.
The fields stay separate. A candidate is not administration. No source text was retained.
`positive_changes` is not extracted. Source A stays open. Gate 2 stays closed.
Readiness `NOT_READY`.

## Visit-to-visit medicine orders v0.1

Aggregate count of doctor medicine orders on completed clinic and online visits in Source A.
Artifacts: `artifacts/stage-05-visit-order-chain-v0.1/`.
47429 visits, 30583 consecutive pairs, 2676 visits with an added medicine order.
28247 pairs have no added order on either visit. An added order is not administration.
The stage catalog has two medicine categories, `drug` and `supplements`. Screen titles for those categories are not stored in the stage database.
`drug` is present on 1991 visits. `supplements` is present on 2208 visits.
Those visit figures are from the local stage dump. The separate stage container on the dev server has 72635 appointments.
36449 of them, 50.2 percent, have a filled «Медикаменты» or «Препараты и витамины» section or a catalog order with status `added`.
The owner confirmed that union and stated that a prescription belongs to the visit. All 36449 rows are attached to an appointment: 36333 completed, 102 canceled, 14 another status. The owner then stated that this intake is not an action recorded in the database and that every patient took these drugs. That statement is owner evidence on the union. Domain-accepted mappings stay 0 and eligible cells stay 0. Among 48128 consecutive completed visits, 12292 pairs change the prescription in both directions and 90 keep the same names.
The owner named the doctor questionnaire as the visit completion document for every visit except manipulations. The doctor enters it, and on a written visit the patient enters it. Completed visits without that document, apart from manipulations, are 470 clinic and 670 online visits on the psychologist scheme, 1 written visit, and 187 visits with no visit type. The next-visit state remains that document plus a received laboratory result or functional study. Pairs with the confirmed prescription on the previous visit and a doctor questionnaire on the next visit: 19778. Both visits have that document. The stored examination text differs for goal in 12073 of those pairs, complaints in 8216, anamnesis in 9386, objective status in 8585, and local status in 4809. Where the same received analysis is present on both visits, the stored values differ in 1797 pairs and match in 757. Eligible cells stay 0.
The most common normalized prescription label on that container is «омега-3 (жизнивек) капсулы – 2 раза»: 8169 visits, 5384 from a recommendation section and 2785 from the catalog. Consecutive pairs with that label on the previous visit and a doctor questionnaire on the next: 3665. Goal text changes in 2281 of them. The same received analysis is present on both visits in 318 pairs, and the stored values differ in 215. The stage catalog does not store what this product is made of. The owner confirmed the label is the SKU https://zhiznivek.ru/catalog/product/omega-3-ultramaks-200ml-60-kap-1500-mg-steklyannaya-banka and supplied the product table. The adult recommended daily intake on that table is not less than 4500 mg omega-3 polyunsaturated fatty acids, 3000 mg EPA and 1200 mg DHA. The clinic regimen is two capsules, which is 3000 mg, 2000 mg and 800 mg. That dose applies to 3514 of the 3665 pairs, the ones aged 18 or older. 115 pairs are aged 11 to 17 and 36 are under 11. The script is `python -m human_simulator.stage05_visit_popular_probe_v01`. Gate 2 stays closed.
The local dump count above excludes written visits. Gate 2 stays closed.

```bash
uv run --frozen --no-sync python -m human_simulator.stage05_gate1b_extractor_pilot_v01.orchestrator
```
