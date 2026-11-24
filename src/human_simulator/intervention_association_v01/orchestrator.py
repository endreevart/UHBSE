"""Orchestrator for First Technical Medication-Association Baseline v0.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.accounting import (
    assert_reconciliation_status_contract,
    build_component_reconciliation,
)
from human_simulator.intervention_association_v01.baseline_verify import verify_accepted_v011
from human_simulator.intervention_association_v01.compare_1996 import compare_1996_vs_4408
from human_simulator.intervention_association_v01.engine_shadow import run_engine_shadow
from human_simulator.intervention_association_v01.episodes import build_episode_datasets
from human_simulator.intervention_association_v01.evaluate import (
    bootstrap_m2_vs_m1,
    permutation_m2_vs_m1,
    summarize_incremental_signal,
    uncertainty_from_validation,
)
from human_simulator.intervention_association_v01.freeze import freeze_cohort_models
from human_simulator.intervention_association_v01.idempotency import (
    full_source_a_expected_id_coverage_check,
)
from human_simulator.intervention_association_v01.medication_ref import (
    build_medication_reference_report,
)
from human_simulator.intervention_association_v01.models import (
    load_episodes,
    run_baselines_for_cohort,
    split_episodes,
    train_outcome_unit_cohorts,
)
from human_simulator.intervention_association_v01.policy import (
    ARTIFACT_DIR,
    MIN_COHORT_TRAIN_EPISODES,
    MIN_COHORT_TRAIN_SUBJECTS,
    MIN_LEVEL5_EPISODES,
    MIN_LEVEL5_SUBJECTS,
    PRIMARY_HORIZON_DAYS,
    VERSION,
    policy_snapshot,
)
from human_simulator.intervention_association_v01.source_b import discover_source_b_interventions


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = verify_accepted_v011(root)
    _write(art / "baseline-v011-verification.json", baseline)
    if not baseline.get("ok"):
        return {
            "ok": False,
            "error": "accepted_v011_baseline_mismatch",
            "baseline": baseline,
        }

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings
    from human_simulator.unified import source_a_adapter as sa

    with sa.source_a_connection(root) as conn_a, canonical_connection(
        load_canonical_settings()
    ) as conn_c:
        recon = build_component_reconciliation(conn_a, conn_c)
        assert_reconciliation_status_contract(recon)
        _write(art / "source-a-component-reconciliation.json", recon)

        idem = full_source_a_expected_id_coverage_check(root, conn_c)
        _write(art / "source-a-idempotency-method.json", idem)

        cmp1996 = compare_1996_vs_4408(conn_a)
        _write(art / "explain-1996-vs-4408.json", cmp1996)

        med_ref = build_medication_reference_report(conn_a)
        _write(art / "medication-reference-coverage.json", med_ref)

        episodes_doc = build_episode_datasets(root, conn_a)
        _write(art / "medication-episode-dataset-summary.json", episodes_doc)

    # Source B (optional)
    try:
        from human_simulator.unified.source_b_adapter import source_b_connection

        with source_b_connection(root) as conn_b:
            src_b = discover_source_b_interventions(conn_b)
    except Exception as exc:  # noqa: BLE001
        src_b = discover_source_b_interventions(None)
        src_b["connection_error"] = type(exc).__name__
    _write(art / "source-b-intervention-discovery.json", src_b)

    # Modeling on appointment_date primary horizon
    hyp = "appointment_date"
    ep_path = (
        root
        / "private"
        / "intervention-association-v01"
        / "episodes"
        / f"episodes_{hyp}_h{PRIMARY_HORIZON_DAYS}.jsonl"
    )
    created_path = (
        root
        / "private"
        / "intervention-association-v01"
        / "episodes"
        / f"episodes_created_h{PRIMARY_HORIZON_DAYS}.jsonl"
    )

    modeling: dict[str, Any] = {
        "TECHNICAL_MEDICATION_ASSOCIATION_BASELINE_STATUS": "NOT_RUN_GATE_FAILED",
        "cohorts": [],
        "freeze": [],
    }
    freeze_results: list[dict[str, Any]] = []

    if ep_path.is_file():
        episodes = load_episodes(ep_path)
        split = split_episodes(episodes)
        split_pub = {k: v for k, v in split.items() if k != "episodes_by_split"}
        _write(art / "scientific-split.json", split_pub)

        prim = (episodes_doc.get("hypotheses") or {}).get(hyp, {}).get("primary") or {}
        l4_ep = int(prim.get("n_episodes") or 0)
        l4_subj = int(prim.get("n_subjects") or 0)
        cohort_gate = l4_ep >= MIN_LEVEL5_EPISODES and l4_subj >= MIN_LEVEL5_SUBJECTS
        test_gate = bool(split.get("test_size_gate_passed"))
        leakage_ok = (
            split.get("zero_subject_overlap")
            and split.get("zero_episode_overlap")
            and split.get("zero_locator_overlap")
        )

        if cohort_gate and test_gate and leakage_ok:
            train = split["episodes_by_split"]["train"]
            val = split["episodes_by_split"]["validation"]
            test = split["episodes_by_split"]["test"]
            cohorts = train_outcome_unit_cohorts(
                train,
                min_episodes=MIN_COHORT_TRAIN_EPISODES,
                min_subjects=MIN_COHORT_TRAIN_SUBJECTS,
            )
            # Cap to top 5 cohorts for runtime
            cohorts = cohorts[:5]
            if not cohorts:
                # pooled fallback label
                modeling["TECHNICAL_MEDICATION_ASSOCIATION_BASELINE_STATUS"] = (
                    "INSUFFICIENT_DATA"
                )
                modeling["note"] = "No outcome-unit cohort passed train gates"
            else:
                results = []
                for c in cohorts:
                    r = run_baselines_for_cohort(
                        cohort=c, train=train, val=val, test=test
                    )
                    if r.get("status") == "EVALUATED":
                        r["bootstrap"] = bootstrap_m2_vs_m1(
                            r["m1_preds"], r["m2_preds"]
                        )
                        r["permutation"] = permutation_m2_vs_m1(
                            r["m1_preds"], r["m2_preds"]
                        )
                        r["uncertainty"] = uncertainty_from_validation(
                            [],
                            r["m2_preds"],
                            residual_std=float(
                                r["serialized"]["m2"].get("residual_std") or 1.0
                            ),
                        )
                        # negative control
                        sh = run_baselines_for_cohort(
                            cohort=c,
                            train=train,
                            val=val,
                            test=test,
                            shuffle_medication=True,
                        )
                        r["negative_control_shuffle_medication"] = {
                            "m2_mae": (sh.get("m2") or {}).get("pair_micro_mae"),
                            "real_m2_mae": (r.get("m2") or {}).get("pair_micro_mae"),
                        }
                        fr = freeze_cohort_models(
                            art,
                            r,
                            timestamp_hypothesis=hyp,
                            horizon_days=PRIMARY_HORIZON_DAYS,
                        )
                        freeze_results.append(fr)
                        # strip preds from published cohort doc
                        pub = {
                            k: v
                            for k, v in r.items()
                            if k not in ("m1_preds", "m2_preds", "serialized")
                        }
                        pub["freeze"] = {
                            k: fr[k]
                            for k in (
                                "MODEL_FREEZE_STATUS",
                                "file_sha256",
                                "model_identity_sha256",
                                "relative_path",
                                "reload_matches",
                            )
                            if k in fr
                        }
                        results.append(pub)
                modeling["cohorts"] = results
                modeling["TECHNICAL_MEDICATION_ASSOCIATION_BASELINE_STATUS"] = (
                    "EVALUATED" if results else "INSUFFICIENT_DATA"
                )
        else:
            modeling["gate_failures"] = {
                "cohort_size": not cohort_gate,
                "test_size": not test_gate,
                "leakage": not leakage_ok,
                "l4_episodes": l4_ep,
                "l4_subjects": l4_subj,
            }

        # Level-5 update for appointment_date hierarchy
        if episodes_doc.get("hypotheses", {}).get(hyp, {}).get("hierarchy"):
            h = episodes_doc["hypotheses"][hyp]["hierarchy"]
            n5_ep = sum(c.get("n_test", 0) + c.get("n_train", 0) for c in modeling.get("cohorts") or [])
            n5_subj = l4_subj if modeling.get("cohorts") else 0
            h["levels"]["5_model_eligible_after_gates"] = {
                "episodes": n5_ep if modeling.get("cohorts") else 0,
                "subjects": n5_subj if modeling.get("cohorts") else 0,
            }
            h["gates"]["test_size"]["passed"] = test_gate
            h["gates"]["cohort_size"]["passed"] = cohort_gate
            _write(art / "medication-episode-dataset-summary.json", episodes_doc)

    # Timestamp sensitivity (created vs appointment) — metrics compare episode counts
    sens = {
        "MEDICATION_EVENT_TIMESTAMP_STATUS": (
            "TECHNICAL_HYPOTHESES_EVALUATED_DOMAIN_CONFIRMATION_PENDING"
        ),
        "appointment_date": (episodes_doc.get("hypotheses") or {})
        .get("appointment_date", {})
        .get("horizons"),
        "created": (episodes_doc.get("hypotheses") or {}).get("created", {}).get("horizons"),
        "datasets_remain_separate": True,
        "created_path_exists": created_path.is_file(),
        "appointment_path_exists": ep_path.is_file(),
    }
    _write(art / "timestamp-sensitivity.json", sens)

    signal = summarize_incremental_signal(modeling.get("cohorts") or [])
    _write(art / "incremental-medication-context-signal.json", signal)

    freeze_status = (
        "FROZEN"
        if any(f.get("MODEL_FREEZE_STATUS") == "FROZEN" for f in freeze_results)
        else "NOT_FROZEN"
    )
    _write(
        art / "model-freeze.json",
        {
            "MODEL_FREEZE_STATUS": freeze_status,
            "models": freeze_results,
        },
    )
    _write(art / "medication-association-baselines.json", modeling)

    shadow = run_engine_shadow(art)
    _write(art / "engine-shadow-integration.json", shadow)

    statuses = {
        "version": VERSION,
        "generated_at": _now(),
        "EVIDENCE_CORRECTION_STATUS": (
            "PASS"
            if recon.get("SOURCE_A_COMPONENT_RECONCILIATION_STATUS") == "PASS"
            else recon.get("SOURCE_A_COMPONENT_RECONCILIATION_STATUS")
        ),
        "SOURCE_A_COMPONENT_RECONCILIATION_STATUS": recon.get(
            "SOURCE_A_COMPONENT_RECONCILIATION_STATUS"
        ),
        "SOURCE_A_IDEMPOTENCY_STATUS": idem.get("SOURCE_A_IDEMPOTENCY_STATUS"),
        "FULL_SOURCE_A_EXPECTED_ID_COVERAGE_CHECK_STATUS": idem.get(
            "FULL_SOURCE_A_EXPECTED_ID_COVERAGE_CHECK_STATUS"
        ),
        "MEDICATION_EPISODE_DATASET_STATUS": episodes_doc.get(
            "MEDICATION_EPISODE_DATASET_STATUS"
        ),
        "MEDICATION_EVENT_TIMESTAMP_STATUS": episodes_doc.get(
            "MEDICATION_EVENT_TIMESTAMP_STATUS"
        ),
        "TECHNICAL_MEDICATION_ASSOCIATION_BASELINE_STATUS": modeling.get(
            "TECHNICAL_MEDICATION_ASSOCIATION_BASELINE_STATUS"
        ),
        "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": signal.get(
            "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS"
        ),
        "MODEL_FREEZE_STATUS": freeze_status,
        "ENGINE_SHADOW_INTEGRATION_STATUS": shadow.get(
            "ENGINE_SHADOW_INTEGRATION_STATUS"
        ),
        "PUBLICATION_INTEGRITY_STATUS": "PENDING",
        # immutable non-claims
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "SOURCE_B_INTERVENTION_DISCOVERY_STATUS": src_b.get(
            "SOURCE_B_INTERVENTION_DISCOVERY_STATUS"
        ),
        "policy": policy_snapshot(),
        "elapsed_sec": round(time.time() - t0, 2),
    }
    _write(art / "status-contract.json", statuses)

    verification = {
        "ok": True,
        "baseline_ok": baseline.get("ok"),
        "statuses": statuses,
        "component_matches_gap": (recon.get("gap_explained_as") or {}).get("matches_gap"),
    }
    _write(art / "verification.json", verification)

    result: dict[str, Any] = {
        "ok": True,
        "artifact_dir": str(art),
        "statuses": statuses,
        "verification": verification,
        "no_publish": no_publish,
    }
    if not no_publish:
        from human_simulator.intervention_association_v01.publish import publish

        result["publication"] = publish(root)
        statuses["PUBLICATION_INTEGRITY_STATUS"] = result["publication"].get(
            "PUBLICATION_INTEGRITY_STATUS", "FAIL"
        )
        _write(art / "status-contract.json", statuses)
    return result
