"""Technical classifier foundation. Labels are not diagnoses."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from human_simulator.integrated_research_runtime_v01.hashes import derive_seed, sha_obj
from human_simulator.integrated_research_runtime_v01.policy import LABEL_STATUSES, N_BOOTSTRAP, SEED, VERSION
from human_simulator.unified_individual_state_v0111.ridge import fit_ridge, predict_ridge

TECHNICAL_LABEL_ID = "NEXT_RECORDED_SOURCE_SPECIFIC_OUTCOME_EXCURSION_WITHIN_HORIZON"
THRESHOLD_PREDECLARED = 0.5


def _now() -> str:
    return datetime.now(UTC).isoformat()


def append_label(registry: list[dict[str, Any]], rec: dict[str, Any]) -> list[dict[str, Any]]:
    status = rec.get("status")
    if status not in LABEL_STATUSES:
        raise ValueError("illegal label status")
    if rec.get("clinical") and status != "DOMAIN_ACCEPTED":
        rec = dict(rec)
        rec["clinical"] = False
        rec["technical"] = True
        rec["status"] = "CANDIDATE_TECHNICAL_LABEL"
    rec["timestamp"] = rec.get("timestamp") or _now()
    rec["evidence_hash"] = sha_obj({k: rec[k] for k in rec if k != "evidence_hash"})
    registry.append(rec)
    return registry


def technical_cannot_become_clinical(registry: list[dict[str, Any]]) -> bool:
    for rec in registry:
        if rec.get("status") != "DOMAIN_ACCEPTED" and rec.get("clinical"):
            return False
        if rec.get("label_id") == TECHNICAL_LABEL_ID and rec.get("clinical"):
            return False
    return True


def _features(row: dict[str, Any]) -> list[float]:
    feat = row.get("features") or {}
    return [
        float(feat.get("persistence_value") or row.get("t0_value") or 0.0),
        float(feat.get("n_prior_outcome_measurements") or 0.0),
        float(feat.get("days_since_previous") or 0.0),
        float(feat.get("history_depth") or 0.0),
        float(feat.get("requested_horizon_days") or row.get("requested_horizon_days") or 0.0),
    ]


def _excursions(rows: list[dict[str, Any]]) -> None:
    by: dict[tuple[str, str], list[float]] = defaultdict(list)
    train = [r for r in rows if r.get("split_role") == "train"]
    for r in train:
        by[(r["source_system"], r["outcome_key"])].append(abs(float(r.get("oof_residual") or r.get("observed") or 0.0)))
    q90 = {k: sorted(v)[int(0.9 * (len(v) - 1))] if v else 0.0 for k, v in by.items()}
    for r in rows:
        key = (r["source_system"], r["outcome_key"])
        thr = q90.get(key, 0.0)
        resid = abs(float(r.get("oof_residual") or 0.0))
        r["label"] = int(resid > thr and thr > 0)


def _auc(scores: list[float], y: list[int]) -> float:
    pairs = sorted(zip(scores, y, strict=True), key=lambda z: z[0])
    pos = sum(y)
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    rank_sum = 0.0
    for i, (_s, lab) in enumerate(pairs, start=1):
        if lab == 1:
            rank_sum += i
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def _auprc(scores: list[float], y: list[int]) -> float:
    pairs = sorted(zip(scores, y, strict=True), key=lambda z: -z[0])
    tp = 0
    fp = 0
    pos = sum(y)
    if pos == 0:
        return float("nan")
    acc = 0.0
    prev_rec = 0.0
    for s, lab in pairs:
        if lab == 1:
            tp += 1
        else:
            fp += 1
        prec = tp / (tp + fp)
        rec = tp / pos
        acc += prec * (rec - prev_rec)
        prev_rec = rec
    return acc


def _brier(scores: list[float], y: list[int]) -> float:
    return sum((s - lab) ** 2 for s, lab in zip(scores, y, strict=True)) / len(y)


def _bootstrap_auc(scores: list[float], y: list[int], groups: list[str]) -> dict[str, Any]:
    by: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for s, lab, g in zip(scores, y, groups, strict=True):
        by[g].append((s, lab))
    keys = list(by)
    rng = random.Random(SEED)
    stats = []
    for _ in range(N_BOOTSTRAP):
        draw = [keys[rng.randrange(len(keys))] for _ in keys]
        ss: list[float] = []
        yy: list[int] = []
        for k in draw:
            for a, b in by[k]:
                ss.append(a)
                yy.append(b)
        val = _auc(ss, yy)
        if math.isfinite(val):
            stats.append(val)
    stats.sort()
    if not stats:
        return {"lo": None, "hi": None}
    return {"lo": stats[int(0.025 * (len(stats) - 1))], "hi": stats[int(0.975 * (len(stats) - 1))], "n_groups": len(keys)}


def run_classifier(rows: list[dict[str, Any]]) -> dict[str, Any]:
    registry: list[dict[str, Any]] = []
    append_label(
        registry,
        {
            "label_id": TECHNICAL_LABEL_ID,
            "label_type": "RECORDED_EVENT",
            "technical": True,
            "clinical": False,
            "definition": "Recorded source-specific outcome residual exceeds train-only 90th absolute residual at the requested horizon.",
            "observable_evidence": "source-local residual vs frozen marginal",
            "source_applicability": "A_and_B_separately",
            "reviewer": "runtime_v0.1",
            "status": "CANDIDATE_TECHNICAL_LABEL",
            "supersedes": None,
        },
    )
    _excursions(rows)
    by_source: dict[str, dict[str, Any]] = {}
    any_signal = False
    for ss in sorted({r["source_system"] for r in rows}):
        src_rows = [r for r in rows if r["source_system"] == ss and "label" in r]
        train = [r for r in src_rows if r["split_role"] == "train"]
        val = [r for r in src_rows if r["split_role"] == "validation"]
        if len(train) < 40 or len(val) < 20:
            by_source[ss] = {"status": "NOT_RUN_FAILED_DATA_GATE"}
            continue
        xtr = [_features(r) for r in train]
        ytr = [r["label"] for r in train]
        model = fit_ridge(xtr, [float(y) for y in ytr], l2=0.1)
        def logit_scores(recs: list[dict[str, Any]]) -> list[float]:
            out = []
            for r in recs:
                z = predict_ridge(model, _features(r))
                out.append(1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, z)))))
            return out
        val_s = logit_scores(val)
        yv = [r["label"] for r in val]
        prev = sum(yv) / len(yv)
        base = [prev] * len(yv)
        auroc = _auc(val_s, yv)
        auprc = _auprc(val_s, yv)
        brier = _brier(val_s, yv)
        brier_base = _brier(base, yv)
        pred = [int(s >= THRESHOLD_PREDECLARED) for s in val_s]
        tp = sum(1 for a, b in zip(pred, yv, strict=True) if a == 1 and b == 1)
        tn = sum(1 for a, b in zip(pred, yv, strict=True) if a == 0 and b == 0)
        fp = sum(1 for a, b in zip(pred, yv, strict=True) if a == 1 and b == 0)
        fn = sum(1 for a, b in zip(pred, yv, strict=True) if a == 0 and b == 1)
        sens = tp / (tp + fn) if tp + fn else float("nan")
        spec = tn / (tn + fp) if tn + fp else float("nan")
        boot = _bootstrap_auc(val_s, yv, [str(r.get("effective_overlap_group_id") or "") for r in val])
        incremental = math.isfinite(brier) and brier < brier_base - 1e-4 and math.isfinite(auroc) and auroc > 0.55
        any_signal = any_signal or incremental
        by_source[ss] = {
            "n_train": len(train),
            "n_val": len(val),
            "prevalence": prev,
            "auroc": auroc,
            "auprc": auprc,
            "brier": brier,
            "brier_baseline": brier_base,
            "threshold_predeclared": THRESHOLD_PREDECLARED,
            "sensitivity": sens,
            "specificity": spec,
            "bootstrap": boot,
            "incremental_vs_probability_baseline": incremental,
            "threshold_selected_on_test": False,
        }
    status = (
        "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL"
        if not any_signal
        else "EVALUATED_CANDIDATE_TECHNICAL_ONLY"
    )
    return {
        "version": VERSION,
        "CLASSIFIER_LABEL_ONTOLOGY_STATUS": "BUILT",
        "CLASSIFIER_DOMAIN_REVIEW_WORKBENCH_STATUS": "BUILT",
        "TRAJECTORY_EVENT_CLASSIFIER_STATUS": status,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_ACCEPTED",
        "label": TECHNICAL_LABEL_ID,
        "not_a_diagnosis": True,
        "registry_public": [
            {k: v for k, v in rec.items() if k not in {"observable_evidence"}}
            for rec in registry
        ],
        "by_source": by_source,
        "technical_cannot_become_clinical": technical_cannot_become_clinical(registry),
        "ok": True,
    }
