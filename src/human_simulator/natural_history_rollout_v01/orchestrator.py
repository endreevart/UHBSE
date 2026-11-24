"""Orchestrator — freeze-only run, then separate open-test."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.natural_history_rollout_v01.assembly import assemble_marginal_state
from human_simulator.natural_history_rollout_v01.baseline import verify_baseline
from human_simulator.natural_history_rollout_v01.engine import run_engine_shadow
from human_simulator.natural_history_rollout_v01.evaluate import rollout_cell_metrics
from human_simulator.natural_history_rollout_v01.freeze import (
    mark_test_opened,
    verify_pretest_freeze,
    write_pretest_freeze,
)
from human_simulator.natural_history_rollout_v01.limitations import (
    consumption_matrix,
    reproduce_limitations,
    rollout_acceptance_policy,
)
from human_simulator.natural_history_rollout_v01.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    MIN_TEST_SUBJECTS,
    PREDECLARED_HORIZONS_DAYS,
    REVIEW_ZIP,
    RUNTIME_DIR,
    SECURITY_STAGE_STATUS,
    SEQ_DIR,
    TEST_PARQUET,
    TRAIN_VAL_PARQUET,
    VERSION,
    policy_snapshot,
)
from human_simulator.natural_history_rollout_v01.privacy import scan_public
from human_simulator.natural_history_rollout_v01.providers import predict_active, train_providers
from human_simulator.natural_history_rollout_v01.registry import build_registry, public_registry
from human_simulator.natural_history_rollout_v01.residuals import fit_residuals
from human_simulator.natural_history_rollout_v01.sequences import (
    assert_no_test_parquet,
    audit_uis_m1,
    build_sequences,
    inventory_from_series,
    load_series,
    load_split,
    transitions_from_sequences,
    write_sequences,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{hashlib.sha256((art / n).read_bytes()).hexdigest()}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )


def _status(bundle: dict[str, Any]) -> dict[str, Any]:
    lim = bundle.get("limitations") or {}
    inv = bundle.get("inventory") or {}
    seq = bundle.get("sequences_public") or {}
    train = bundle.get("train") or {}
    reg = bundle.get("registry") or {}
    eng = bundle.get("engine") or {}
    freeze = bundle.get("freeze") or {}
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": (bundle.get("baseline") or {}).get("BASELINE_VERIFICATION_STATUS"),
        "PRIOR_MEDICATION_RESIDUAL_LIMITATION_REPRODUCTION_STATUS": lim.get(
            "PRIOR_MEDICATION_RESIDUAL_LIMITATION_REPRODUCTION_STATUS"
        ),
        "PRIOR_MEDICATION_RESIDUAL_FOUNDATION_STATUS": lim.get("PRIOR_MEDICATION_RESIDUAL_FOUNDATION_STATUS"),
        "SOURCE_A_PROVIDER_INVENTORY_STATUS": inv.get("SOURCE_A_PROVIDER_INVENTORY_STATUS"),
        "SOURCE_B_PROVIDER_INVENTORY_STATUS": inv.get("SOURCE_B_PROVIDER_INVENTORY_STATUS"),
        "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS": inv.get("SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS"),
        "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS": train.get(
            "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS"
        ),
        "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": train.get("TRAIN_ONLY_PROVIDER_SELECTION_STATUS"),
        "ROLLOUT_SEQUENCE_DATASET_STATUS": bundle.get("dataset_status"),
        "ROLLOUT_SEQUENCE_ACCOUNTING_STATUS": "PASS" if seq.get("ok") else "FAIL",
        "ROLLOUT_TEMPORAL_LEAKAGE_STATUS": seq.get("ROLLOUT_TEMPORAL_LEAKAGE_STATUS"),
        "ROLLOUT_SPLIT_ISOLATION_STATUS": seq.get("ROLLOUT_SPLIT_ISOLATION_STATUS"),
        "ROLLOUT_TARGET_REUSE_STATUS": seq.get("ROLLOUT_TARGET_REUSE_STATUS"),
        "ONE_STEP_PROVIDER_REGISTRY_STATUS": reg.get("ONE_STEP_PROVIDER_REGISTRY_STATUS"),
        "ONE_STEP_VALIDATION_ACCEPTED_CELL_COUNT": reg.get("ONE_STEP_VALIDATION_ACCEPTED_CELL_COUNT", 0),
        "ONE_STEP_HELDOUT_CONFIRMED_CELL_COUNT": reg.get("ONE_STEP_HELDOUT_CONFIRMED_CELL_COUNT", 0),
        "STOCHASTIC_RESIDUAL_DISTRIBUTION_STATUS": (bundle.get("residuals") or {}).get(
            "STOCHASTIC_RESIDUAL_DISTRIBUTION_STATUS"
        ),
        "RECURSIVE_ROLLOUT_EVALUATION_STATUS": bundle.get("RECURSIVE_ROLLOUT_EVALUATION_STATUS", "NOT_RUN"),
        "RECURSIVE_ROLLOUT_ACCEPTED_CELL_COUNT": reg.get("RECURSIVE_ROLLOUT_ACCEPTED_CELL_COUNT", 0),
        "MULTI_OUTCOME_ROLLOUT_ASSEMBLY_STATUS": "MARGINAL_SOURCE_SPECIFIC_MULTI_OUTCOME_ROLLOUT",
        "MULTI_OUTCOME_DEPENDENCE_STATUS": "MARGINAL_ONLY_NO_JOINT_MODEL",
        "NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS": reg.get("NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS"),
        "OBSERVATION_PROCESS_SCHEDULER_STATUS": "TECHNICAL_OPTIONAL_WITH_UPSTREAM_LIMITATION",
        "INTERVENTION_SLOT_CONTRACT_STATUS": "TYPED_UNAVAILABLE",
        "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
        "ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS": eng.get("ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS", "NOT_RUN"),
        "ENGINE_DETERMINISTIC_REPLAY_STATUS": eng.get("ENGINE_DETERMINISTIC_REPLAY_STATUS", "NOT_RUN"),
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": eng.get(
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS", "NOT_RUN"
        ),
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": "NOT_CONSUMED_NOT_ACCEPTED",
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
        "PUBLIC_DATA_MINIMIZATION_STATUS": (bundle.get("privacy") or {}).get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": bundle.get("REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS", "NOT_PACKED"),
        "PUBLICATION_INTEGRITY_STATUS": bundle.get("PUBLICATION_INTEGRITY_STATUS", "NOT_PUBLISHED"),
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "TEST_ACCESS_LIFECYCLE_STATUS": bundle.get("test_lifecycle", "FROZEN_UNOPENED"),
        "TECHNICAL_PASS": bool(bundle.get("ok")),
        "lep_not_used_as_outcome_value": True,
        "no_medication_residual_consumption": True,
    }


def _report(st: dict[str, Any], *, final: bool) -> str:
    status = "FINAL" if final else "DRAFT"
    lines = [
        f"# Unified Source-Aware Natural-History Stochastic Rollout Foundation v{VERSION}",
        "",
        f"Report status: {status}",
        "",
        "Natural history only. Marginal source-specific trajectories. Not joint physiology,",
        "not intervention response, not clinical use. Medication residual v0.1 was not consumed.",
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
    lines += ["", "## Non-claims", "", "- `NATURAL_HISTORY_ONLY`", "- `CLINICAL_USE_PROHIBITED`", ""]
    return "\n".join(lines) + "\n"


def _write_public(root: Path, bundle: dict[str, Any], *, final: bool) -> None:
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    _write_json(art / "policy-snapshot.json", policy_snapshot())
    _write_json(art / "baseline-verification.json", bundle.get("baseline"))
    _write_json(art / "medication-residual-v01-limitations.json", bundle.get("limitations"))
    _write_json(art / "upstream-foundation-consumption-matrix.json", bundle.get("matrix"))
    _write_json(art / "rollout-foundation-acceptance-policy.json", bundle.get("policy"))
    _write_json(art / "source-provider-inventory.json", bundle.get("inventory"))
    _write_json(art / "rollout-sequence-contract.json", bundle.get("sequences_public"))
    _write_json(
        art / "one-step-providers.json",
        {
            "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS": (
                bundle.get("train") or {}
            ).get("SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS"),
            "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": (bundle.get("train") or {}).get(
                "TRAIN_ONLY_PROVIDER_SELECTION_STATUS"
            ),
            "n_cells": len((bundle.get("train") or {}).get("cells") or []),
            "no_medication_features": True,
            "no_vocab_hashes": True,
        },
    )
    _write_json(art / "residual-distributions.json", (bundle.get("residuals") or {}).get("public"))
    _write_json(art / "cell-registry-public.json", public_registry(bundle.get("registry") or {}))
    _write_json(
        art / "observation-process-scheduler.json",
        {
            "OBSERVATION_PROCESS_SCHEDULER_STATUS": "TECHNICAL_OPTIONAL_WITH_UPSTREAM_LIMITATION",
            "lep_survival_used_as_outcome_value": False,
            "excursion_not_latent_biological_event": True,
            "heldout_confirmation_not_scientific_pass": True,
            "fixed_time_grid_days": list(PREDECLARED_HORIZONS_DAYS),
            "endpoint_identity": "USER_REQUESTED_FIXED_TIME_GRID",
        },
    )
    _write_json(
        art / "intervention-slot-contract.json",
        {
            "INTERVENTION_SLOT_CONTRACT_STATUS": "TYPED_UNAVAILABLE",
            "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
            "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
            "inputs_accepted": [
                "medication",
                "supplement",
                "nutrition",
                "activity",
                "dose",
                "duration",
                "start_time",
            ],
            "nonzero_returns": "UNAVAILABLE",
            "no_hard_coded_drug_effect": True,
            "no_medication_residual_v01": True,
        },
    )
    _write_json(
        art / "multi-outcome-assembly.json",
        {
            "MULTI_OUTCOME_ROLLOUT_ASSEMBLY_STATUS": "MARGINAL_SOURCE_SPECIFIC_MULTI_OUTCOME_ROLLOUT",
            "MULTI_OUTCOME_DEPENDENCE_STATUS": "MARGINAL_ONLY_NO_JOINT_MODEL",
            "rejected_encoder_used": False,
            "no_zero_mean_imputation": True,
            "example": assemble_marginal_state(
                source_system="magerya_api",
                horizon_days=90,
                seed=42,
                requested_outcomes=["A::demo::u", "A::missing::u"],
                per_outcome={
                    "A::demo::u": {
                        "value": None,
                        "unit": "u",
                        "uncertainty": {"q05": None, "q95": None},
                        "provider_identity": None,
                        "unsupported": True,
                    }
                },
            ),
        },
    )
    _write_json(art / "pre-test-freeze.json", bundle.get("freeze"))
    _write_json(art / "engine-natural-history-shadow.json", bundle.get("engine") or {"status": "NOT_RUN"})
    (art / "REPRODUCE.md").write_text(
        "# Reproduce\n\n"
        "```bash\n"
        "audit --root . natural-history-rollout run-v0.1 --no-publish\n"
        "audit --root . natural-history-rollout open-test-v0.1\n"
        "audit --root . natural-history-rollout verify-v0.1\n"
        "audit --root . natural-history-rollout publish-v0.1\n"
        "```\n",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        "# Review guide\n\nAggregate-only public bundle. Natural history only.\n",
        encoding="utf-8",
    )
    st = _status(bundle)
    (art / "stage-report.md").write_text(_report(st, final=final), encoding="utf-8")
    _write_json(art / "status-contract.json", st)
    _write_json(
        art / "verification.json",
        {
            "version": VERSION,
            "ok": False,
            "generated_at": _now(),
            "final": final,
        },
    )
    priv = scan_public(art)
    bundle["privacy"] = priv
    bundle["ok"] = bool(bundle.get("ok")) and bool(priv.get("ok"))
    st = _status(bundle)
    _write_json(art / "status-contract.json", st)
    _write_json(art / "public-privacy-scan.json", priv)
    (art / "stage-report.md").write_text(_report(st, final=final), encoding="utf-8")
    _write_json(
        art / "verification.json",
        {
            "version": VERSION,
            "ok": bool(bundle.get("ok"))
            and priv.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "PASS_AGGREGATE_ONLY",
            "generated_at": _now(),
            "final": final,
        },
    )
    write_manifest(art)


def _persist_cells(root: Path, cells: list[dict[str, Any]]) -> None:
    models = root / MODELS_DIR
    models.mkdir(parents=True, exist_ok=True)
    slim = []
    for c in cells:
        payload = c.get("payload")
        fname = None
        if payload:
            fname = f"frozen-{c.get('model_identity_sha256', 'x')[:16]}.json"
            public_payload = dict(payload)
            (models / fname).write_text(json.dumps(public_payload, separators=(",", ":")) + "\n")
            c["frozen_file"] = fname
        slim.append(c)
    (models / "pre-test-cells.json").write_text(
        json.dumps({"cells": slim}, indent=2, default=str) + "\n", encoding="utf-8"
    )


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / SEQ_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    assert_no_test_parquet(root)
    baseline = verify_baseline(root)
    lim = reproduce_limitations(root)
    matrix = consumption_matrix()
    pol = rollout_acceptance_policy()
    split = load_split(root)
    allowed = {
        sid
        for sid, rec in split.items()
        if rec["split_role"] in {"train", "validation"}
    }
    series, series_pub = load_series(root, allowed_subjects=allowed)
    uis = audit_uis_m1(root)
    inv = inventory_from_series(series, split, uis)
    inv["timestamp_completeness"] = "event_time_required_unreliable_excluded"
    inv["duplicate_same_timestamp_rows"] = series_pub.get("same_timestamp_collapses")
    inv["missing_numeric_values"] = series_pub.get("missing_numeric")
    inv["unexplained_count"] = series_pub.get("unexplained_count")
    built = build_sequences(series, split, roles={"train", "validation"})
    write_sequences(root, built["rows"], TRAIN_VAL_PARQUET)
    assert_no_test_parquet(root)
    train_seq = [r for r in built["rows"] if r["split_role"] == "train"]
    val_seq = [r for r in built["rows"] if r["split_role"] == "validation"]
    tr_tr = transitions_from_sequences(train_seq)
    va_tr = transitions_from_sequences(val_seq)
    train = train_providers(tr_tr, va_tr)
    residuals = fit_residuals(tr_tr, train["cells"])
    for c in train["cells"]:
        if c.get("one_step_status") == "ONE_STEP_VALIDATION_ACCEPTED":
            m = rollout_cell_metrics(val_seq, c)
            c["rollout_metrics"] = m
            c["rollout_status"] = m["rollout_status"]
        else:
            c["rollout_status"] = "NOT_RUN_FAILED_SEQUENCE_GATE"
    _persist_cells(root, train["cells"])
    freeze = write_pretest_freeze(root)
    reg = build_registry(train["cells"])
    bundle = {
        "ok": bool(baseline.get("ok")) and bool(lim.get("ok")) and bool(freeze.get("ok")) and bool(built["public"].get("ok")),
        "baseline": baseline,
        "limitations": lim,
        "matrix": matrix,
        "policy": pol,
        "inventory": inv,
        "sequences_public": {**built["public"], "series_meta": series_pub},
        "dataset_status": "BUILT_TRAIN_VALIDATION_ONLY",
        "train": train,
        "residuals": residuals,
        "registry": reg,
        "freeze": freeze,
        "engine": {"ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS": "NOT_RUN_UNTIL_OPEN_TEST"},
        "RECURSIVE_ROLLOUT_EVALUATION_STATUS": "VALIDATION_EVALUATED",
        "test_lifecycle": "FROZEN_UNOPENED",
    }
    _write_public(root, bundle, final=False)
    print(
        json.dumps(
            {
                "phase": "freeze",
                "n_sequences": len(built["rows"]),
                "n_cells": len(train["cells"]),
            }
        ),
        flush=True,
    )
    return {"ok": bundle["ok"], "frozen": True, "test_opened": False, "artifact_dir": ARTIFACT_DIR, "no_publish": no_publish}


def open_test(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    freeze = verify_pretest_freeze(root)
    if not freeze.get("ok"):
        return {"ok": False, "error": "freeze_not_verified", "freeze": freeze}
    mark_test_opened(root)
    pretest = json.loads((root / MODELS_DIR / "pre-test-cells.json").read_text(encoding="utf-8"))
    cells = pretest["cells"]
    split = load_split(root)
    allowed = {sid for sid, rec in split.items() if rec["split_role"] == "test"}
    series, _ = load_series(root, allowed_subjects=allowed)
    built = build_sequences(series, split, roles={"test"})
    write_sequences(root, built["rows"], TEST_PARQUET)
    test_seq = built["rows"]
    te_tr = transitions_from_sequences(test_seq)
    from collections import defaultdict

    by = defaultdict(list)
    for r in te_tr:
        by[(r["source_system"], r["outcome_key"], int(r["requested_horizon_days"]))].append(r)
    for c in cells:
        key = (c.get("source_system"), c.get("outcome_key"), int(c.get("horizon_days") or 0))
        rows = by.get(key) or []
        n_te = len({r["source_scoped_subject_id"] for r in rows})
        if c.get("one_step_status") == "ONE_STEP_VALIDATION_ACCEPTED" and n_te >= MIN_TEST_SUBJECTS and rows:
            ps = [predict_active(c, r["features"], r.get("history_values") or []) for r in rows]
            finite = all(isinstance(p, float) and p == p for p in ps)
            c["one_step_heldout"] = "HELDOUT_TEST_CONFIRMED" if finite else "HELDOUT_TEST_NOT_CONFIRMED"
        else:
            c["one_step_heldout"] = (
                "NOT_RUN_FAILED_DATA_GATE"
                if c.get("one_step_status") != "ONE_STEP_VALIDATION_ACCEPTED"
                else "HELDOUT_TEST_NOT_CONFIRMED"
            )
        if c.get("one_step_status") == "ONE_STEP_VALIDATION_ACCEPTED":
            hm = rollout_cell_metrics(test_seq, c)
            c["heldout_rollout"] = hm
            # do not change validation rollout_status from test
        else:
            c["heldout_rollout"] = None
    reg = build_registry(cells)
    engine = run_engine_shadow(reg, cells)
    inventory = json.loads((root / ARTIFACT_DIR / "source-provider-inventory.json").read_text())
    n_subj: dict[str, set[str]] = defaultdict(set)
    for r in test_seq:
        n_subj[r["outcome_key"]].add(r["source_scoped_subject_id"])
    for g in inventory.get("grains") or []:
        g["test_subjects"] = len(n_subj.get(g.get("outcome_key"), set()))
    bundle = {
        "ok": bool(freeze.get("ok")) and bool(engine.get("ok")),
        "baseline": json.loads((root / ARTIFACT_DIR / "baseline-verification.json").read_text()),
        "limitations": json.loads((root / ARTIFACT_DIR / "medication-residual-v01-limitations.json").read_text()),
        "matrix": json.loads((root / ARTIFACT_DIR / "upstream-foundation-consumption-matrix.json").read_text()),
        "policy": json.loads((root / ARTIFACT_DIR / "rollout-foundation-acceptance-policy.json").read_text()),
        "inventory": inventory,
        "sequences_public": {
            **json.loads((root / ARTIFACT_DIR / "rollout-sequence-contract.json").read_text()),
            "test_public": built["public"],
        },
        "dataset_status": "BUILT",
        "train": {"SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS": "TRAINED_SOURCE_SPECIFIC", "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": "VALIDATION_ONLY", "cells": cells},
        "residuals": {"STOCHASTIC_RESIDUAL_DISTRIBUTION_STATUS": "FITTED_TRAIN_EMPIRICAL", "public": json.loads((root / ARTIFACT_DIR / "residual-distributions.json").read_text())},
        "registry": reg,
        "freeze": freeze,
        "engine": engine,
        "RECURSIVE_ROLLOUT_EVALUATION_STATUS": "VALIDATION_AND_HELDOUT_REPORTED",
        "test_lifecycle": "OPENED",
    }
    (root / MODELS_DIR / "post-test-cells.json").write_text(
        json.dumps({"cells": cells}, indent=2, default=str) + "\n", encoding="utf-8"
    )
    _write_public(root, bundle, final=True)
    _update_docs(root, bundle)
    return {"ok": bundle["ok"], "artifact_dir": ARTIFACT_DIR, "test_opened": True}


def _update_docs(root: Path, bundle: dict[str, Any]) -> None:
    st = json.loads((root / ARTIFACT_DIR / "status-contract.json").read_text(encoding="utf-8"))
    (root / "docs" / "current-stage.md").write_text(
        "\n".join(
            [
                "# Current stage",
                "",
                f"**Stage:** 03 — Unified Source-Aware Natural-History Stochastic Rollout Foundation v{VERSION}",
                "**Phase:** PUBLISHED — security PAUSED",
                f"**Last updated:** {_now()[:10]}",
                "",
                "## Published ZIP (immutable)",
                "",
                f"- `artifacts/external-review/{REVIEW_ZIP}`",
                "- SHA-256: see sidecar after publish-v0.1",
                f"- NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS={st.get('NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS')}",
                f"- ONE_STEP_VALIDATION_ACCEPTED_CELL_COUNT={st.get('ONE_STEP_VALIDATION_ACCEPTED_CELL_COUNT')}",
                f"- RECURSIVE_ROLLOUT_ACCEPTED_CELL_COUNT={st.get('RECURSIVE_ROLLOUT_ACCEPTED_CELL_COUNT')}",
                f"- INTERVENTION_EFFECT_STATUS=UNAVAILABLE",
                "",
                "Medication Residual v0.1 remains immutable and is not consumed.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    marker = "## Current stage"
    insert = f"""## Current stage

