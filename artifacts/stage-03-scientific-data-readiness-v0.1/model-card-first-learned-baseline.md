# Model card — FirstLearnedBaseline v0.1.0

- Model family: ridge_regression
- Claim level: RETROSPECTIVE_BASELINE_ONLY
- Clinical validation: NOT_CLAIMED
- Feature schema hash: `14303f8d4197b9bf8205bcb912bbb294c75f4ff2f7e22d2ae42290f97c4e29ff`
- Training configuration hash: `ed068794f4ad1c840f0b15ac33a9498787f981d4af728296175d4ae312c1bd79`
- Seed: 42
- L2: 1.0

## Intended use

Retrospective prediction of natural observed dynamics for one measurement label
selected by coverage gates. Not an intervention-response model.

## Limitations

- Small pilot cohort; exploratory split possible
- No causal treatment effect claim
- Medical semantics of measurement label: DOMAIN_REVIEW_PENDING
- Empirical residual intervals only
