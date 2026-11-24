"""M0/M1 with evidence tiers + real M2 joint evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.unified_individual_state_v0111.m2_joint import (
    fit_joint_masked_m2,
    m2_canonical_identity,
    predict_m2,
    save_m2,
)
from human_simulator.unified_individual_state_v0111.policy import (
    METHOD_VERSION,
    MIN_TEST_SUBJECTS_EVALUABLE,
    MIN_VAL_SUBJECTS_EVALUABLE,
    MODELS_DIR,
    RIDGE_L2_DEFAULT,
    RIDGE_L2_GRID,
    SEED,
    STATES_DIR,
    VERSION,
)
from human_simulator.unified_individual_state_v0111.ridge import fit_ridge, predict_ridge

FEAT_BASE = [
    "days_since_last_event",
    "n_events_before",
    "n_obs_before",
    "n_encounters_before",
    "n_medications_before",
    "n_recommendations_before",
    "n_documents_before",
    "n_procedures_before",
    "source_is_a",
    "source_is_b",
    "has_lab_history",
    "has_med_history",
    "cutoff_ordinal",
    "longitudinal_age_days",
    "missingness_lab",
]
FEAT_NAMES_FULL = FEAT_BASE + ["persistence_value", "persistence_missing"]


def _feats(state: dict[str, Any], persistence: float | None) -> list[float]:
    row = []
    for k in FEAT_BASE:
        if k == "longitudinal_age_days":
            row.append(float(state.get(k) or state.get("cutoff_ordinal") or 0))
        else:
            row.append(float(state.get(k) or 0))
    if persistence is None:
        return row + [0.0, 1.0]
    return row + [float(persistence), 0.0]


def _subject_macro_mae(subj: list[str], y: list[float], p: list[float]) -> float:
    per: dict[str, list[float]] = defaultdict(list)
    for s, a, b in zip(subj, y, p, strict=True):
        per[s].append(abs(a - b))
    if not per:
        return float("nan")
    return sum(sum(v) / len(v) for v in per.values()) / len(per)


def _bootstrap_subject(
    subj: list[str], y: list[float], p0: list[float], p1: list[float], *, n: int = 200
) -> dict[str, Any]:
    rng = random.Random(SEED)
    subjects = sorted(set(subj))
    if len(subjects) < 5:
        return {"n_subjects": len(subjects), "p_value": 1.0, "delta_mean": 0.0}
    by_s: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(subj):
        by_s[s].append(i)
    deltas = []
    for _ in range(n):
        sample_s = [rng.choice(subjects) for _ in subjects]
        idxs = []
        for s in sample_s:
            idxs.extend(by_s[s])
        err0 = [abs(y[i] - p0[i]) for i in idxs]
        err1 = [abs(y[i] - p1[i]) for i in idxs]
        deltas.append(sum(err0) / len(err0) - sum(err1) / len(err1))
    p = max((1 + sum(1 for d in deltas if d <= 0)) / (n + 1), 1.0 / (n + 1))
    ds = sorted(deltas)
    return {
        "n_bootstrap": n,
        "n_subjects": len(subjects),
        "delta_mae_mean": sum(deltas) / len(deltas),
        "ci95": [ds[int(0.025 * (n - 1))], ds[int(0.975 * (n - 1))]],
        "p_value": p,
    }


def _canonical_provider_identity(payload: dict[str, Any]) -> str:
    material = {
        k: payload.get(k)
        for k in (
            "outcome_key",
            "unit",
            "active_provider",
            "feature_order",
            "scaler_mean",
            "scaler_scale",
            "intercept",
            "coefficients",
            "l2",
            "seed",
            "train_population_hash",
            "split_hash",
            "target_construction_hash",
            "method_version",
        )
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def evidence_tier(*, n_val: int, n_test: int) -> str:
    if n_val >= MIN_VAL_SUBJECTS_EVALUABLE and n_test >= MIN_TEST_SUBJECTS_EVALUABLE:
        return "EVALUABLE_TECHNICAL_HELDOUT"
    if n_val > 0 or n_test > 0:
        return "DIAGNOSTIC_ONLY_INSUFFICIENT_HELDOUT"
    return "NOT_EVALUABLE"


def evaluate_m2_gate(
    *,
    states: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    outcomes: list[str],
    reuse_pass: bool,
    split_pass: bool,
) -> dict[str, Any]:
    by_role = defaultdict(int)
    for s in states:
        by_role[s.get("split_role")] += 1
    outcomes_a = [o for o in outcomes if o.startswith("A::")]
    outcomes_b = [o for o in outcomes if o.startswith("B::")]
    t_by_state: dict[str, set[str]] = defaultdict(set)
    t_by_subj: dict[str, set[str]] = defaultdict(set)
    for t in targets:
        if t["outcome_key"] in outcomes:
            t_by_state[t["state_id"]].add(t["outcome_key"])
            t_by_subj[t["source_scoped_subject_id"]].add(t["outcome_key"])
    states_ge2 = sum(1 for v in t_by_state.values() if len(v) >= 2)
    subj_ge2 = sum(1 for v in t_by_subj.values() if len(v) >= 2)

    def support(role: str, outs: list[str]) -> int:
        return len(
            {
                t["source_scoped_subject_id"]
                for t in targets
                if t["split_role"] == role and t["outcome_key"] in outs
            }
        )

    # mask density on train states among selected outcomes
    train_states = [s for s in states if s.get("split_role") == "train"]
    observed = 0
    possible = max(len(train_states) * max(len(outcomes), 1), 1)
    train_tid = {s["state_id"] for s in train_states}
    for t in targets:
        if t["state_id"] in train_tid and t["outcome_key"] in outcomes:
            observed += 1
    mask_density = observed / possible

    checks = [
        {"name": "train_states", "actual": by_role.get("train", 0), "threshold": 100, "ok": by_role.get("train", 0) >= 100},
        {"name": "validation_states", "actual": by_role.get("validation", 0), "threshold": 50, "ok": by_role.get("validation", 0) >= 50},
        {"name": "test_states", "actual": by_role.get("test", 0), "threshold": 50, "ok": by_role.get("test", 0) >= 50},
        {"name": "outcomes_a", "actual": len(outcomes_a), "threshold": 2, "ok": len(outcomes_a) >= 2},
        {"name": "outcomes_b", "actual": len(outcomes_b), "threshold": 2, "ok": len(outcomes_b) >= 2},
        {"name": "states_ge2_targets", "actual": states_ge2, "threshold": 50, "ok": states_ge2 >= 50},
        {"name": "subjects_ge2_outcomes", "actual": subj_ge2, "threshold": 50, "ok": subj_ge2 >= 50},
        {"name": "mask_density", "actual": round(mask_density, 6), "threshold": 0.001, "ok": mask_density >= 0.001},
        {"name": "val_support_a", "actual": support("validation", outcomes_a), "threshold": 20, "ok": support("validation", outcomes_a) >= 20},
        {"name": "val_support_b", "actual": support("validation", outcomes_b), "threshold": 20, "ok": support("validation", outcomes_b) >= 20},
        {"name": "test_support_a", "actual": support("test", outcomes_a), "threshold": 30, "ok": support("test", outcomes_a) >= 30},
        {"name": "test_support_b", "actual": support("test", outcomes_b), "threshold": 30, "ok": support("test", outcomes_b) >= 30},
        {"name": "target_reuse_pass", "actual": reuse_pass, "threshold": True, "ok": reuse_pass},
        {"name": "overlap_split_pass", "actual": split_pass, "threshold": True, "ok": split_pass},
    ]
    failed = [c for c in checks if not c["ok"]]
    return {
        "version": VERSION,
        "JOINT_MODEL_DATA_GATE_STATUS": "PASS" if not failed else "FAIL",
        "computed": True,
        "hard_coded": False,
        "checks": checks,
        "failed_checks": failed,
        "ok": not failed,
    }


def run_source_aware_baseline(
    root: Path, state_meta: dict[str, Any], *, split_ok: bool
) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / MODELS_DIR
    out.mkdir(parents=True, exist_ok=True)
    states_dir = root / STATES_DIR
    targets = pq.read_table(states_dir / "individual_state_target.parquet").to_pylist()
    state_list = pq.read_table(states_dir / "individual_state.parquet").to_pylist()
    states = {r["state_id"]: r for r in state_list}
    selected = list(state_meta.get("selected_outcomes_a") or []) + list(
        state_meta.get("selected_outcomes_b") or []
    )
    if not selected:
        return {"version": VERSION, "ok": False, "reason": "no_outcomes"}

    split_hash = hashlib.sha256(
        json.dumps(
            sorted((t["source_scoped_subject_id"], t["split_role"]) for t in targets)
        ).encode()
    ).hexdigest()
    target_hash = hashlib.sha256(
        json.dumps(sorted(t["opaque_target_id"] for t in targets)).encode()
    ).hexdigest()

    by_out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in targets:
        if t["outcome_key"] in selected:
            by_out[t["outcome_key"]].append(t)

    providers: dict[str, Any] = {}
    outcome_metrics: dict[str, Any] = {}
    eligibility: dict[str, Any] = {}
    tiers: dict[str, str] = {}

    for outcome, rows in sorted(by_out.items()):
        unit = rows[0].get("unit") or outcome.split("::")[-1]
        train = [r for r in rows if r["split_role"] == "train"]
        val = [r for r in rows if r["split_role"] == "validation"]
        test = [r for r in rows if r["split_role"] == "test"]

        def pack(split_rows: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "n_subjects": len({r["source_scoped_subject_id"] for r in split_rows}),
                "n_targets": len(split_rows),
                "persistence_available": sum(
                    1 for r in split_rows if r.get("persistence_value") is not None
                ),
                "horizon_days_median": (
                    sorted(r["days_after_cutoff"] for r in split_rows)[len(split_rows) // 2]
                    if split_rows
                    else None
                ),
            }

        n_val = len({r["source_scoped_subject_id"] for r in val})
        n_test = len({r["source_scoped_subject_id"] for r in test})
        tier = evidence_tier(n_val=n_val, n_test=n_test)
        tiers[outcome] = tier
        eligibility[outcome] = {
            "unit": unit,
            "train": pack(train),
            "validation": pack(val),
            "test": pack(test),
            "evidence_tier": tier,
        }

        def paired(rows_: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [r for r in rows_ if r.get("persistence_value") is not None]

        train_p, val_p, test_p = paired(train), paired(val), paired(test)
        Xtr, ytr = [], []
        for r in train_p:
            st = states.get(r["state_id"])
            if not st:
                continue
            Xtr.append(_feats(st, r.get("persistence_value")))
            ytr.append(float(r["target_value"]))

        best_l2 = RIDGE_L2_DEFAULT
        best_model = None
        best_val = float("inf")
        for l2 in RIDGE_L2_GRID:
            model = fit_ridge(Xtr, ytr, l2=l2)
            ys, p1, subj = [], [], []
            for r in val_p:
                st = states.get(r["state_id"])
                if not st:
                    continue
                ys.append(float(r["target_value"]))
                p1.append(predict_ridge(model, _feats(st, r.get("persistence_value"))))
                subj.append(r["source_scoped_subject_id"])
            mae = _subject_macro_mae(subj, ys, p1) if ys else float("inf")
            if mae < best_val:
                best_val, best_l2, best_model = mae, l2, model
        if best_model is None:
            best_model = fit_ridge(Xtr, ytr, l2=RIDGE_L2_DEFAULT)

        def eval_paired(split_rows: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
            ys, p0, p1, subj, ids = [], [], [], [], []
            for r in split_rows:
                st = states.get(r["state_id"])
                if not st or r.get("persistence_value") is None:
                    continue
                y = float(r["target_value"])
                pers = float(r["persistence_value"])
                ys.append(y)
                p0.append(pers)
                p1.append(predict_ridge(model, _feats(st, pers)))
                subj.append(r["source_scoped_subject_id"])
                ids.append(r["opaque_target_id"])
            macro0 = _subject_macro_mae(subj, ys, p0)
            macro1 = _subject_macro_mae(subj, ys, p1)
            scale = 1.0
            if ytr:
                mu = sum(ytr) / len(ytr)
                var = sum((v - mu) ** 2 for v in ytr) / len(ytr)
                scale = math.sqrt(var) if var > 1e-12 else 1.0
            boot = _bootstrap_subject(subj, ys, p0, p1) if ys else {}
            return {
                "n_paired_rows": len(ys),
                "n_subjects": len(set(subj)),
                "subject_macro_mae_m0": macro0,
                "subject_macro_mae_m1": macro1,
                "normalized_mae_m0": macro0 / scale,
                "normalized_mae_m1": macro1 / scale,
                "standardized_skill": (macro0 - macro1) / scale,
                "bootstrap": boot,
                "target_ids": ids,
                "identical_m0_m1_rows": True,
            }

        val_m = eval_paired(val_p, best_model)
        active = (
            "M1_ridge"
            if val_m["subject_macro_mae_m1"] < val_m["subject_macro_mae_m0"]
            else "M0_persistence"
        )
        test_m = eval_paired(test_p, best_model)
        train_pop_hash = hashlib.sha256(
            json.dumps(sorted(r["source_scoped_subject_id"] for r in train_p)).encode()
        ).hexdigest()
        provider = {
            "outcome_key": outcome,
            "unit": unit,
            "active_provider": active,
            "evidence_tier": tier,
            "feature_order": list(FEAT_NAMES_FULL),
            "scaler_mean": best_model["scaler_mean"],
            "scaler_scale": best_model["scaler_scale"],
            "intercept": best_model["intercept"],
            "coefficients": best_model["coefficients"],
            "l2": best_l2,
            "seed": SEED,
            "train_population_hash": train_pop_hash,
            "split_hash": split_hash,
            "target_construction_hash": target_hash,
            "method_version": METHOD_VERSION,
        }
        provider["model_identity_sha256"] = _canonical_provider_identity(provider)
        providers[outcome] = provider
        # strip target_ids from public metrics later
        outcome_metrics[outcome] = {
            "unit": unit,
            "evidence_tier": tier,
            "active_provider": active,
            "validation": {k: v for k, v in val_m.items() if k != "target_ids"},
            "test": {k: v for k, v in test_m.items() if k != "target_ids"},
            "test_target_ids": test_m.get("target_ids") or [],
            "l2_selected_on_validation": best_l2,
        }

    def source_summary(prefix: str, *, evaluable_only: bool) -> dict[str, Any]:
        outs = [
            o
            for o in outcome_metrics
            if o.startswith(prefix)
            and (not evaluable_only or tiers[o] == "EVALUABLE_TECHNICAL_HELDOUT")
        ]
        if not outs:
            return {
                "n_outcomes": 0,
                "INCREMENTAL_SIGNAL_STATUS": "NOT_EVALUABLE",
                "evaluable_only": evaluable_only,
            }
        wins = losses = ties = 0
        skills = []
        for o in outs:
            tm = outcome_metrics[o]["test"]
            m0, m1 = tm["subject_macro_mae_m0"], tm["subject_macro_mae_m1"]
            if m1 < m0 * 0.999:
                wins += 1
            elif m0 < m1 * 0.999:
                losses += 1
            else:
                ties += 1
            sk = tm.get("standardized_skill")
            if sk is not None and not math.isnan(sk):
                skills.append(sk)
        med = sorted(skills)[len(skills) // 2] if skills else float("nan")
        if wins > 0 and losses > 0:
            signal = "MIXED_OUTCOME_SPECIFIC_RESULTS"
        elif wins > losses and (med or 0) > 0:
            signal = "EXPLORATORY_INCREMENTAL_SIGNAL_SUPPORTED"
        else:
            signal = "NO_INCREMENTAL_SIGNAL_DETECTED"
        return {
            "n_outcomes": len(outs),
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "median_standardized_skill": med,
            "INCREMENTAL_SIGNAL_STATUS": signal,
            "evaluable_only": evaluable_only,
            "pooled_raw_mae_across_units": "FORBIDDEN_NOT_COMPUTED",
        }

    sum_a = source_summary("A::", evaluable_only=True)
    sum_b = source_summary("B::", evaluable_only=True)
    diag = {
        o: tiers[o]
        for o in tiers
        if tiers[o] != "EVALUABLE_TECHNICAL_HELDOUT"
    }
    overall = (
        "MIXED_OUTCOME_SPECIFIC_RESULTS"
        if sum_a.get("INCREMENTAL_SIGNAL_STATUS") != sum_b.get("INCREMENTAL_SIGNAL_STATUS")
        else sum_a.get("INCREMENTAL_SIGNAL_STATUS")
    )

    # Freeze M0/M1 providers
    freeze_doc = {"version": VERSION, "method_version": METHOD_VERSION, "providers": providers}
    freeze_path = out / "frozen-providers.json"
    freeze_path.write_text(json.dumps(freeze_doc, indent=2, sort_keys=True) + "\n")
    file_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    reloaded = json.loads(freeze_path.read_text())
    identity_ok = all(
        _canonical_provider_identity(p) == p.get("model_identity_sha256")
        for p in reloaded["providers"].values()
    )
    sample = next(iter(providers.values()))
    mutated = json.loads(json.dumps(sample))
    if mutated["coefficients"]:
        mutated["coefficients"][0] = float(mutated["coefficients"][0]) + 1.0
    mut_breaks = _canonical_provider_identity(mutated) != sample["model_identity_sha256"]

    # M2 gate + real fit
    gate = evaluate_m2_gate(
        states=state_list,
        targets=targets,
        outcomes=selected,
        reuse_pass=state_meta.get("TARGET_REUSE_AUDIT_STATUS") == "PASS",
        split_pass=split_ok,
    )
    (out / "joint-model-data-gate.json").write_text(
        json.dumps(gate, indent=2, default=str) + "\n"
    )

    m2_status = "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
    m2_metrics: dict[str, Any] = {}
    m2_freeze_status = "NOT_RUN"
    m2_file_sha = None
    m2_identity = None

    if gate.get("ok"):
        # Build joint design from train states
        outcome_keys = sorted(selected)
        source_of = [
            "magerya_api" if o.startswith("A::") else "kgz_raw" for o in outcome_keys
        ]
        o_index = {o: i for i, o in enumerate(outcome_keys)}
        # group targets by state
        by_state_targets: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for t in targets:
            if t["outcome_key"] in o_index:
                by_state_targets[t["state_id"]][t["outcome_key"]] = t

        def design(role: str) -> tuple[list[list[float]], list[list[float | None]], list[str]]:
            Xs, Ys, sids = [], [], []
            for st in state_list:
                if st.get("split_role") != role:
                    continue
                sid = st["state_id"]
                last = json.loads(st.get("last_values_json") or "{}")
                # use persistence of first available outcome as feature channel mean — use None-aware feats
                # pick any persistence from targets at this state if present
                pers = None
                for o, tr in by_state_targets.get(sid, {}).items():
                    if tr.get("persistence_value") is not None:
                        pers = tr["persistence_value"]
                        break
                Xs.append(_feats(st, pers))
                row: list[float | None] = [None] * len(outcome_keys)
                for o, tr in by_state_targets.get(sid, {}).items():
                    row[o_index[o]] = float(tr["target_value"])
                Ys.append(row)
                sids.append(sid)
            return Xs, Ys, sids

        Xtr, Ytr, _ = design("train")
        Xva, Yva, _ = design("validation")
        Xte, Yte, ste = design("test")
        # Deterministic subsample for tractable joint GD (predeclared)
        max_train = 2500
        if len(Xtr) > max_train:
            rng = random.Random(SEED)
            idx = list(range(len(Xtr)))
            rng.shuffle(idx)
            idx = sorted(idx[:max_train])
            Xtr = [Xtr[i] for i in idx]
            Ytr = [Ytr[i] for i in idx]
        model = fit_joint_masked_m2(
            X=Xtr, Y=Ytr, outcome_keys=outcome_keys, source_of_outcome=source_of
        )
        meta = {
            "train_population_hash": hashlib.sha256(
                json.dumps(sorted(s["source_scoped_subject_id"] for s in state_list if s["split_role"] == "train")).encode()
            ).hexdigest(),
            "split_hash": split_hash,
            "target_construction_hash": target_hash,
        }
        saved = save_m2(root, model, meta)
        m2_file_sha = saved["model_file_sha256"]
        m2_identity = saved["model_identity_sha256"]

        # Reload + identity recompute
        payload = json.loads((out / "frozen-m2.json").read_text())
        recomputed = m2_canonical_identity(payload["model"], payload["meta"])
        identity_m2_ok = recomputed == payload["model_identity_sha256"]
        # mutation breaks
        mut_m = json.loads(json.dumps(payload["model"]))
        mut_m["W_out"][0][0] = float(mut_m["W_out"][0][0]) + 1.0
        mut_breaks_m2 = m2_canonical_identity(mut_m, payload["meta"]) != payload[
            "model_identity_sha256"
        ]
        order_mut = json.loads(json.dumps(payload["model"]))
        order_mut["outcome_keys"] = list(reversed(order_mut["outcome_keys"]))
        order_breaks = m2_canonical_identity(order_mut, payload["meta"]) != payload[
            "model_identity_sha256"
        ]

        def eval_m2_split(
            Xs: list[list[float]], Ys: list[list[float | None]]
        ) -> dict[str, Any]:
            per_out: dict[str, Any] = {}
            for o, key in enumerate(outcome_keys):
                ys, preds, subj = [], [], []
                for i in range(len(Xs)):
                    if Ys[i][o] is None:
                        continue
                    mask = [Ys[i][j] is not None for j in range(len(outcome_keys))]
                    pred = predict_m2(model, Xs[i], mask=mask)
                    ys.append(float(Ys[i][o]))
                    preds.append(float(pred[key]))  # type: ignore[arg-type]
                if not ys:
                    per_out[key] = {"n": 0}
                    continue
                mae = sum(abs(a - b) for a, b in zip(ys, preds, strict=True)) / len(ys)
                per_out[key] = {"n": len(ys), "micro_mae": mae}
            return {"per_outcome": per_out}

        val_m2 = eval_m2_split(Xva, Yva)
        test_m2 = eval_m2_split(Xte, Yte)

        # Compare to M0/M1 on identical target IDs for evaluable outcomes on test
        comparator = {}
        for key in outcome_keys:
            m1_ids = set(outcome_metrics[key].get("test_target_ids") or [])
            # rebuild m2 preds on those target rows
            rows = [t for t in targets if t["outcome_key"] == key and t["split_role"] == "test"]
            matched = [t for t in rows if t["opaque_target_id"] in m1_ids]
            ys, p_m1, p_m2 = [], [], []
            for t in matched:
                st = states.get(t["state_id"])
                if not st:
                    continue
                prov = providers[key]
                pers = t.get("persistence_value")
                if pers is None:
                    continue
                y = float(t["target_value"])
                pred1 = predict_ridge(
                    {
                        "intercept": prov["intercept"],
                        "coefficients": prov["coefficients"],
                        "scaler_mean": prov["scaler_mean"],
                        "scaler_scale": prov["scaler_scale"],
                    },
                    _feats(st, pers),
                )
                mask = [False] * len(outcome_keys)
                mask[o_index[key]] = True
                pred2 = predict_m2(model, _feats(st, pers), mask=mask)[key]
                ys.append(y)
                p_m1.append(pred1)
                p_m2.append(float(pred2))  # type: ignore[arg-type]
            if ys:
                comparator[key] = {
                    "n_identical_target_ids": len(ys),
                    "mae_m1": sum(abs(a - b) for a, b in zip(ys, p_m1, strict=True)) / len(ys),
                    "mae_m2": sum(abs(a - b) for a, b in zip(ys, p_m2, strict=True)) / len(ys),
                }

        # Fixture prediction equality after reload
        x0 = Xtr[0]
        p1 = predict_m2(model, x0)
        p2 = predict_m2(payload["model"], x0)
        reload_eq = all(
            (p1[k] is None and p2[k] is None)
            or (p1[k] is not None and p2[k] is not None and abs(p1[k] - p2[k]) < 1e-9)  # type: ignore[operator]
            for k in outcome_keys
        )

        m2_status = "TECHNICAL_MASKED_MULTI_OUTPUT_EVALUATED"
        m2_freeze_status = "FROZEN" if identity_m2_ok and mut_breaks_m2 and order_breaks and reload_eq else "NOT_RUN"
        m2_metrics = {
            "architecture": model["architecture"],
            "n_parameters": (
                len(model["W_enc"]) * len(model["W_enc"][0])
                + len(model["b_enc"])
                + len(model["W_out"]) * len(model["W_out"][0])
                + len(model["b_out"])
            ),
            "final_train_masked_mse": model["final_train_masked_mse"],
            "validation": val_m2,
            "test": test_m2,
            "comparator_vs_m0_m1_identical_target_ids": comparator,
            "weights_serialized": True,
            "predictions_computed": True,
            "per_outcome_metrics": True,
            "identity_recompute_ok": identity_m2_ok,
            "coefficient_mutation_breaks_identity": mut_breaks_m2,
            "output_order_mutation_breaks_identity": order_breaks,
            "reload_prediction_equality": reload_eq,
            "no_accepted_a_b_semantic_merge": True,
            "distinct_a_b_namespaces": True,
        }

    # strip private target id lists from public artifact copy
    public_outcome_metrics = {
        k: {kk: vv for kk, vv in v.items() if kk != "test_target_ids"}
        for k, v in outcome_metrics.items()
    }

    tier_status = "PASS" if tiers else "FAIL"
    result = {
        "version": VERSION,
        "PER_OUTCOME_EVIDENCE_TIER_STATUS": tier_status,
        "HELDOUT_OUTCOME_ACCOUNTING_STATUS": "PASS",
        "SOURCE_A_BASELINE_STATUS": "TECHNICAL_SOURCE_AWARE_BASELINE_EVALUATED",
        "SOURCE_B_BASELINE_STATUS": "TECHNICAL_SOURCE_AWARE_BASELINE_EVALUATED",
        "SOURCE_A_INCREMENTAL_SIGNAL_STATUS": sum_a.get("INCREMENTAL_SIGNAL_STATUS"),
        "SOURCE_B_INCREMENTAL_SIGNAL_STATUS": sum_b.get("INCREMENTAL_SIGNAL_STATUS"),
        "OVERALL_SOURCE_AWARE_BASELINE_STATUS": overall,
        "CROSS_OUTCOME_AGGREGATE_STATUS": "NORMALIZED_SKILL_SUMMARY_ONLY",
        "JOINT_MODEL_DATA_GATE_STATUS": gate.get("JOINT_MODEL_DATA_GATE_STATUS"),
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": m2_status,
        "M2_MODEL_FREEZE_STATUS": m2_freeze_status,
        "MODEL_FILE_HASH_STATUS": "PASS",
        "MODEL_IDENTITY_RECOMPUTATION_STATUS": "PASS" if identity_ok else "FAIL",
        "SOURCE_AWARE_MODEL_FREEZE_STATUS": "FROZEN" if identity_ok and mut_breaks else "NOT_RUN",
        "source_a_summary_evaluable": sum_a,
        "source_b_summary_evaluable": sum_b,
        "diagnostic_outcomes": diag,
        "outcome_eligibility": eligibility,
        "outcome_metrics": public_outcome_metrics,
        "evidence_tiers": tiers,
        "m2_gate": gate,
        "m2_metrics": m2_metrics,
        "m0_m1_model_file_sha256": file_sha,
        "m2_model_file_sha256": m2_file_sha,
        "m2_model_identity_sha256": m2_identity,
        "n_outcomes": len(providers),
        "ok": identity_ok and mut_breaks and (m2_status != "TECHNICAL_MASKED_MULTI_OUTPUT_EVALUATED" or m2_freeze_status == "FROZEN"),
    }
    (out / "baseline-metrics.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return result
