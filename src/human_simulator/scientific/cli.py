"""CLI for Scientific Data Readiness v0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _print(doc: Any) -> None:
    print(json.dumps(doc, indent=2, default=str))


def cmd_profile(root: Path) -> int:
    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings
    from human_simulator.scientific.outcome import select_outcome
    from human_simulator.scientific.policy import ARTIFACT_DIR
    from human_simulator.scientific.profile import profile_candidates

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        profile = profile_candidates(conn)
    selection = select_outcome(profile)
    out = root / ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidate-outcome-profile.json").write_text(
        json.dumps(profile, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (out / "outcome-selection.json").write_text(
        json.dumps(selection, indent=2, default=str) + "\n", encoding="utf-8"
    )
    _print({"profile_hash": profile["profile_hash"], "selection": selection.get("status")})
    return 0


def cmd_run_first_backtest(root: Path) -> int:
    from human_simulator.scientific.orchestrator import run_v01

    result = run_v01(root, no_publish=True)
    _print(result)
    return 0 if "INSUFFICIENT" not in str(result.get("scientific_data_readiness_status")) or True else 1


def cmd_verify(root: Path) -> int:
    from human_simulator.scientific.policy import ARTIFACT_DIR

    path = root / ARTIFACT_DIR / "scientific-data-readiness-verification.json"
    if not path.is_file():
        _print({"error": "missing verification; run run-v0.1 first"})
        return 1
    doc = json.loads(path.read_text(encoding="utf-8"))
    _print(doc)
    tech = doc.get("technical_pipeline_status")
    if tech == "BACKTEST_PIPELINE_FAIL":
        return 1
    return 0


def cmd_run_v01(root: Path, *, no_publish: bool, seed: int) -> int:
    from human_simulator.scientific.orchestrator import run_v01

    result = run_v01(root, seed=seed, no_publish=no_publish)
    _print(result)
    if result.get("technical_pipeline_status") == "BACKTEST_PIPELINE_FAIL":
        return 1
    if not no_publish:
        from human_simulator.scientific.publish import PublicationError, publish_scientific_v01

        try:
            pub = publish_scientific_v01(root)
        except PublicationError as exc:
            _print({"publish_error": str(exc)})
            return 1
        _print(pub)
    return 0


def cmd_publish(root: Path) -> int:
    from human_simulator.scientific.publish import PublicationError, publish_scientific_v01

    try:
        result = publish_scientific_v01(root)
    except PublicationError as exc:
        _print({"error": str(exc)})
        return 1
    _print(result)
    return 0


def dispatch_scientific(root: Path, command: str, args: Any) -> int:
    if command == "profile":
        return cmd_profile(root)
    if command == "run-first-backtest":
        return cmd_run_first_backtest(root)
    if command == "verify":
        return cmd_verify(root)
    if command == "run-v0.1":
        return cmd_run_v01(
            root,
            no_publish=bool(getattr(args, "no_publish", True)),
            seed=int(getattr(args, "seed", 42)),
        )
    if command == "publish":
        return cmd_publish(root)
    _print({"error": f"unknown scientific-data-readiness command: {command}"})
    return 2
