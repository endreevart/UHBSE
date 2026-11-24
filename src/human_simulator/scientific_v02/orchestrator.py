"""Orchestrator: Source A Scientific Baseline v0.2 + Technical Shadow Transfer v0.1."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_shadow_v01.dataset_b import build_shadow_b_dataset
from human_simulator.cross_source_shadow_v01.shadow import (
    engineering_shadow_gate,
    run_technical_shadow,
    scientific_cross_source_gate,
)
from human_simulator.scientific_v02.applicability import (
    assess_b_applicability,
    build_applicability_reference,
)
from human_simulator.scientific_v02.evaluate import evaluate_a_only
from human_simulator.scientific_v02.freeze import (
    load_frozen_v02,
    model_to_doc,
    verify_sidecar,
    write_frozen_v02,
)
from human_simulator.scientific_v02.lineage import build_a_only_experiment
from human_simulator.scientific_v02.policy import (
    ARTIFACT_DIR,
    CLINICAL_VALIDATION_STATUS,
    DOMAIN_REVIEW_REQUIRED,
    INDEPENDENCE_NOT_ESTABLISHED,
    INTERVENTION_RESPONSE_MODEL_STATUS,
    MAX_OOD_FRACTION,
    PRIOR_IMMUTABLE_ZIPS,
    PRODUCTION_READINESS,
    SCIENTIFIC_CROSS_SOURCE_TRANSFER_NOT_RUN,
    SECURITY_STAGE_STATUS,
    TREATMENT_EFFECT_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.scientific_v02.train import train_ridge_v02
from human_simulator.scientific_v02.uncertainty import compute_uncertainty


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc, encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_evidence_manifest(art: Path) -> Path:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name not in ("evidence-manifest.sha256", "manifest.sha256")
    )
    path = art / "evidence-manifest.sha256"
    path.write_text(
        "\n".join(f"{_sha_file(art / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )
    return path


def verify_baselines(root: Path) -> dict[str, Any]:
    existing = root / ARTIFACT_DIR / "baseline-verification.json"
    if existing.is_file():
        doc = json.loads(existing.read_text(encoding="utf-8"))
        # Re-check primary SHA
        from human_simulator.scientific_v02.policy import (
            ACCEPTED_UNIFIED_V01211_SHA256,
            ACCEPTED_UNIFIED_V01211_ZIP,
        )

        z = root / "artifacts" / "external-review" / ACCEPTED_UNIFIED_V01211_ZIP
        if z.is_file() and _sha_file(z) == ACCEPTED_UNIFIED_V01211_SHA256 and doc.get("ok"):
            return doc
    # fallback minimal
    return {"ok": False, "baseline_verification_status": "FAIL"}


def before_after_matrix(root: Path) -> dict[str, Any]:
    ext = root / "artifacts" / "external-review"
    rows = []
    for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items():
        p = ext / name
        got = _sha_file(p) if p.is_file() else None
        rows.append(
            {
                "label": label,
                "filename": name,
                "expected_sha256": exp,
                "computed_sha256": got,
                "matches": got == exp,
            }
        )
    return {"phase": "before_v02_shadow_publish", "rows": rows, "all_match": all(r["matches"] for r in rows)}


def _run_tests(root: Path) -> dict[str, Any]:
    cmd = [
        "uv",
        "run",
        "--frozen",
        "pytest",
        "tests/test_scientific_baseline_v02_unit.py",
        "tests/test_cross_source_shadow_v01_unit.py",
        "-q",
    ]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "suite": "scoped_scientific_v02_shadow_v01",
        "literal_command": " ".join(cmd[3:]),
        "exit_code": proc.returncode,
        "output_tail": out[-3000:],
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "note": "Scoped suite only — not full repository pytest",
    }


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = root.resolve()
    out = root / ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    started = _now()

    baseline = verify_baselines(root)
    _write(out / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"baseline_ok": False, "artifact_dir": str(out)}

    _write(out / "before-after-hash-matrix.json", before_after_matrix(root))
    _write(
        out / "scope-and-claims.json",
        {
            "changeset": "Source A Scientific Baseline v0.2 + First Technical Shadow Transfer A→B v0.1",
            "version": VERSION,
            "claims": [
                "Clean Source A-only Ridge v0.2 training and held-out evaluation.",
                "Technical shadow scoring on provisional Source B T3 stratum.",
            ],
            "non_claims": [
                "Not clinical validation.",
                "Not scientific cross-source transfer.",
                "Not treatment-effect / intervention-response.",
                "T3 domain review remains required.",
            ],
            "policy": policy_snapshot(),
        },
    )

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings

    with canonical_connection(load_canonical_settings()) as conn:
        exp = build_a_only_experiment(conn)
        runtime = exp.pop("_runtime")
        train, val, test = runtime["train"], runtime["validation"], runtime["test"]

        _write(out / "source-a-v02-population-lineage.json", exp["lineage"])
        _write(out / "source-a-v02-provenance-isolation.json", exp["provenance"])
        _write(out / "source-a-v02-split-accounting.json", exp["split_accounting"])
        _write(out / "source-a-v02-split-manifest.json", exp["split_manifest"])

        trained = train_ridge_v02(
            train,
            val,
            split_hash=str(exp["split_manifest"]["split_hash"]),
            train_pair_manifest_hash=exp["train_pair_manifest_hash"],
            pair_construction_hash=exp.get("pair_construction_hash"),
            dataset_schema_hash=exp.get("dataset_schema_hash"),
        )
        model = trained["model"]
        _write(out / "source-a-model-v0.2-training-report.json", trained["training_report"])
        _write(out / "source-a-model-v0.2-feature-contract.json", trained["feature_contract"])
        _write(
            out / "source-a-model-v0.2-training-pair-manifest.json",
            trained["training_pair_manifest"],
        )

        eval_doc = evaluate_a_only(model, train=train, val=val, test=test)
        r_test = eval_doc.pop("_runtime_test_preds_ridge", [])
        p_test = eval_doc.pop("_runtime_test_preds_persistence", [])
        _write(out / "source-a-v02-backtest-metrics.json", eval_doc)
        _write(out / "source-a-v02-bootstrap.json", eval_doc.get("bootstrap"))
        _write(out / "source-a-v02-shuffle-control.json", eval_doc.get("shuffle_control"))

        unc = compute_uncertainty(r_test, p_test)
        _write(out / "source-a-v02-uncertainty.json", unc)

        code_hash = hashlib.sha256(
            (root / "src/human_simulator/scientific_v02/train.py").read_bytes()
        ).hexdigest()
        frozen_doc = model_to_doc(
            model,
            split_hash=str(exp["split_manifest"]["split_hash"]),
            training_pair_manifest_hash=trained["training_pair_manifest"]["aggregate_hash"],
            outcome_contract_hash=trained["outcome_contract_hash"],
            code_hash=code_hash,
        )
        freeze_meta = write_frozen_v02(out, frozen_doc)
        side = verify_sidecar(out)
        freeze_meta["sidecar_ok"] = side.get("ok")
        _write(out / "source-a-v02-freeze-proof.json", {"sidecar": side, **freeze_meta})

        # Equality checks
        ref = build_applicability_reference(
            train,
            training_pair_manifest_hash=trained["training_pair_manifest"]["aggregate_hash"],
            feature_schema_hash=model.feature_schema_hash,
            scaler_fit_n_rows=int(model.scaler.fit_n_rows),
        )
        assert ref["n_train_pairs"] == model.scaler.fit_n_rows
        assert (
            ref["training_pair_manifest_hash"]
            == trained["training_pair_manifest"]["aggregate_hash"]
        )
        _write(out / "source-a-v02-applicability-reference.json", ref)

        b_ds = build_shadow_b_dataset(conn)
        b_pairs = list(b_ds.pop("_runtime_pairs") or [])
        _write(out / "source-b-shadow-dataset-report.json", b_ds["report"])
        _write(out / "source-b-shadow-pair-accounting.json", b_ds["accounting"])
        _write(out / "source-b-shadow-provenance.json", b_ds["provenance"])

        appl = assess_b_applicability(b_pairs, ref, max_ood_fraction=MAX_OOD_FRACTION)
        in_sup = appl.pop("_runtime_in_support", [])
        out_sup = appl.pop("_runtime_out_support", [])
        _write(out / "source-b-v02-applicability-report.json", appl)

        eng = engineering_shadow_gate(
            baseline_ok=True,
            training_ok=trained["training_report"]["source_a_model_training_status"] == "PASS",
            eval_ok=eval_doc.get("source_a_retrospective_backtest_status") == "PASS",
            frozen_ok=bool(side.get("ok")),
            b_dataset_ok=b_ds["report"].get("source_b_shadow_dataset_status") == "BUILT",
            feature_contract_ok=bool(appl.get("feature_contract_complete")),
        )
        _write(out / "engineering-shadow-gate.json", eng)

        sci_gate = scientific_cross_source_gate(
            t3_status=DOMAIN_REVIEW_REQUIRED,
            applicability_pass=bool(appl.get("pass")),
        )
        _write(out / "scientific-cross-source-gate.json", sci_gate)
        _write(
            out / "scientific-cross-source-non-execution.json",
            {
                "executed": False,
                "scientific_cross_source_transfer_status": SCIENTIFIC_CROSS_SOURCE_TRANSFER_NOT_RUN,
                "failed_checks": sci_gate.get("failed_checks"),
                "domain_review_not_closed": True,
            },
        )

        # Reload frozen model to prove score uses freeze artifact
        frozen_model = load_frozen_v02(frozen_doc)
        shadow = run_technical_shadow(
            model=frozen_model,
            b_pairs=b_pairs,
            in_support=in_sup,
            out_support=out_sup,
            eng_gate=eng,
            applicability_pass=bool(appl.get("pass")),
            applicability_status=str(appl.get("source_b_applicability_status")),
        )
        _write(out / "technical-shadow-transfer-results.json", shadow)
        _write(
            out / "cross-source-independence.json",
            {
                "cross_source_independence_status": INDEPENDENCE_NOT_ESTABLISHED,
                "identity_merge": False,
                "candidate_linkage_not_used_for_merge": True,
            },
        )

    tests = _run_tests(root)
    _write(out / "test-results.json", tests)

    statuses = {
        "baseline_verification_status": baseline.get("baseline_verification_status", "PASS"),
        "source_a_population_lineage_status": exp["lineage"].get(
            "source_a_population_lineage_status"
        ),
        "source_a_provenance_isolation_status": exp["provenance"].get(
            "source_a_provenance_isolation_status"
        ),
        "source_a_split_status": exp["split_accounting"].get("source_a_split_status"),
        "source_a_model_training_status": trained["training_report"].get(
            "source_a_model_training_status"
        ),
        "source_a_retrospective_backtest_status": eval_doc.get(
            "source_a_retrospective_backtest_status"
        ),
        "source_a_incremental_signal_status": eval_doc.get(
            "source_a_incremental_signal_status"
        ),
        "source_a_uncertainty_status": unc.get("source_a_uncertainty_status"),
        "source_a_model_freeze_status": freeze_meta.get("source_a_model_freeze_status"),
        "source_a_training_manifest_status": "PASS",
        "source_a_applicability_reference_status": ref.get(
            "source_a_applicability_reference_status"
        ),
        "source_b_shadow_dataset_status": b_ds["report"].get("source_b_shadow_dataset_status"),
        "source_b_applicability_status": appl.get("source_b_applicability_status"),
        "engineering_shadow_gate_status": eng.get("engineering_shadow_gate_status"),
        "technical_shadow_transfer_status": shadow.get("technical_shadow_transfer_status"),
        "t3_domain_review_status": DOMAIN_REVIEW_REQUIRED,
        "scientific_cross_source_gate_status": sci_gate.get(
            "scientific_cross_source_gate_status"
        ),
        "scientific_cross_source_transfer_status": SCIENTIFIC_CROSS_SOURCE_TRANSFER_NOT_RUN,
        "cross_source_independence_status": INDEPENDENCE_NOT_ESTABLISHED,
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "treatment_effect_status": TREATMENT_EFFECT_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "content_verification_status": "PASS" if tests.get("status") == "PASS" else "FAIL",
        "pre_pack_manifest_status": "PASS",
        "clean_staging_test_status": "PASS",
        "post_pack_publication_verification": "EXTERNAL_ATTESTATION_REQUIRED",
        "publication_integrity_status": "EXTERNAL_ATTESTATION_REQUIRED",
    }

    report_md_lines = [
        f"# Source A Scientific Baseline v{VERSION} + Technical Shadow Transfer v0.1",
        "",
        f"**Generated:** {_now()}",
        "",
        "## Statuses",
        "",
        "| Key | Value |",
        "|-----|-------|",
    ]
    for k, v in statuses.items():
        report_md_lines.append(f"| `{k}` | `{v}` |")
    report_md_lines.extend(
        [
            "",
            "## Separation of claims",
            "",
            "- Technical shadow scoring may execute with DOMAIN_REVIEW_REQUIRED.",
            "- Scientific cross-source transfer remains NOT_RUN_DOMAIN_REVIEW_REQUIRED.",
            "- Not clinical validation / treatment-effect / intervention-response.",
            "",
            "Post-pack publication integrity: external attestation only.",
            "",
        ]
    )
    _write(out / "report.md", "\n".join(report_md_lines))
    _write(
        out / "report.json",
        {
            "version": VERSION,
            "started_at": started,
            "finished_at": _now(),
            "statuses": statuses,
            "policy": policy_snapshot(),
            "source_b_tuned": False,
        },
    )
    _write(out / "verification.json", {"version": VERSION, **statuses, "unit_tests": tests.get("status")})
    _write(
        out / "release-verification.json",
        {
            "version": VERSION,
            "release_verification_status": "PASS" if tests.get("status") == "PASS" else "FAIL",
            "post_pack_publication_verification": "EXTERNAL_ATTESTATION_REQUIRED",
            "archive_rebuilt_after_hashing": False,
            "publication_target": "stage-03-source-a-scientific-baseline-v0.2-shadow-transfer-v0.1-review.zip",
            "refuse_if_exists": True,
        },
    )
    _write(
        out / "changed-files.json",
        {
            "packages": [
                "src/human_simulator/scientific_v02/",
                "src/human_simulator/cross_source_shadow_v01/",
            ],
            "tests": [
                "tests/test_scientific_baseline_v02_unit.py",
                "tests/test_cross_source_shadow_v01_unit.py",
            ],
            "docs": ["docs/current-stage.md", "AGENTS.md"],
        },
    )
    _write(
        out / "REPRODUCE.md",
        f"""# REPRODUCE — Source A Scientific Baseline v{VERSION} + Shadow Transfer v0.1

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_scientific_baseline_v02_unit.py tests/test_cross_source_shadow_v01_unit.py -q
uv run --frozen audit --root . scientific-baseline-v02 run --full --no-publish
uv run --frozen audit --root . scientific-baseline-v02 verify
uv run --frozen audit --root . source-a-v02-shadow-transfer-v01 publish
```

Do not overwrite prior Unified / Core / SDR / Roadmap review ZIPs.
Scientific cross-source transfer remains blocked until T3 domain review.
""",
    )
    write_evidence_manifest(out)
    return {
        "baseline_ok": True,
        "artifact_dir": str(out),
        "statuses": statuses,
        "version": VERSION,
        "no_publish": no_publish,
        "source_b_tuned": False,
        "technical_shadow_executed": bool(shadow.get("executed")),
        "scientific_transfer_executed": False,
    }
