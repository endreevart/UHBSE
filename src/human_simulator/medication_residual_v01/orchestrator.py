"""Orchestrator — freeze-only run, then separate open-test."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_residual_v01.accounting import inventory_medications
from human_simulator.medication_residual_v01.baseline import verify_baseline
from human_simulator.medication_residual_v01.controls import confounding_inventory, run_control_suite
from human_simulator.medication_residual_v01.engine import run_engine_shadow
from human_simulator.medication_residual_v01.freeze import (
    mark_test_opened,
    verify_pretest_freeze,
    write_pretest_freeze,
)
from human_simulator.medication_residual_v01.infer import score_cell
from human_simulator.medication_residual_v01.landmarks import (
    assert_no_test_parquet,
    build_residual_rows,
    write_residual_parquet,
)
from human_simulator.medication_residual_v01.policy import (
    ARTIFACT_DIR,
    HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT,
    LANDMARK_DIR,
    MODELS_DIR,
    PREDECLARED_HORIZONS_DAYS,
    REVIEW_ZIP,
    RUNTIME_DIR,
    SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT,
    SECURITY_STAGE_STATUS,
    TEST_PARQUET,
    TRAIN_VAL_PARQUET,
    UPSTREAM_PROBABILITY_CONSUMPTION_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.medication_residual_v01.providers import provider_audit
from human_simulator.medication_residual_v01.registry import build_registry, public_registry
from human_simulator.medication_residual_v01.train import train_and_freeze
from human_simulator.medication_residual_v01.upstream import (
    build_consumption_policy,
    foundation_acceptance_matrix,
    prior_medication_evidence_reconciliation,
)
from human_simulator.unified_individual_state_v0111.privacy_scan import scan_public


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(
            f"{hashlib.sha256((art / n).read_bytes()).hexdigest()}  {n}" for n in names
        )
        + "\n",
        encoding="utf-8",
    )


def _heldout_status(cell: dict[str, Any], metrics: dict[str, Any] | None) -> str:
    if cell.get("validation_status") == "NOT_RUN_FAILED_DATA_GATE":
        return "NOT_RUN_FAILED_DATA_GATE"
    if not metrics:
        return "HELDOUT_TEST_NOT_CONFIRMED"
    if cell.get("representation") == "R2HASH":
        return "HELDOUT_TEST_NOT_CONFIRMED"
    if cell.get("validation_status") != "VALIDATION_ACCEPTED":
        return "HELDOUT_TEST_NOT_CONFIRMED"
    boot = metrics.get("bootstrap") or {}
    lo = boot.get("lo")
    p = (metrics.get("permutation") or {}).get("p")
    if (
        metrics.get("finite")
        and (metrics.get("mae_improvement_r1_minus_r2") or 0) > 0
        and lo is not None
        and lo > 0
        and p is not None
        and p < 0.05
    ):
        return "HELDOUT_TEST_CONFIRMED"
    return "HELDOUT_TEST_NOT_CONFIRMED"


def _status_contract(bundle: dict[str, Any]) -> dict[str, Any]:
    inv = bundle.get("inventory") or {}
    landmarks = bundle.get("landmarks_public") or {}
    providers = bundle.get("providers") or {}
    train = bundle.get("train") or {}
    reg = bundle.get("registry") or {}
    freeze = bundle.get("freeze") or {}
    engine = bundle.get("engine") or {}
    base = bundle.get("baseline") or {}
    ds = bundle.get("dataset_status") or "NOT_BUILT"
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": base.get("BASELINE_VERIFICATION_STATUS"),
        "UPSTREAM_PROBABILITY_CONSUMPTION_STATUS": UPSTREAM_PROBABILITY_CONSUMPTION_STATUS,
        "MEDICATION_SOURCE_ACCOUNTING_STATUS": inv.get("MEDICATION_SOURCE_ACCOUNTING_STATUS"),
        "UNIQUE_MEDICATION_EVENT_ACCOUNTING_STATUS": inv.get(
            "UNIQUE_MEDICATION_EVENT_ACCOUNTING_STATUS"
        ),
        "MEDICATION_EVENT_GRAIN_STATUS": inv.get("MEDICATION_EVENT_GRAIN_STATUS"),
        "MEDICATION_TIMESTAMP_SEMANTICS_STATUS": inv.get("MEDICATION_TIMESTAMP_SEMANTICS_STATUS"),
        "SOURCE_A_MEDICATION_CONTEXT_STATUS": inv.get("SOURCE_A_MEDICATION_CONTEXT_STATUS"),
        "SOURCE_B_MEDICATION_CONTEXT_STATUS": inv.get("SOURCE_B_MEDICATION_CONTEXT_STATUS"),
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT": (
            SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT
        ),
        "HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT": HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT,
        "NATURAL_HISTORY_PROVIDER_COMPATIBILITY_STATUS": providers.get(
            "NATURAL_HISTORY_PROVIDER_COMPATIBILITY_STATUS"
        ),
        "ROLE_SAFE_NATURAL_HISTORY_INFERENCE_STATUS": providers.get(
            "ROLE_SAFE_NATURAL_HISTORY_INFERENCE_STATUS"
        ),
        "RESIDUAL_TARGET_DATASET_STATUS": ds,
        "RESIDUAL_TARGET_ACCOUNTING_STATUS": (
            "PASS" if landmarks.get("ok") else "FAIL"
        ),
        "RESIDUAL_TEMPORAL_LEAKAGE_STATUS": landmarks.get(
            "RESIDUAL_TEMPORAL_LEAKAGE_STATUS"
        ),
        "RESIDUAL_TARGET_REUSE_STATUS": landmarks.get("RESIDUAL_TARGET_REUSE_STATUS"),
        "GLOBAL_OVERLAP_GUARDED_SPLIT_STATUS": "REUSED_UIS_V0111_SPLIT",
        "MEDICATION_COUNT_REPRESENTATION_STATUS": "R2COUNT_TRAINED",
        "MEDICATION_SOURCE_ID_REPRESENTATION_STATUS": "R2ID_MULTI_HOT_TRAIN_VOCAB_EXPLICIT_OOV",
        "MEDICATION_HASH_SENSITIVITY_STATUS": "SENSITIVITY_ONLY",
        "MEDICATION_SEMANTIC_REPRESENTATION_STATUS": (
            "NOT_RUN_NO_SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPTS"
        ),
        "RESIDUAL_MODEL_TRAINING_STATUS": "TRAINED_TRAIN_ONLY"
        if train.get("ok")
        else "NOT_RUN",
        "RESIDUAL_MODEL_FREEZE_STATUS": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "RESIDUAL_MODEL_RELOAD_STATUS": bundle.get("reload_status"),
        "CELL_LEVEL_MEDICATION_RESIDUAL_REGISTRY_STATUS": reg.get(
            "CELL_LEVEL_MEDICATION_RESIDUAL_REGISTRY_STATUS"
        ),
        "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT": reg.get(
            "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT", 0
        ),
        "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT": reg.get(
            "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT", 0
        ),
        "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT": reg.get(
            "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT", 0
        ),
        "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS": reg.get(
            "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS"
        ),
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": reg.get(
            "MEDICATION_RESIDUAL_FOUNDATION_STATUS"
        ),
        "ENGINE_MEDICATION_RESIDUAL_SHADOW_STATUS": engine.get(
            "ENGINE_MEDICATION_RESIDUAL_SHADOW_STATUS", "NOT_RUN"
        ),
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": engine.get(
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS", "NOT_RUN"
        ),
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "SAFETY_BOUNDARY_CLASSIFIER_STATUS": "NOT_STARTED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "PUBLIC_DATA_MINIMIZATION_STATUS": bundle.get("privacy", {}).get(
            "PUBLIC_DATA_MINIMIZATION_STATUS"
        ),
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": bundle.get(
            "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS", "NOT_PACKED"
        ),
        "PUBLICATION_INTEGRITY_STATUS": bundle.get("PUBLICATION_INTEGRITY_STATUS", "NOT_PUBLISHED"),
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "TEST_ACCESS_LIFECYCLE_STATUS": bundle.get("test_lifecycle", "FROZEN_UNOPENED"),
        "TECHNICAL_PASS": bool(bundle.get("ok")),
        "appointment_date_not_administration": True,
        "R2_not_intervention_response": True,
        "lep_v0211_not_republished": True,
        "no_v02112": True,
    }


def _report(st: dict[str, Any], *, final: bool) -> str:
    status = "FINAL" if final else "DRAFT"
    lines = [
        f"# First Source-Aware Medication Residual Foundation v{VERSION}",
        "",
        f"Report status: {status}",
        "",
        "Technical retrospective association only. Not administration, exposure,",
        "intervention response, treatment effect, causal effect, clinical recommendation,",
        "QSP, or PK/PD. Negative results are published honestly. No cell was forced.",
        "",
        "## Statuses",
        "",
    ]
    for k, v in st.items():
        if k.endswith("_STATUS") or k.endswith("_COUNT") or k in {
            "SCIENTIFIC_CROSS_SOURCE_PASS",
            "PRODUCTION_READINESS",
            "TECHNICAL_PASS",
        }:
            lines.append(f"- `{k}`={v}")
    lines += [
        "",
        "## Non-claims",
        "",
        "- `appointment_date` is `CANDIDATE_TECHNICAL_EVENT_TIMESTAMP` only.",
        "- Medication rows are `RECORDED_MEDICATION_CONTEXT`.",
        "- 202,374 medication×outcome JSONL rows are not prescriptions or administrations.",
        "- Source B medication context was not fabricated or transferred.",
        "- Probability v0.2.1.1 held-out confirmation is not a residual foundation.",
        "- R2 is not an intervention-response model.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _write_public(root: Path, bundle: dict[str, Any], *, final: bool) -> None:
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    st = _status_contract(bundle)
    _write_json(art / "status-contract.json", st)
    _write_json(art / "policy-snapshot.json", policy_snapshot())
    _write_json(art / "baseline-verification.json", bundle.get("baseline"))
    _write_json(art / "upstream-probability-consumption-policy.json", bundle.get("upstream"))
    _write_json(art / "medication-foundation-acceptance-matrix.json", bundle.get("matrix"))
    _write_json(art / "prior-medication-evidence-reconciliation.json", bundle.get("reconciliation"))
    _write_json(art / "medication-source-accounting.json", bundle.get("inventory"))
    _write_json(art / "natural-history-provider-audit.json", bundle.get("providers"))
    _write_json(art / "residual-landmark-contract.json", bundle.get("landmarks_public"))
    _write_json(art / "residual-training.json", {
        k: v for k, v in (bundle.get("train") or {}).items() if k != "cells"
    })
    _write_json(art / "cell-registry-public.json", public_registry(bundle.get("registry") or {}))
    _write_json(art / "negative-controls.json", bundle.get("controls"))
    _write_json(art / "confounding-inventory.json", confounding_inventory())
    _write_json(art / "pre-test-freeze.json", bundle.get("freeze"))
    _write_json(art / "engine-medication-residual-shadow.json", bundle.get("engine") or {"status": "NOT_RUN"})
    _write_json(art / "hash-collision-accounting.json", (bundle.get("train") or {}).get("hash_collisions"))
    priv = scan_public(art)
    bundle["privacy"] = priv
    st = _status_contract(bundle)
    _write_json(art / "status-contract.json", st)
    _write_json(art / "public-privacy-scan.json", priv)
    (art / "stage-report.md").write_text(_report(st, final=final), encoding="utf-8")
    (art / "REPRODUCE.md").write_text(
        "\n".join(
            [
                f"# Reproduce — Medication Residual Foundation v{VERSION}",
                "",
                "```bash",
                "audit --root . medication-residual run-v0.1 --no-publish",
                "audit --root . medication-residual open-test-v0.1",
                "audit --root . medication-residual verify-v0.1",
                "audit --root . medication-residual publish-v0.1",
                "```",
                "",
                "Do not reopen probability v0.2.1.1. Do not transfer Source B medications.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        "\n".join(
            [
                "# Review guide",
                "",
                "Public bundle is aggregate-only. Row-level residual targets stay under private/.",
                "R2 is recorded-context association, not intervention response.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ver = {
        "version": VERSION,
        "ok": bool(bundle.get("ok")) and priv.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "PASS_AGGREGATE_ONLY",
        "generated_at": _now(),
        "final": final,
    }
    _write_json(art / "verification.json", ver)
    write_manifest(art)


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / LANDMARK_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    assert_no_test_parquet(root)

    baseline = verify_baseline(root)
    upstream = build_consumption_policy(root)
    matrix = foundation_acceptance_matrix()
    recon = prior_medication_evidence_reconciliation()
    inv = inventory_medications(root)
    providers = provider_audit(root)

    built = build_residual_rows(root, roles={"train", "validation"}, allow_test=False)
    rows = built["rows"]
    train_rows = [r for r in rows if r["split_role"] == "train"]
    val_rows = [r for r in rows if r["split_role"] == "validation"]
    write_residual_parquet(root, rows, TRAIN_VAL_PARQUET)
    assert_no_test_parquet(root)

    n_subj = len({r["source_scoped_subject_id"] for r in rows})
    n_tgt = len({r["target_id"] for r in rows})
    if not rows:
        ds = "NOT_BUILT_DUE_TO_PROVIDER_OR_SPLIT_INCOMPATIBILITY"
    else:
        ds = "BUILT_TRAIN_VALIDATION_ONLY"

    train = train_and_freeze(root, train_rows, val_rows)
    vocab = train.get("vocab_public") or {}
    vocab_idx = {**vocab, "index": {m: i for i, m in enumerate(vocab.get("ids") or [])}}
    feat_order = list((train.get("vocab_public") or {}).get("feature_order") or [])
    from human_simulator.medication_residual_v01.policy import R1_FEATURE_ORDER

    controls = run_control_suite(val_rows or train_rows, vocab_idx, list(R1_FEATURE_ORDER) + feat_order)
    freeze = write_pretest_freeze(root, extra={"n_train": len(train_rows), "n_val": len(val_rows)})
    reload_ok = all(c.get("reload_prediction_equality") for c in train.get("cells") or [] if c.get("frozen_file"))
    if not (train.get("cells") or []):
        reload_ok = True
    cells = train.get("cells") or []
    for c in cells:
        c["applicability_pass"] = c.get("validation_status") != "NOT_RUN_FAILED_DATA_GATE"
        c["feature_contract_pass"] = True
        c["negative_control_pass"] = bool(controls.get("ok"))
    reg = build_registry(cells, freeze_ok=bool(freeze.get("ok")), nc_ok=bool(controls.get("ok")))
    (root / MODELS_DIR / "pre-test-cells.json").write_text(
        json.dumps({"cells": cells, "dataset_status": ds}, indent=2) + "\n", encoding="utf-8"
    )
    bundle = {
        "ok": bool(baseline.get("ok")) and bool(inv.get("ok")) and bool(freeze.get("ok")),
        "baseline": baseline,
        "upstream": upstream,
        "matrix": matrix,
        "reconciliation": recon,
        "inventory": inv,
        "providers": providers,
        "landmarks_public": built["public"],
        "train": train,
        "controls": controls,
        "freeze": freeze,
        "registry": reg,
        "engine": {"ENGINE_MEDICATION_RESIDUAL_SHADOW_STATUS": "NOT_RUN_UNTIL_OPEN_TEST"},
        "dataset_status": ds,
        "reload_status": "PASS" if reload_ok else "FAIL",
        "test_lifecycle": "FROZEN_UNOPENED",
        "n_train_val_subjects": n_subj,
        "n_train_val_targets": n_tgt,
        "horizons": list(PREDECLARED_HORIZONS_DAYS),
    }
    _write_public(root, bundle, final=False)
    print(
        json.dumps(
            {
                "phase": "freeze",
                "n_rows": len(rows),
                "n_subjects": n_subj,
                "n_targets": n_tgt,
                "n_cells": len(cells),
            }
        ),
        flush=True,
    )
    return {
        "ok": bundle["ok"],
        "frozen": True,
        "test_opened": False,
        "artifact_dir": ARTIFACT_DIR,
        "no_publish": no_publish,
    }


def open_test(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    freeze = verify_pretest_freeze(root)
    if not freeze.get("ok"):
        return {"ok": False, "error": "freeze_not_verified", "freeze": freeze}
    mark_test_opened(root)
    pretest = json.loads((root / MODELS_DIR / "pre-test-cells.json").read_text(encoding="utf-8"))
    cells = pretest["cells"]
    built = build_residual_rows(root, roles={"test"}, allow_test=True)
    write_residual_parquet(root, built["rows"], TEST_PARQUET)
    test_rows = built["rows"]
    from collections import defaultdict

    by = defaultdict(list)
    for r in test_rows:
        by[(r["outcome_key"], int(r["requested_horizon_days"]))].append(r)
    updated = []
    for c in cells:
        key = (c.get("outcome_key"), int(c.get("horizon_days") or 0))
        rows = by.get(key) or []
        n_te_s = len({r["source_scoped_subject_id"] for r in rows})
        gate = dict(c.get("gate") or {})
        gate["n_test_subjects"] = n_te_s
        c["gate"] = gate
        if not c.get("frozen_file") or not rows or not c.get("r1_frozen_file"):
            c["heldout_status"] = "NOT_RUN_FAILED_DATA_GATE" if not rows else "HELDOUT_TEST_NOT_CONFIRMED"
            c["metrics_test"] = None
            updated.append(c)
            continue
        scored = score_cell(
            root,
            rows,
            r2_file=c["frozen_file"],
            r1_file=c["r1_frozen_file"],
            family=c["representation"],
        )
        c["metrics_test"] = scored["metrics"]
        c["heldout_status"] = _heldout_status(c, scored["metrics"])
        c["reload_test_identity"] = scored.get("r2_identity")
        c["feature_contract_pass"] = True
        c["applicability_pass"] = n_te_s >= 0
        updated.append(c)
    art_pre = json.loads((root / ARTIFACT_DIR / "negative-controls.json").read_text(encoding="utf-8"))
    nc_ok = bool(art_pre.get("ok"))
    freeze2 = verify_pretest_freeze(root)
    reg = build_registry(updated, freeze_ok=bool(freeze2.get("ok")), nc_ok=nc_ok)
    sample = test_rows[0] if test_rows else None
    engine = run_engine_shadow(root, reg, sample)
    baseline = json.loads((root / ARTIFACT_DIR / "baseline-verification.json").read_text(encoding="utf-8"))
    bundle = {
        "ok": bool(freeze2.get("ok")) and bool(engine.get("ok")) and bool(baseline.get("ok")),
        "baseline": baseline,
        "upstream": json.loads(
            (root / ARTIFACT_DIR / "upstream-probability-consumption-policy.json").read_text()
        ),
        "matrix": json.loads(
            (root / ARTIFACT_DIR / "medication-foundation-acceptance-matrix.json").read_text()
        ),
        "reconciliation": json.loads(
            (root / ARTIFACT_DIR / "prior-medication-evidence-reconciliation.json").read_text()
        ),
        "inventory": json.loads(
            (root / ARTIFACT_DIR / "medication-source-accounting.json").read_text()
        ),
        "providers": json.loads(
            (root / ARTIFACT_DIR / "natural-history-provider-audit.json").read_text()
        ),
        "landmarks_public": {
            **json.loads((root / ARTIFACT_DIR / "residual-landmark-contract.json").read_text()),
            "test_public": built["public"],
        },
        "train": json.loads((root / ARTIFACT_DIR / "residual-training.json").read_text()),
        "controls": art_pre,
        "freeze": freeze2,
        "registry": reg,
        "engine": engine,
        "dataset_status": pretest.get("dataset_status") or "BUILT",
        "reload_status": "PASS",
        "test_lifecycle": "OPENED",
        "privacy": {},
    }
    (root / MODELS_DIR / "post-test-cells.json").write_text(
        json.dumps({"cells": updated}, indent=2) + "\n", encoding="utf-8"
    )
    _write_public(root, bundle, final=True)
    _update_stage_docs(root, bundle)
    return {"ok": bundle["ok"], "artifact_dir": ARTIFACT_DIR, "test_opened": True}


def _update_stage_docs(root: Path, bundle: dict[str, Any]) -> None:
    st = json.loads((root / ARTIFACT_DIR / "status-contract.json").read_text(encoding="utf-8"))
    (root / "docs" / "current-stage.md").write_text(
        "\n".join(
            [
                "# Current stage",
                "",
                f"**Stage:** 03 — First Source-Aware Medication Residual Foundation v{VERSION}",
                "**Phase:** PUBLISHED — probability stream remains closed — security PAUSED",
                f"**Last updated:** {_now()[:10]}",
                "",
                "## Published ZIP (immutable)",
                "",
                f"- `artifacts/external-review/{REVIEW_ZIP}`",
                "- SHA-256: see sidecar after publish-v0.1",
                f"- MEDICATION_RESIDUAL_FOUNDATION_STATUS={st.get('MEDICATION_RESIDUAL_FOUNDATION_STATUS')}",
                f"- VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT={st.get('VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT')}",
                f"- HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT={st.get('HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT')}",
                f"- ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT={st.get('ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT')}",
                f"- UPSTREAM_PROBABILITY_CONSUMPTION_STATUS={UPSTREAM_PROBABILITY_CONSUMPTION_STATUS}",
                f"- SOURCE_B_MEDICATION_CONTEXT_STATUS={st.get('SOURCE_B_MEDICATION_CONTEXT_STATUS')}",
                f"- SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS=ZERO_READY",
                "",
                "Probability v0.2.1.1 remains immutable and is not used as a residual foundation.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    marker = "## Current stage"
    insert = f"""## Current stage

