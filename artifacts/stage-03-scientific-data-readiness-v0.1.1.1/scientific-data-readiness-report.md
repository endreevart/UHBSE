# Scientific Data Readiness v0.1.1.1

**Scientific status:** EXPLORATORY_RETROSPECTIVE_PIPELINE_PASS
**Technical pipeline:** TECHNICAL_PIPELINE_PASS
**Backtest:** FIRST_EXPLORATORY_RETROSPECTIVE_BACKTEST_PASS
**Incremental signal:** NO_INCREMENTAL_SIGNAL_DETECTED
**Interval construction:** UNCERTAINTY_INTERVAL_CONSTRUCTION_PASS
**Uncertainty calibration:** INSUFFICIENT_DATA_FOR_UNCERTAINTY_CALIBRATION
**Interval sharpness:** INTERVAL_SHARPNESS_NOT_ESTABLISHED

## Evidence corrections vs v0.1.1

- Gaussian interval multiplier derived from nominal coverage (not fixed 1.96 for 0.90)
- Interval construction status separated from calibration status
- Held-out test size gates calibration PASS
- Shuffled-label control uses frozen real-model L2
- Strict consecutive neighbor pairs only (not all-forward combinations)
- Subject split before outcome selection (train/discovery only)
- Split class: `EXPLORATORY_SUBJECT_DISJOINT_SPLIT`
- Sample-level temporal leakage audit
- Subject-macro MAE primary; pair-micro MAE secondary
- Shuffled-label control retrains on shuffled train labels with frozen configuration
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
- real L2: 0.1 shuffled L2: 0.1
- config equality: PASS
- mean interval width (test): 16.026728278036572
- interval multiplier: 1.6448536269514715
