"""Disclosure register for the public roadmap series."""

from __future__ import annotations

from pathlib import Path

import yaml

from human_simulator.media.series.constants import EVIDENCE_DIR, SERIES_TITLE


def write_disclosure_register(root: Path, bindings: dict) -> Path:
    public = [row for row in bindings["bindings"] if row["disclosure_category"] == "PUBLIC_FACT"]
    controlled = [
        row for row in bindings["bindings"] if row["disclosure_category"] == "CONTROLLED_COMMERCIAL_REVEAL"
    ]
    doc = {
        "series_title": SERIES_TITLE,
        "publication_status": "PRIVATE_PUBLICATION_REVIEW_REQUIRED",
        "categories": {
            "PUBLIC_FACT": {
                "rule": "Show fully as aggregates or project statuses.",
                "items": [
                    {
                        "binding_id": row["binding_id"],
                        "displayed_public_value": row["displayed_public_value"],
                        "episode": row["episode"],
                    }
                    for row in public
                ],
            },
            "CONTROLLED_COMMERCIAL_REVEAL": {
                "rule": "Shown intentionally to demonstrate technical depth.",
                "disclosure_status": "OWNER_REVIEW_REQUIRED",
                "items": [
                    {
                        "binding_id": row["binding_id"],
                        "displayed_public_value": row["displayed_public_value"],
                        "disclosure_status": "OWNER_REVIEW_REQUIRED",
                    }
                    for row in controlled
                ],
            },
            "FORBIDDEN": {
                "rule": "Must not appear in videos, captions, fixtures, or the review ZIP.",
                "items": [
                    "real patient records",
                    "raw subject identifiers",
                    "opaque subject keys from the working database",
                    "names, phones, emails, addresses",
                    "real visit dates of an individual",
                    "individual laboratory sequences",
                    "document bodies",
                    "source table and column names",
                    "SQL",
                    "exact mappings",
                    "normalization formulas",
                    "feature engineering formulas",
                    "thresholds",
                    "model parameters and weights",
                    "Vault configuration and paths",
                    "tokens, credentials, DSN, .env",
                    "network topology",
                    "private keys",
                    "HMAC values",
                    "private runtime directories",
                    "row-level health records even if de-identified",
                ],
            },
        },
        "synthetic_elements": [
            {
                "id": "SYNTHETIC_COMPOSITE_TIMELINE",
                "episode": "Roadmap03",
                "rule": "Visual timeline is a composite of event-type counts, not a real subject.",
            },
            {
                "id": "SYNTHETIC_CONTROLLED_EVENT",
                "episode": "Roadmap04",
                "rule": "Fork event is a technical synthetic intervention. No biological effect claimed.",
            },
        ],
    }
    path = root / EVIDENCE_DIR / "disclosure-register.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
