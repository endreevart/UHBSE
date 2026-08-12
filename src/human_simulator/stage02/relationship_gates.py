"""Precondition gates for assess-source-relationship."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from human_simulator.stage01.settings import MG_AUDIT_USER, MgAuditSettings
from human_simulator.stage02.compare_source_audits import GateResult, _run_gates
from human_simulator.stage02.settings import KGZ_AUDIT_USER, KgzRestoreSettings

COMPARE_REPORT = "compare-verification-report.json"
LIVE_AUDIT_USER_A = MG_AUDIT_USER
LIVE_AUDIT_USER_B = KGZ_AUDIT_USER


class AssessSourceRelationshipError(RuntimeError):
    """Raised when relationship assessment prerequisites fail."""


@dataclass(frozen=True)
class GateContext:
    gates: list[GateResult]
    compare_report: dict[str, Any] | None


def run_relationship_gates(repo_root: Path) -> GateContext:
    root = repo_root.resolve()
    stage01_dir = root / "artifacts" / "stage-01"
    stage02_dir = root / "artifacts" / "stage-02"

    gates = list(_run_gates(stage01_dir, stage02_dir))

    compare_path = stage02_dir / COMPARE_REPORT
    compare_report: dict[str, Any] | None = None
    if compare_path.exists():
        compare_report = json.loads(compare_path.read_text(encoding="utf-8"))
    gates.append(
        GateResult(
            "compare_verification_report",
            "PASS" if compare_report and compare_report.get("status") == "PASS" else "FAIL",
            f"status={compare_report.get('status') if compare_report else 'missing'}",
        )
    )

    mg = MgAuditSettings.from_repo(root)
    kgz = KgzRestoreSettings.from_repo(root)
    mg_engine = create_engine(mg.audit_sqlalchemy_url)
    kgz_engine = create_engine(kgz.audit_sqlalchemy_url)
    try:
        gates.extend(_runtime_readonly_gates(mg_engine, kgz_engine))
    finally:
        mg_engine.dispose()
        kgz_engine.dispose()

    failed = [gate for gate in gates if gate.status != "PASS"]
    if failed:
        raise AssessSourceRelationshipError(
            "assess-source-relationship prerequisites failed: "
            + "; ".join(f"{gate.name}={gate.detail}" for gate in failed)
        )

    return GateContext(gates=gates, compare_report=compare_report)


def _runtime_readonly_gates(mg_engine: Engine, kgz_engine: Engine) -> list[GateResult]:
    results: list[GateResult] = []
    for label, engine, expected_user in (
        ("source_a_runtime_user", mg_engine, LIVE_AUDIT_USER_A),
        ("source_b_runtime_user", kgz_engine, LIVE_AUDIT_USER_B),
    ):
        current_user = engine.connect().execute(text("SELECT current_user")).scalar_one()
        results.append(
            GateResult(
                label,
                "PASS" if current_user == expected_user else "FAIL",
                f"current_user={current_user!r}, expected {expected_user!r}",
            )
        )
    return results
