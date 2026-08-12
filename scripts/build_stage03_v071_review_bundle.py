#!/usr/bin/env python3
"""Build stage-03-design-v0.7.1-review.zip for external verification."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from human_simulator.stage03.review_bundle import BUNDLE_ZIP_NAME, build_stage03_review_bundle


def main() -> None:
    bundle_generated_at = build_stage03_review_bundle(ROOT)
    out_zip = ROOT / "artifacts" / "external-review" / BUNDLE_ZIP_NAME
    print(f"Created {out_zip} ({out_zip.stat().st_size} bytes)")
    print(f"REVIEW_INDEX Generated: {bundle_generated_at}")


if __name__ == "__main__":
    main()
