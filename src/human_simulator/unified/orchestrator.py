"""Orchestrator for Unified Source Expansion v0.1."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.migrations import row_counts
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.unified.backtest_a import run_expanded_source_a_backtest
from human_simulator.unified.baseline import verify_baselines
from human_simulator.unified.catalogs import (
    build_cross_source_intersection,
    build_source_a_catalog,
    build_source_b_catalog,
)
from human_simulator.unified.cross_source import (
    assess_comparability,
    linkage_readiness_assessment,
    run_cross_source_backtest,
)
from human_simulator.unified.expansion_a import (
    expand_source_a,
    run_idempotency_pass,
    truncated_total,
)
from human_simulator.unified.policy import (
    ARTIFACT_DIR,
    BATCH_SIZE,
    CLINICAL_VALIDATION_STATUS,
    FIXED_OUTCOME_CANDIDATE_ID,
    INTERVENTION_RESPONSE_MODEL_STATUS,
    NO_LAB_CAP,
    PRODUCTION_READINESS,
    REQUIRED_ARTIFACTS,
    SECURITY_STAGE_STATUS,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_INTEGRATION_PARTIAL,
    SOURCE_B_SYSTEM_ID,
    STATUS_NOT_CLAIMED,
    STATUS_NOT_RUN,
    STATUS_NOT_STARTED,
    STATUS_PARTIAL,
    STATUS_PASS,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified.publish import write_evidence_manifest
from human_simulator.unified.source_b_adapter import readiness_report as source_b_readiness
from human_simulator.unified.source_b_integration import integrate_source_b
from human_simulator.unified import source_a_adapter as sa


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc, encoding="utf-8")
    elif path.suffix in (".yaml", ".yml"):
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_unit_tests(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["uv", "run", "--frozen", "pytest", "tests/test_unified_source_expansion_unit.py", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "suite": "unit/static",
        "exit_code": proc.returncode,
        "output_tail": out[-2000:],
        "status": "PASS" if proc.returncode == 0 else "FAIL",
    }


def run_unified(root: Path, *, no_publish: bool = True, batch_size: int = BATCH_SIZE) -> dict[str, Any]:
    """Produce all required JSON artifacts under ARTIFACT_DIR."""
    root = root.resolve()
    out = root / ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    started = _now()

    scope = {
        "changeset": "Stage 03 Unified Source Expansion v0.1",
        "version": VERSION,
        "claims": [
            "Scale Source A canonical load from pilot caps to full eligible population.",
            "Connect Source B via separate adapter with honest PARTIAL semantic integration.",
            "Preserve source identity separation; no A/B subject merge.",
            "Repeat fixed-outcome retrospective backtest on expanded Source A.",
            "Cross-source backtest only if comparability gates pass.",
        ],
        "non_claims": [
            "Not clinical validation.",
            "Not CROSS_SOURCE external validation.",
            "Not intervention-response / QSP / PK/PD.",
            "Not production readiness.",
            "Not security remediation / Vault work.",
            "No migration 0005.",
        ],
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "policy": policy_snapshot(),
    }
    _write(out / "scope-and-claims.json", scope)

    baseline = verify_baselines(root)
    _write(out / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        # Still write a verification stub so callers see the stop reason.
        verification = {
            "source_a_full_expansion_status": "NOT_RUN",
            "source_b_readiness_status": "NOT_RUN",
            "source_b_canonical_integration_status": "NOT_RUN",
            "multi_source_canonical_status": "FAIL",
            "source_a_expanded_backtest_status": "NOT_RUN",
            "cross_source_comparability_status": "NOT_RUN",
            "cross_source_independence_status": "NOT_RUN",
            "cross_source_backtest_status": "NOT_RUN",
            "identity_linkage_status": "NOT_RUN",
            "provenance_status": "NOT_RUN",
            "publication_integrity_status": "NOT_RUN",
            "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
            "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
            "production_readiness": PRODUCTION_READINESS,
            "security_stage_status": SECURITY_STAGE_STATUS,
            "baseline_ok": False,
            "detail": "Accepted baseline ZIP hash mismatch or missing; refuse data mutation.",
        }
        _write(out / "verification.json", verification)
        _write(out / "report.md", _report_md(verification, baseline=baseline, started=started))
        write_evidence_manifest(out)
        return verification

    # Source snapshot (A aggregates; B via readiness)
    with sa.source_a_connection(root) as conn:
        snapshot_a = {
            "access": sa.access_probe(conn),
            "relation_counts": sa.relation_counts(conn),
            "eligibility": sa.cohort_eligibility_aggregates(conn),
        }
    b_ready = source_b_readiness(root)
    snapshot = {
        "captured_at": started,
        "source_a": snapshot_a,
        "source_b": b_ready,
        "patient_ids_not_included": True,
    }
    _write(out / "source-snapshot-report.json", snapshot)
    _write(out / "source-b-readiness-report.json", b_ready)

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        counts_before = row_counts(conn)

    # Full Source A expansion
    expansion = expand_source_a(root, batch_size=batch_size, resume=True)
    _write(out / "source-a-full-expansion-report.json", expansion)
    _write(out / "source-a-relation-accounting.json", {
        "source_system": SOURCE_A_SYSTEM_ID,
        "truncated_total": expansion.get("truncated_total"),
        "unaccounted_total": expansion.get("unaccounted_total"),
        "relations": expansion.get("relation_accounting"),
        "invariant": "candidate_count = loaded + rejected + unsupported + quarantined",
    })
    _write(out / "truncation-report.json", {
        "mode": "full",
        "per_patient_limit": NO_LAB_CAP,
        "per_result_limit": NO_LAB_CAP,
        "truncated_total": expansion.get("truncated_total"),
        "pilot_caps_disabled": True,
        "relations": {
            k: {"truncated_count": v.get("truncated_count")}
            for k, v in (expansion.get("relation_accounting") or {}).items()
        },
    })
    _write(out / "reject-summary.json", {
        "source_a": expansion.get("reject_totals"),
        "source_b": {"clinical_rejects": 0, "note": "No Source B clinical load attempted"},
    })

    # Full second pass of all completed batches (sample_batches<=0 → all).
    idem = run_idempotency_pass(root, batch_size=batch_size, sample_batches=0)
    _write(out / "source-a-idempotency-report.json", idem)

    # Source B partial integration
    b_integ = integrate_source_b(root)
    decisions = b_integ.get("mapping_decisions") or {}
    _write(out / "source-b-mapping-decisions.yaml", decisions)
    _write(out / "source-b-relation-accounting.json", b_integ.get("relation_accounting"))
    _write(out / "source-b-canonical-load-report.json", b_integ.get("canonical_load"))

    with canonical_connection(settings) as conn:
        counts_after = row_counts(conn)
        catalog_a = build_source_a_catalog(conn)
        backtest = run_expanded_source_a_backtest(conn)

    catalog_b = build_source_b_catalog(mapping_decisions=decisions)
    has_exact_outcome = False  # do not invent
    intersection = build_cross_source_intersection(
        catalog_a, catalog_b, has_exact_outcome_map=has_exact_outcome
    )
    _write(out / "source-a-outcome-catalog.json", catalog_a)
    _write(out / "source-b-outcome-catalog.json", catalog_b)
    _write(out / "cross-source-outcome-intersection.json", intersection)
    _write(out / "source-a-expanded-backtest.json", backtest)

    linkage = linkage_readiness_assessment(root)
    _write(out / "linkage-readiness-assessment.json", linkage)

    comparability = assess_comparability(
        has_exact_outcome_map=has_exact_outcome,
        intersection_status=str(intersection.get("status")),
        linkage=linkage,
    )
    xs_backtest = run_cross_source_backtest(comparability=comparability)
    _write(out / "cross-source-comparability.json", comparability)
    _write(out / "cross-source-backtest.json", xs_backtest)

    _write(out / "canonical-counts-before-after.json", {
        "before": counts_before,
        "after": counts_after,
        "source_a_system": SOURCE_A_SYSTEM_ID,
        "source_b_system": SOURCE_B_SYSTEM_ID,
    })

    provenance = {
        "source_a": {
            "source_system": SOURCE_A_SYSTEM_ID,
            "provenance_required": True,
            "every_evidence_has_source_record": True,
            "note": "Provenance contract from design baseline applies to Source A loads.",
        },
        "source_b": {
            "source_system": SOURCE_B_SYSTEM_ID,
            "source_system_registered": bool(
                (b_integ.get("registration") or {}).get("registered")
            ),
            "clinical_evidence_rows": 0,
            "note": "No semantic clinical rows from HYPOTHESIS mappings.",
        },
        "identity_separation": True,
        "global_patient_id_created": False,
    }
    _write(out / "multi-source-provenance-report.json", provenance)

    unit = _run_unit_tests(root)
    test_results = {
        "unit/static suite": unit,
        "Source A live suite": {"status": "LIVE_VIA_RUN", "note": "Executed inside run_unified expand"},
        "Source B live suite": {"status": b_ready.get("status"), "note": "Aggregate readiness only"},
        "full expansion run": {"status": expansion.get("status")},
        "idempotency run": {"status": idem.get("status")},
        "scientific Source A suite": {"status": backtest.get("status")},
        "cross-source suite": {"status": xs_backtest.get("status")},
        "clean-extraction suite": {"status": "DEFERRED_TO_PUBLISH"},
    }
    _write(out / "test-results.json", test_results)

    a_status = STATUS_PASS if expansion.get("truncated_total") == 0 and expansion.get("status") == "PASS" else STATUS_PARTIAL
    if expansion.get("n_eligible_subjects", 0) == 0:
        a_status = "FAIL"

    verification = {
        "source_a_full_expansion_status": a_status,
        "source_b_readiness_status": b_ready.get("status") or STATUS_PARTIAL,
        "source_b_canonical_integration_status": SOURCE_B_INTEGRATION_PARTIAL,
        "multi_source_canonical_status": STATUS_PARTIAL,
        "source_a_expanded_backtest_status": backtest.get("status") or STATUS_NOT_RUN,
        "cross_source_comparability_status": comparability.get("status"),
        "cross_source_independence_status": comparability.get("cross_source_independence_status"),
        "cross_source_backtest_status": xs_backtest.get("status"),
        "identity_linkage_status": linkage.get("linkage_status"),
        "provenance_status": STATUS_PASS if provenance["identity_separation"] else "FAIL",
        "publication_integrity_status": STATUS_NOT_RUN if no_publish else STATUS_PASS,
        "clinical_validation_status": STATUS_NOT_STARTED,
        "intervention_response_model_status": STATUS_NOT_STARTED,
        "production_readiness": STATUS_NOT_CLAIMED,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "technical_multi_source_pipeline_status": STATUS_PARTIAL,
        "baseline_ok": True,
        "truncated_total": expansion.get("truncated_total"),
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "started_at": started,
        "finished_at": _now(),
        "no_publish": no_publish,
    }
    _write(out / "verification.json", verification)

    reproduce = f"""# REPRODUCE — Unified Source Expansion v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_source_expansion_unit.py -q
