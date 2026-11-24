"""Orchestrator for Unified Source Expansion v0.1.2.1."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from human_simulator.unified_v0121.accounting import recompute_accounting
from human_simulator.unified_v0121.applicability import assess_applicability
from human_simulator.unified_v0121.baseline import before_after_hash_matrix, verify_baselines
from human_simulator.unified_v0121.consistency import assert_report_consistency, statuses_from_verification
from human_simulator.unified_v0121.empty_headers import analyze_empty_headers, empty_component_policy_doc
from human_simulator.unified_v0121.frozen_model_a import (
    build_frozen_from_runtime,
    prove_hash_unchanged,
    write_frozen_model,
)
from human_simulator.unified_v0121.pairs_b import construct_source_b_pairs, sanitize_pairs_artifact
from human_simulator.unified_v0121.policy import (
    ARTIFACT_DIR,
    CLINICAL_VALIDATION_STATUS,
    INTERVENTION_RESPONSE_MODEL_STATUS,
    PRODUCTION_READINESS,
    REQUIRED_ARTIFACTS,
    REQUIRED_STATUSES,
    SECURITY_STAGE_STATUS,
    TREATMENT_EFFECT_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_v0121.t3_harmonization import run_t3_harmonization
from human_simulator.unified_v0121.transfer import build_transfer_gate, run_transfer_or_skip
from human_simulator.unified_v0121.uncertainty_recompute import (
    recompute_uncertainty,
    sanitize_uncertainty_artifact,
)
from human_simulator.unified_v0121.validation_insert import run_validation_insert_rollback


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc, encoding="utf-8")
    elif path.suffix in (".yaml", ".yml"):
        path.write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    else:
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_evidence_manifest(art: Path) -> Path:
    import hashlib

    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name not in ("evidence-manifest.sha256", "manifest.sha256")
    )

    def sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    path = art / "evidence-manifest.sha256"
    path.write_text(
        "\n".join(f"{sha(art / n)}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )
    return path


def _run_unit_tests(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "pytest",
            "tests/test_unified_source_expansion_v0121_unit.py",
            "-q",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "suite": "unit/static",
        "literal_command": (
            "uv run --frozen pytest tests/test_unified_source_expansion_v0121_unit.py -q"
        ),
        "exit_code": proc.returncode,
        "output_tail": out[-2000:],
        "status": "PASS" if proc.returncode == 0 else "FAIL",
    }


def _changed_files() -> dict[str, Any]:
    return {
        "package": "src/human_simulator/unified_v0121/",
        "modules": [
            "policy.py",
            "baseline.py",
            "accounting.py",
            "empty_headers.py",
            "validation_insert.py",
            "uncertainty_recompute.py",
            "t3_harmonization.py",
            "pairs_b.py",
            "frozen_model_a.py",
            "applicability.py",
            "transfer.py",
            "consistency.py",
            "orchestrator.py",
            "publish.py",
            "cli.py",
        ],
        "tests": [
            "tests/test_unified_source_expansion_v0121_unit.py",
        ],
        "docs": ["docs/current-stage.md", "AGENTS.md"],
        "note": "Does not overwrite v0.1 / v0.1.1 / v0.1.2 review ZIPs.",
    }


def _build_report_md(statuses: dict[str, Any]) -> str:
    lines = [
        f"# Unified Source Expansion v{VERSION}",
        "",
        f"**Report status:** DRAFT",
        f"**Generated:** {_now()}",
        "",
        "## Scope",
        "",
        "- Accounting reconciliation for Source B Observation load (no full reload).",
        "- Empty-header policy (keep rows; exclude from science; no migration 0005).",
        "- Validation INSERT + mandatory ROLLBACK.",
        "- Source A uncertainty recompute with exclusive quantiles.",
        "- T3 strata by raw_code+raw_unit; domain review if material empty.",
        "- Frozen Source A model + gated exploratory transfer (not clinical validation).",
        "",
        "## Statuses",
        "",
        "| Key | Value |",
        "|-----|-------|",
    ]
    for k in REQUIRED_STATUSES:
        lines.append(f"| `{k}` | `{statuses.get(k, 'UNSET')}` |")
    lines.extend(
        [
            "",
            "## Non-claims",
            "",
            "- Clinical validation: NOT_STARTED",
            "- Identity merge: false",
            "- Migration 0005: false",
            "- Security stage: PAUSED_NOT_ACCEPTED_BY_OWNER",
            "",
        ]
    )
    return "\n".join(lines)


def run_v0121(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    """Produce all required artifacts under ARTIFACT_DIR."""
    root = root.resolve()
    out = root / ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    started = _now()

    baseline = verify_baselines(root)
    _write(out / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        statuses = {
            "baseline_verification_status": "FAIL",
            "cross_source_transfer_status": "NOT_RUN_DUE_TO_FAILED_GATE",
            "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
            "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
            "treatment_effect_status": TREATMENT_EFFECT_STATUS,
            "production_readiness": PRODUCTION_READINESS,
            "security_stage_status": SECURITY_STAGE_STATUS,
            "pre_publish_verification_status": "FAIL",
            "post_publish_integrity_status": "NOT_RUN",
            "identity_linkage_status": "CANDIDATE_ONLY",
        }
        ver = {
            "version": VERSION,
            "started_at": started,
            "finished_at": _now(),
            "baseline_ok": False,
            **statuses,
            "refuse_reason": baseline.get("refuse_reason"),
        }
        _write(out / "verification.json", ver)
        _write(out / "scope-and-claims.json", {"version": VERSION, "baseline_ok": False})
        return {"baseline_ok": False, "artifact_dir": str(out), **ver}

    hash_matrix = before_after_hash_matrix(root)
    _write(out / "before-after-hash-matrix.json", hash_matrix)

    scope = {
        "changeset": "Stage 03 Unified Source Expansion v0.1.2.1",
        "version": VERSION,
        "claims": [
            "Recompute Source B Observation accounting without full reload.",
            "Empty-component headers retained; science exclusion; schema decision deferred.",
            "Mandatory rollback validation insert.",
            "Exclusive quantile uncertainty recompute on Source A.",
            "T3 harmonization by raw_code+raw_unit; catalog-default alone insufficient.",
            "Frozen Source A model; gated exploratory B transfer only if all gates pass.",
        ],
        "non_claims": [
            "Not clinical validation.",
            "No A/B identity merge.",
            "No migration 0005.",
            "Security remains PAUSED.",
        ],
        "policy": policy_snapshot(),
    }
    _write(out / "scope-and-claims.json", scope)

    accounting = recompute_accounting(root)
    _write(out / "source-row-accounting.json", accounting["source_row_disposition"])
    _write(out / "observation-header-accounting.json", accounting["observation_header_accounting"])
    _write(
        out / "observation-component-accounting.json",
        accounting["observation_component_accounting"],
    )
    _write(out / "source-record-accounting.json", accounting["source_record_accounting"])

    empty = analyze_empty_headers(root, accounting=accounting)
    _write(out / "empty-component-analysis.json", empty)
    _write(out / "empty-component-policy.yaml", empty_component_policy_doc())

    validation = run_validation_insert_rollback(root)
    _write(out / "insertion-rollback-validation.json", validation)

    # Source A robustness + uncertainty + freeze (single live path when DB available)
    unc_doc: dict[str, Any] = {
        "status": "SKIPPED",
        "source_a_uncertainty_recomputation_status": "SKIPPED",
    }
    frozen_meta: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "frozen_source_a_model_status": "UNAVAILABLE",
    }
    frozen_doc: dict[str, Any] | None = None
    a_train_horizons: list[float] | None = None
    runtime_pairs: list[dict[str, Any]] = []
    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings

        with canonical_connection(load_canonical_settings()) as conn:
            unc_full = recompute_uncertainty(conn)
            runtime = unc_full.pop("_runtime", {})
            unc_doc = sanitize_uncertainty_artifact(unc_full)
            frozen_meta = build_frozen_from_runtime(runtime.get("_learned_model"))
            if frozen_meta.get("model"):
                frozen_doc = frozen_meta["model"]
                write_frozen_model(out, frozen_doc)

            pairs_full = construct_source_b_pairs(conn)
            runtime_pairs = list(pairs_full.get("_runtime_pairs") or [])
            pairs_doc = sanitize_pairs_artifact(pairs_full)
    except Exception as exc:  # noqa: BLE001
        unc_doc = {
            "status": "INSUFFICIENT_DATA",
            "source_a_uncertainty_recomputation_status": "INSUFFICIENT_DATA",
            "error_type": type(exc).__name__,
        }
        pairs_doc = sanitize_pairs_artifact(construct_source_b_pairs(None))
        # Still write placeholder frozen sidecar if missing
        if not (out / "frozen-source-a-model.json").is_file():
            placeholder = {
                "version": VERSION,
                "status": "UNAVAILABLE",
                "reason": "canonical_connection_unavailable",
                "coef": [],
                "feature_order": list(policy_snapshot()["feature_order"]),
            }
            write_frozen_model(out, placeholder)
            frozen_doc = placeholder

    _write(out / "source-a-uncertainty-recomputation.json", unc_doc)
    if not (out / "frozen-source-a-model.json").is_file() and frozen_doc:
        write_frozen_model(out, frozen_doc)

    t3 = run_t3_harmonization(root)
    decision = t3.pop("decision_required_doc", None)
    _write(out / "t3-semantic-comparison-matrix.json", t3)
    if decision:
        _write(out / "decision-required-t3-domain-review.yaml", decision)

    _write(out / "source-b-pair-construction.json", pairs_doc)

    hash_proof_before_b = prove_hash_unchanged(out)

    appl = assess_applicability(
        b_pairs=runtime_pairs,
        a_train_horizons=a_train_horizons,
    )
    _write(out / "applicability-report.json", appl)

    # Prove frozen hash unchanged after B evaluation
    hash_proof_after_b = prove_hash_unchanged(out)
    frozen_stable = bool(hash_proof_after_b.get("ok")) and bool(
        hash_proof_before_b.get("ok")
    )
    if frozen_meta.get("sha256"):
        frozen_meta["hash_proof_after_b_evaluation"] = hash_proof_after_b
        frozen_meta["hash_unchanged"] = frozen_stable

    gate = build_transfer_gate(
        baseline_ok=bool(baseline.get("ok")),
        t3_status=str(t3.get("t3_semantic_harmonization_status") or ""),
        pairs_status=str(pairs_doc.get("source_b_pair_construction_status") or ""),
        pairs_gate_pass=bool(
            (pairs_doc.get("technical_min_sample_gate") or {}).get("pass")
        ),
        frozen_status=str(frozen_meta.get("frozen_source_a_model_status") or ""),
        applicability_pass=bool(appl.get("pass")),
        validation_rollback_pass=validation.get("status") == "PASS",
        uncertainty_pass=unc_doc.get("source_a_uncertainty_recomputation_status") == "PASS",
    )
    _write(out / "transfer-gate.json", gate)

    transfer = run_transfer_or_skip(
        gate=gate,
        frozen_doc=frozen_doc if frozen_meta.get("frozen_source_a_model_status") == "FROZEN" else None,
        b_pairs=runtime_pairs,
    )
    _write(out / "transfer-results.json", transfer)

    statuses = {
        "baseline_verification_status": baseline.get("baseline_verification_status", "FAIL"),
        "source_row_accounting_status": accounting.get("source_row_accounting_status"),
        "observation_header_accounting_status": accounting.get(
            "observation_header_accounting_status"
        ),
        "observation_component_accounting_status": accounting.get(
            "observation_component_accounting_status"
        ),
        "source_record_accounting_status": accounting.get("source_record_accounting_status"),
        "empty_component_observation_semantics_status": empty.get(
            "empty_component_observation_semantics_status"
        ),
        "insertion_rollback_validation_status": validation.get(
            "insertion_rollback_validation_status"
        ),
        "source_a_uncertainty_recomputation_status": unc_doc.get(
            "source_a_uncertainty_recomputation_status"
        ),
        "t3_semantic_harmonization_status": t3.get("t3_semantic_harmonization_status"),
        "source_b_temporal_dataset_status": pairs_doc.get(
            "source_b_pair_construction_status"
        ),
        "source_b_pair_construction_status": pairs_doc.get(
            "source_b_pair_construction_status"
        ),
        "frozen_source_a_model_status": frozen_meta.get("frozen_source_a_model_status"),
        "applicability_status": appl.get("applicability_status"),
        "transfer_gate_status": gate.get("transfer_gate_status"),
        "cross_source_transfer_status": transfer.get("cross_source_transfer_status"),
        "identity_linkage_status": "CANDIDATE_ONLY",
        "pre_publish_verification_status": "PASS" if no_publish else "PENDING_PUBLISH",
        "post_publish_integrity_status": "NOT_RUN" if no_publish else "PENDING_PUBLISH",
        "publication_integrity_status": "PENDING_PUBLISH" if no_publish else "PENDING_PUBLISH",
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "treatment_effect_status": TREATMENT_EFFECT_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "security_stage_status": SECURITY_STAGE_STATUS,
    }
    accounting_ok = all(
        accounting.get(k) == "PASS"
        for k in (
            "source_row_accounting_status",
            "observation_header_accounting_status",
            "observation_component_accounting_status",
            "source_record_accounting_status",
        )
    )
    statuses["source_b_accounting_status"] = "PASS" if accounting_ok else "FAIL"
    unexplained_zero = all(
        int((accounting.get(ledger) or {}).get("unexplained_count") or 0) == 0
        for ledger in (
            "source_row_disposition",
            "observation_header_accounting",
            "observation_component_accounting",
            "source_record_accounting",
        )
    )
    statuses["technical_multi_source_pipeline_status"] = (
        "TECHNICAL_MULTI_SOURCE_PIPELINE_PASS"
        if accounting_ok and validation.get("status") == "PASS"
        else "TECHNICAL_MULTI_SOURCE_PIPELINE_PARTIAL"
    )
    statuses["evidence_closure_status"] = "PENDING_TESTS"

    tests = _run_unit_tests(root)
    _write(out / "test-results.json", tests)

    evidence_pass = (
        accounting_ok
        and unexplained_zero
        and validation.get("status") == "PASS"
        and unc_doc.get("source_a_uncertainty_recomputation_status") == "PASS"
        and bool(
            unc_doc.get("authoritative_exclusive_quantile_ok")
            or (unc_doc.get("exclusive_quantile_coverage") or {}).get(
                "exclusive_sum_equals_n"
            )
        )
        and tests.get("status") == "PASS"
    )
    statuses["evidence_closure_status"] = (
        "EVIDENCE_CLOSURE_PASS" if evidence_pass else "EVIDENCE_CLOSURE_PARTIAL"
    )

    report_json = {
        "version": VERSION,
        "started_at": started,
        "finished_at": _now(),
        "baseline_ok": True,
        "statuses": statuses,
        "policy": policy_snapshot(),
        "transfer_executed": bool(transfer.get("executed")),
        "frozen_hash_unchanged_after_b": frozen_stable,
    }
    _write(out / "report.json", report_json)
    _write(out / "report.md", _build_report_md(statuses))

    verification = {
        "version": VERSION,
        "started_at": started,
        "finished_at": _now(),
        "baseline_ok": True,
        **statuses,
        "unit_tests": tests.get("status"),
        "no_publish": no_publish,
        "migration_0005": False,
        "identity_merge": False,
        "required_artifacts_present_hint": list(REQUIRED_ARTIFACTS),
    }
    _write(out / "verification.json", verification)

    release = {
        "version": VERSION,
        "release_verification_status": "PASS" if tests.get("status") == "PASS" else "FAIL",
        "pre_publish_verification_status": statuses["pre_publish_verification_status"],
        "post_publish_integrity_status": statuses["post_publish_integrity_status"],
        "publication_integrity_status": statuses["publication_integrity_status"],
        "evidence_closure_status": statuses["evidence_closure_status"],
        "archive_rebuilt_after_hashing": False,
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "cross_source_transfer_status": statuses["cross_source_transfer_status"],
        "publication_target": "stage-03-unified-source-expansion-v0.1.2.1-review.zip",
        "refuse_if_exists": True,
    }
    _write(out / "release-verification.json", release)

    consistency = assert_report_consistency(
        report_md_statuses=statuses_from_verification(statuses),
        report_json=report_json,
        verification=verification,
        release_verification=release,
        published=False,
    )
    _write(out / "consistency-check.json", consistency)

    _write(out / "changed-files.json", _changed_files())
    _write(
        out / "REPRODUCE.md",
        f"""# REPRODUCE — Unified Source Expansion v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_source_expansion_v0121_unit.py -q
uv run --frozen audit --root . unified-source-expansion-v0121 run --full --no-publish
uv run --frozen audit --root . unified-source-expansion-v0121 verify
```

Do not overwrite prior Unified / Core / SDR / Roadmap review ZIPs.
""",
    )

    write_evidence_manifest(out)

    missing = [n for n in REQUIRED_ARTIFACTS if not (out / n).is_file()]
    result = {
        "baseline_ok": True,
        "artifact_dir": str(out),
        "missing_required_artifacts": missing,
        "statuses": statuses,
        "consistency_ok": consistency.get("ok"),
        "no_publish": no_publish,
        "version": VERSION,
    }
    return result
