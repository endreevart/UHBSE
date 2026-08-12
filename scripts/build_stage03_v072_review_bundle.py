#!/usr/bin/env python3
"""Build stage-03-design-v0.7.2-review.zip for external verification."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from human_simulator.stage03.review_bundle import BUNDLE_ZIP_NAME, build_stage03_review_bundle


def main() -> None:
    generated_at = datetime.now(tz=UTC).isoformat()
    build_stage03_review_bundle(ROOT, generated_at=generated_at)
    out_zip = ROOT / "artifacts" / "external-review" / BUNDLE_ZIP_NAME
    print(f"Created {out_zip} ({out_zip.stat().st_size} bytes)")
    print(f"REVIEW_INDEX Generated: {generated_at}")


if __name__ == "__main__":
    main()
