"""Run the public roadmap series through the existing Remotion factory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.media.series.baseline import verify_core_baseline
from human_simulator.media.series.bindings import build_bindings, write_bindings
from human_simulator.media.series.copy import write_copy
from human_simulator.media.series.disclosure import write_disclosure_register
from human_simulator.media.series.fixture import write_fixture
from human_simulator.media.series.publish import publish_review_zip
from human_simulator.media.series.render import render_series
from human_simulator.media.series.reports import write_reports, write_storyboard
from human_simulator.media.series.verify import verify_series


def run_series(root: Path, *, stills_only: bool = False, skip_render: bool = False, skip_publish: bool = False) -> dict[str, Any]:
    baseline = verify_core_baseline(root)
    bindings = build_bindings(root)
    bindings_path = write_bindings(root)
    fixture_path = write_fixture(root, bindings)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    write_disclosure_register(root, bindings)
    write_storyboard(root, fixture)
    write_copy(root, fixture)
    render: dict[str, Any] = {"skipped": True}
    if not skip_render:
        render = render_series(root, fixture, stills_only=stills_only)
    verification = verify_series(
        root,
        bindings=bindings,
        fixture=fixture,
        baseline=baseline,
        require_media=not skip_render and not stills_only,
    )
    write_reports(
        root,
        bindings=bindings,
        fixture=fixture,
        baseline=baseline,
        render=render,
        verification=verification,
    )
    verification = verify_series(
        root,
        bindings=bindings,
        fixture=fixture,
        baseline=baseline,
        require_media=not skip_render and not stills_only,
    )
    attestation = None
    if not skip_publish:
        attestation = publish_review_zip(root, baseline=baseline, verification=verification)
    return {
        "baseline": baseline,
        "bindings": str(bindings_path),
        "fixture": str(fixture_path),
        "render": render,
        "verification": verification,
        "attestation": attestation,
        "publication_status": "PRIVATE_PUBLICATION_REVIEW_REQUIRED",
    }