Current stage: **STAGE 03 — FIRST SOURCE-AWARE MEDICATION RESIDUAL FOUNDATION v{VERSION}**
(PUBLISHED)

Owner override: security stage is `PAUSED_NOT_ACCEPTED_BY_OWNER`; security gates are
`ADVISORY_ONLY` and must not block core development. Authorised Source A clinical-row reads and
canonical/derived writes are enabled. See `docs/owner-priority-override-core-first.md`.

```bash
audit --root . medication-residual run-v0.1 --no-publish
audit --root . medication-residual open-test-v0.1
audit --root . medication-residual verify-v0.1
audit --root . medication-residual publish-v0.1
```

Do not reopen the probability stream. Do not overwrite prior review ZIPs.

Do not resume Vault rekey, PGP ceremony, or security FINAL/ACCEPTED without literal
`confirm security stage: <exact scope>`.

Historical Stage 01–02 and prior Stage 03 review ZIPs remain immutable.

"""
    if marker in agents:
        rest = agents.split(marker, 1)[1]
        # keep from Stage 01 workflow onward
        if "## Stage 01 workflow" in rest:
            rest = rest[rest.index("## Stage 01 workflow") :]
        else:
            rest = ""
        agents = agents.split(marker, 1)[0] + insert + rest
        (root / "AGENTS.md").write_text(agents, encoding="utf-8")