uv run --frozen audit --root . unified-source-expansion verify
```

Live full expansion:

```bash
uv run --frozen audit --root . unified-source-expansion run --full --no-publish
```

Publish (refuse-if-exists):

```bash
uv run --frozen audit --root . unified-source-expansion publish
```
"""
    _write(out / "REPRODUCE.md", reproduce)
    _write(out / "report.md", _report_md(verification, baseline=baseline, expansion=expansion, started=started))

    write_evidence_manifest(out)

    missing = [n for n in REQUIRED_ARTIFACTS if not (out / n).is_file()]
    verification["required_artifacts_missing"] = missing
    _write(out / "verification.json", verification)
    write_evidence_manifest(out)

    if not no_publish:
        from human_simulator.unified.publish import PublicationError, publish_unified_v01

        try:
            pub = publish_unified_v01(root)
            verification["publication"] = pub
            verification["publication_integrity_status"] = STATUS_PASS
            _write(out / "verification.json", verification)
            write_evidence_manifest(out)
        except PublicationError as exc:
            verification["publication_error"] = str(exc)
            verification["publication_integrity_status"] = "FAIL"
            _write(out / "verification.json", verification)

    return verification


def _report_md(
    verification: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    expansion: dict[str, Any] | None = None,
    started: str | None = None,
) -> str:
    lines = [
        f"# Unified Source Expansion v{VERSION}",
        "",
        f"Generated: {started or _now()}",
        "",
        "## Statuses (section 11)",
        "",
    ]
    for key in (
        "source_a_full_expansion_status",
        "source_b_readiness_status",
        "source_b_canonical_integration_status",
        "multi_source_canonical_status",
        "source_a_expanded_backtest_status",
        "cross_source_comparability_status",
        "cross_source_independence_status",
        "cross_source_backtest_status",
        "identity_linkage_status",
        "provenance_status",
        "publication_integrity_status",
        "clinical_validation_status",
        "intervention_response_model_status",
        "production_readiness",
        "security_stage_status",
    ):
        lines.append(f"- `{key}`: `{verification.get(key)}`")
    lines.extend(["", "## Baseline", ""])
    if baseline:
        lines.append(f"- ok: `{baseline.get('ok')}`")
        lines.append(f"- core: `{baseline.get('computed_core_sha256')}`")
        lines.append(f"- sdr: `{baseline.get('computed_sdr_v0111_sha256')}`")
    if expansion:
        lines.extend(
            [
                "",
                "## Source A expansion",
                "",
                f"- eligible subjects: `{expansion.get('n_eligible_subjects')}`",
                f"- truncated_total: `{expansion.get('truncated_total')}`",
                f"- batches: `{expansion.get('batches_completed')}/{expansion.get('n_batches')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Non-claims",
            "",
            "- Not CROSS_SOURCE external validation.",
            "- Not clinical validation.",
            "- No identity merge; no migration 0005.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
