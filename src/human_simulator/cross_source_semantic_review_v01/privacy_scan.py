"""Direct-identifier scan for public semantic-review artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.policy import VERSION

_DIRECT_ID_PATTERNS = [
    (r"\bemail\b", "email_field"),
    (r"\bphone\b", "phone_field"),
    (r"\bpassport\b", "passport_field"),
    (r"\bssn\b", "ssn_field"),
    (r"full_name", "full_name_field"),
    (r"street_address", "address_field"),
    (r"date_of_birth", "dob_field"),
    (r"UHBSE_RESEARCH_HMAC_KEY", "hmac_env"),
    (r"uhbse-research-hmac\.key", "hmac_file"),
]


def scan_public_artifacts(art: Path) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    identity_keys = (
        "opaque_subject_key",
        "source_subject_id",
        "patient_id",
        "research_subject_id",
        "component_id",
        "observation_id",
        "pair_id",
    )
    for path in sorted(art.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {
            ".json",
            ".md",
            ".txt",
            ".yaml",
            ".html",
            ".csv",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(art).as_posix()
        for key in identity_keys:
            if re.search(rf'"{re.escape(key)}"\s*:', text):
                hits.append({"file": rel, "kind": "identity_key", "key": key})
        for pat, kind in _DIRECT_ID_PATTERNS:
            if re.search(pat, text, flags=re.IGNORECASE):
                hits.append({"file": rel, "kind": kind, "pattern": pat})
    return {
        "version": VERSION,
        "ok": len(hits) == 0,
        "n_hits": len(hits),
        "hits": hits[:40],
        "DIRECT_IDENTIFIER_SCAN_STATUS": "PASS" if not hits else "FAIL",
        "PUBLIC_DATA_MINIMIZATION_STATUS": (
            "PASS_AGGREGATE_ONLY" if not hits else "FAIL"
        ),
    }
