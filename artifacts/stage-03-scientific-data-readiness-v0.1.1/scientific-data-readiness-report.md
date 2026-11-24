# Scientific Data Readiness v0.1.1

**Scientific status:** EXPLORATORY_RETROSPECTIVE_PIPELINE_PASS
**Technical pipeline:** TECHNICAL_PIPELINE_PASS
**Backtest:** FIRST_EXPLORATORY_RETROSPECTIVE_BACKTEST_PASS
**Incremental signal:** NO_INCREMENTAL_SIGNAL_DETECTED
**Uncertainty:** UNCERTAINTY_CALIBRATION_PASS

## Methodology corrections vs v0.1

- Strict consecutive neighbor pairs only (not all-forward combinations)
- Subject split before outcome selection (train/discovery only)
- Split class: `EXPLORATORY_SUBJECT_DISJOINT_SPLIT`
- Sample-level temporal leakage audit
- Subject-macro MAE primary; pair-micro MAE secondary
- Shuffled-label control retrains on shuffled train labels

## Selected outcome (train-only)

- candidate_id: `2685c68a3e247ca4`
- label: `Т3 св.`
- unit: `пмоль/л`
- medical interpretation: DOMAIN_REVIEW_PENDING

## Dataset

- observations after filter: 114
- subjects with pairs: 30
- consecutive pairs: 40
- split pairs: {'train': 25, 'validation': 13, 'test': 2, 'total': 40}
- split subjects: {'train': 22, 'validation': 6, 'test': 2, 'total': 30}

## Test metrics

- Persistence subject-macro MAE: 1.425
- Empirical trend subject-macro MAE: 1.425
- Ridge subject-macro MAE: 0.5236782086594662
- Outperforms persistence: False

## Leakage / shuffle

- leakage: PASS evaluated=40 violations={}
- shuffle permutations: 20 fraction≤real=0.0
