"""Frozen paths and publication constants for the public roadmap series v0.1.1."""

from __future__ import annotations

from pathlib import Path

SERIES_VERSION = "0.1.1"
SERIES_ID = "uhbse-roadmap-series-v0.1.1"
SERIES_TITLE = "UHBSE — Building a Human Biology Simulation Engine"
EVIDENCE_DIR = Path("artifacts") / "stage-03-public-roadmap-series-v0.1.1"
PUBLIC_MEDIA_DIR = Path("artifacts") / "public-media" / SERIES_ID
CORE_DIR = Path("artifacts") / "stage-03-core-vertical-slice-v0.1.2.1"
PRIOR_V012_DIR = Path("artifacts") / "stage-03-core-vertical-slice-v0.1.2"
SDR_DIR = Path("artifacts") / "stage-03-scientific-data-readiness-v0.1.1.1"
EXTERNAL_DIR = Path("artifacts") / "external-review"

CORE_ZIP_NAME = "stage-03-core-vertical-slice-v0.1.2.1-review.zip"
CORE_ZIP_SHA256 = "9eea316ccc022e6aed75075b47089b10a1263e55e2c58b9fd6852e8201fe1a5f"
ACCEPTED_V01_ZIP_SHA256 = "933c34bee1f03af9e22c54be2fb5aa4022228bb7353a35ad2f7e93d3793cb67c"
ACCEPTED_V011_ZIP_SHA256 = "13fbf307fd03eb8ed419a800ff7fed254a8159240482e8ac4b28b5f391941128"
ACCEPTED_V012_ZIP_SHA256 = "d4218dda05cdf8657e03768ce81727e274a691e90abee3ff701bae1018f419f8"
ACCEPTED_SDR_V0111_ZIP = "stage-03-scientific-data-readiness-v0.1.1.1-review.zip"
ACCEPTED_SDR_V0111_SHA256 = (
    "2b23e48fa9e6687171c60ca371b7aa923d04285e6c3edfe5637cd64060edb67e"
)
ACCEPTED_ROADMAP_V01_ZIP = "stage-03-public-roadmap-series-v0.1-review.zip"
ACCEPTED_ROADMAP_V01_SHA256 = (
    "cccc45fe7f329952dc798d6707be5e331665fa2069255c3a30a8ea324fcfd036"
)

REVIEW_ZIP_NAME = "stage-03-public-roadmap-series-v0.1.1-review.zip"
PUBLICATION_STATUS = "PRIVATE_PUBLICATION_REVIEW_REQUIRED"
REVIEW_BUNDLE_KIND = "PROXY_PUBLICATION_REVIEW_PACKAGE"
HASH_PREFIX_LEN = 10
FPS = 30
WIDTH = 1080
HEIGHT = 1920
PROXY_WIDTH = 720
PROXY_HEIGHT = 1280

# Relation keys stay in this module only. They are never written to public fixtures.
_VOLUME_RELATION = {
    "subjects": "account_patient",
    "appointments": "appointment_appointment",
    "laboratory_records": "document_analysisresult",
    "result_items": "document_analysisresultitem",
}
_TRUNCATION_RELATION = {
    "laboratory_records": "document_analysisresult",
    "result_items": "document_analysisresultitem",
}

EPISODES: tuple[dict[str, object], ...] = (
    {
        "id": "Roadmap01",
        "slug": "01-longitudinal-data",
        "filename": "uhbse-roadmap-01-longitudinal-data-v0.1.1.mp4",
        "title": "The longitudinal data problem",
        "duration_frames": 270,
        "capability_status": "WORKING_NOW",
        "cover_headline": "43,856 entered. 100 made the first testable cohort.",
    },
    {
        "id": "Roadmap02",
        "slug": "02-canonicalization",
        "filename": "uhbse-roadmap-02-canonicalization-v0.1.1.mp4",
        "title": "What survives normalization",
        "duration_frames": 270,
        "capability_status": "WORKING_NOW",
        "cover_headline": "Most of the work happens before the model.",
    },
    {
        "id": "Roadmap03",
        "slug": "03-evidence-state",
        "filename": "uhbse-roadmap-03-evidence-state-v0.1.1.mp4",
        "title": "From history to state",
        "duration_frames": 270,
        "capability_status": "WORKING_NOW",
        "cover_headline": "A computer needs a state before it can simulate a future.",
    },
    {
        "id": "Roadmap04",
        "slug": "04-counterfactual-branching",
        "filename": "uhbse-roadmap-04-counterfactual-branching-v0.1.1.mp4",
        "title": "Forking a biological state",
        "duration_frames": 270,
        "capability_status": "WORKING_NOW",
        "cover_headline": "Same starting state. One controlled change. Two continuations.",
    },
    {
        "id": "Roadmap05",
        "slug": "05-engine-verification",
        "filename": "uhbse-roadmap-05-engine-verification-v0.1.1.mp4",
        "title": "How we test the engine",
        "duration_frames": 270,
        "capability_status": "WORKING_NOW",
        "cover_headline": "A simulation should be able to fail.",
    },
    {
        "id": "Roadmap06",
        "slug": "06-first-scientific-test-next",
        "filename": "uhbse-roadmap-06-first-scientific-test-next-v0.1.1.mp4",
        "title": "The first scientific test",
        "duration_frames": 270,
        "capability_status": "FIRST_EXPLORATORY_RETROSPECTIVE_BACKTEST_COMPLETE",
        "cover_headline": "Lower error than persistence. Two test subjects. No signal claimed.",
    },
)

FORBIDDEN_CLINICAL_CLAIMS = (
    "clinically accurate",
    "validated whole-body model",
    "predicts treatment response",
    "selects the best therapy",
    "digital twin already operational",
    "proven causal effect",
    "80% accuracy",
    "production ready",
)

STALE_EP06_PHRASES = (
    "IN RETROSPECTIVE TESTING",
    "FIRST LEARNED BASELINE STILL BEING DESIGNED",
    "PENDING EVIDENCE",
    "SCIENTIFIC PERFORMANCE BEING MEASURED",
    "IN_RETROSPECTIVE_TESTING",
)

# Invented metric patterns without evidence binding remain forbidden in uncontrolled text.
PLACEHOLDER_METRIC_PATTERNS = (
    r"\bMAE\s*[:=]\s*0\.12\b",
    r"\bRMSE\s*[:=]\s*0\.1\b",
)