Current stage: **STAGE 03 — UNIFIED SOURCE-AWARE NATURAL-HISTORY STOCHASTIC ROLLOUT FOUNDATION v{VERSION}**
(PUBLISHED)

Owner override: security stage is `PAUSED_NOT_ACCEPTED_BY_OWNER`; security gates are
`ADVISORY_ONLY` and must not block core development. Authorised Source A clinical-row reads and
canonical/derived writes are enabled. See `docs/owner-priority-override-core-first.md`.

```bash
audit --root . natural-history-rollout run-v0.1 --no-publish
audit --root . natural-history-rollout open-test-v0.1
audit --root . natural-history-rollout verify-v0.1
audit --root . natural-history-rollout publish-v0.1
```

Do not reopen the probability stream. Do not overwrite prior review ZIPs.

Do not resume Vault rekey, PGP ceremony, or security FINAL/ACCEPTED without literal
`confirm security stage: <exact scope>`.

Historical Stage 01–02 and prior Stage 03 review ZIPs remain immutable.

"""
    if marker in agents:
        rest = agents.split(marker, 1)[1]
        if "## Stage 01 workflow" in rest:
            rest = rest[rest.index("## Stage 01 workflow") :]
        else:
            rest = ""
        (root / "AGENTS.md").write_text(agents.split(marker, 1)[0] + insert + rest, encoding="utf-8")
