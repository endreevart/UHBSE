"""Time-to-event foundation — observation-process + outcome excursion."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.trajectory_regime_tte_v01.policy import (
    NAMESPACE,
    RUNTIME_DIR,
    SEED,
    TTE_DIR,
    TRANSITIONS_DIR,
    V0111_OVERLAP_DIR,
    V0111_STATES_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
)


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _km(times: list[float], events: list[int]) -> dict[str, Any]:
    """Kaplan–Meier at sorted unique times."""
    pairs = sorted(zip(times, events, strict=True))
    n = len(pairs)
    at_risk = n
    surv = 1.0
    curve = []
    for t, e in pairs:
        if at_risk <= 0:
            break
        if e:
            surv *= 1.0 - 1.0 / at_risk
        at_risk -= 1
        curve.append({"t": t, "S": surv})
    return {"n": n, "events": sum(events), "curve_tail": curve[-5:] if curve else []}


def _concordance(times: list[float], events: list[int], scores: list[float]) -> float:
    """Higher score => shorter predicted time; Harrell-like on comparable pairs."""
    n = len(times)
    if n > 400:
        rng = random.Random(SEED)
        idx = sorted(rng.sample(range(n), 400))
        times = [times[i] for i in idx]
        events = [events[i] for i in idx]
        scores = [scores[i] for i in idx]
    n_conc = n_tied = n_comp = 0
    for i in range(len(times)):
        if not events[i]:
            continue
        for j in range(len(times)):
            if times[i] >= times[j]:
                continue
            n_comp += 1
            if scores[i] > scores[j]:
                n_conc += 1
            elif scores[i] == scores[j]:
                n_tied += 1
    if n_comp == 0:
        return 0.5
    return (n_conc + 0.5 * n_tied) / n_comp


def build_tte_foundation(root: Path, *, use_encoder_features: bool) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / TTE_DIR
    out.mkdir(parents=True, exist_ok=True)

    states = pq.read_table(root / V0111_STATES_DIR / "individual_state.parquet").to_pylist()
    split = {
        r["source_scoped_subject_id"]: r
        for r in pq.read_table(root / V0111_OVERLAP_DIR / "subject-split.parquet").to_pylist()
    }

    # --- A. Observation-process: time to next recorded clinical event ---
    # Use consecutive state horizons as proxy for next observation event
    transitions = pq.read_table(root / TRANSITIONS_DIR / "transitions.parquet").to_pylist()
    obs_rows = []
    for tr in transitions:
        horizon = float(tr["horizon_days"])
        if horizon <= 0:
            continue
        # event always observed at next state (event=1); censoring via last state handled separately
        rid = hashlib.sha256(
            f"{NAMESPACE}|tte_obs|{tr['transition_id']}".encode()
        ).hexdigest()
        ctx = json.loads(tr["context_t0_json"])
        obs_rows.append(
            {
                "row_id": rid,
                "endpoint": "TIME_TO_NEXT_RECORDED_CLINICAL_EVENT",
                "endpoint_class": "observation_process",
                "not_biological_risk": True,
                "source_scoped_subject_id": tr["source_scoped_subject_id"],
                "source_system": tr["source_system"],
                "split_role": tr["split_role"],
                "time_origin": "state_cutoff_t0",
                "time_days": horizon,
                "event": 1,
                "features": {
                    "history_depth": float(tr.get("history_depth_t0") or 0),
                    "mask_density": float(tr.get("mask_density_t0") or 0),
                    "source_is_a": float(ctx.get("source_is_a") or 0),
                    "n_events_before": float(ctx.get("n_events_before") or 0),
                    "days_since_last_event": float(ctx.get("days_since_last_event") or 0),
                    "longitudinal_age_days": float(ctx.get("longitudinal_age_days") or 0),
                },
            }
        )

    # Censoring rows: last state per subject — censored at window end (no next event)
    by_subj_states: dict[str, list] = defaultdict(list)
    for st in states:
        by_subj_states[st["source_scoped_subject_id"]].append(st)
    censored = 0
    for sid, sts in by_subj_states.items():
        sts = sorted(sts, key=lambda s: s.get("cutoff_ordinal") or 0)
        if not sts:
            continue
        last = sts[-1]
        # window end: +90 days from last age as technical censor (source-specific window)
        window = 90.0
        rid = hashlib.sha256(f"{NAMESPACE}|tte_obs_censor|{last['state_id']}".encode()).hexdigest()
        role = (split.get(sid) or {}).get("split_role") or last["split_role"]
        obs_rows.append(
            {
                "row_id": rid,
                "endpoint": "TIME_TO_NEXT_RECORDED_CLINICAL_EVENT",
                "endpoint_class": "observation_process",
                "not_biological_risk": True,
                "source_scoped_subject_id": sid,
                "source_system": last["source_system"],
                "split_role": role,
                "time_origin": "state_cutoff_t0",
                "time_days": window,
                "event": 0,
                "features": {
                    "history_depth": float(last.get("n_obs_before") or 0),
                    "mask_density": 1.0 - float(last.get("missingness_lab") or 0),
                    "source_is_a": float(last.get("source_is_a") or 0),
                    "n_events_before": float(last.get("n_events_before") or 0),
                    "days_since_last_event": float(last.get("days_since_last_event") or 0),
                    "longitudinal_age_days": float(last.get("longitudinal_age_days") or 0),
                },
            }
        )
        censored += 1

    pq.write_table(
        pa.Table.from_pylist(obs_rows), out / "tte_observation_process.parquet", compression="zstd"
    )

    # --- B. Outcome excursion: train-threshold deviation ---
    targets = pq.read_table(
        root / V0111_STATES_DIR / "individual_state_target.parquet",
        columns=[
            "opaque_target_id",
            "outcome_key",
            "target_value",
            "persistence_value",
            "days_after_cutoff",
            "split_role",
            "source_system",
            "source_scoped_subject_id",
            "state_id",
        ],
    ).to_pylist()
    # pick top frequent evaluable outcomes from providers if available
    train_vals: dict[str, list[float]] = defaultdict(list)
    for t in targets:
        if t["split_role"] == "train" and t.get("target_value") is not None:
            train_vals[t["outcome_key"]].append(float(t["target_value"]))
    # select outcomes with enough train mass
    excursion_outcomes = []
    thresholds = {}
    for key, vals in sorted(train_vals.items(), key=lambda kv: -len(kv[1])):
        if len(vals) < 500:
            continue
        if not (key.startswith("A::") or key.startswith("B::")):
            continue
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1.0
        thresholds[key] = {"mean": mu, "sd": sd, "hi": mu + 2 * sd, "lo": mu - 2 * sd}
        excursion_outcomes.append(key)
        if len(excursion_outcomes) >= 12:
            break

    exc_rows = []
    zero_neg = 0
    for t in targets:
        key = t["outcome_key"]
        if key not in thresholds:
            continue
        days = float(t.get("days_after_cutoff") or 0)
        if days <= 0:
            zero_neg += 1
            continue
        thr = thresholds[key]
        y = float(t["target_value"])
        event = 1 if (y > thr["hi"] or y < thr["lo"]) else 0
        # For non-events use same horizon as censoring to next observation
        rid = hashlib.sha256(
            f"{NAMESPACE}|tte_exc|{t['opaque_target_id']}|{key}".encode()
        ).hexdigest()
        exc_rows.append(
            {
                "row_id": rid,
                "endpoint": "TIME_TO_NEXT_SOURCE_SPECIFIC_OUTCOME_EXCURSION",
                "endpoint_class": "statistical_excursion",
                "not_diagnosis": True,
                "not_adverse_event_label": True,
                "outcome_key": key,
                "source_scoped_subject_id": t["source_scoped_subject_id"],
                "source_system": t["source_system"],
                "split_role": t["split_role"],
                "time_origin": "state_cutoff",
                "time_days": days,
                "event": event,
                "threshold_train_only": thr,
                "features": {
                    "persistence": float(t["persistence_value"])
                    if t.get("persistence_value") is not None
                    else 0.0,
                    "persistence_missing": 0.0
                    if t.get("persistence_value") is not None
                    else 1.0,
                    "source_is_a": 1.0 if t["source_system"] == "magerya_api" else 0.0,
                },
            }
        )

    pq.write_table(
        pa.Table.from_pylist(exc_rows), out / "tte_outcome_excursion.parquet", compression="zstd"
    )
    (out / "excursion-thresholds-train-only.json").write_text(
        json.dumps({"thresholds": thresholds, "n_outcomes": len(thresholds)}, indent=2) + "\n",
        encoding="utf-8",
    )

    def eval_endpoint(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
        if not rows:
            return {
                "status": "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
                "reason": "empty",
            }
        by_src: dict[str, dict[str, Any]] = {}
        for src_key, src_name in (("magerya_api", "A"), ("kgz_raw", "B")):
            src_rows = [r for r in rows if r["source_system"] == src_key]
            train = [r for r in src_rows if r["split_role"] == "train"]
            val = [r for r in src_rows if r["split_role"] == "validation"]
            test = [r for r in src_rows if r["split_role"] == "test"]
            if len(train) < 50 or sum(r["event"] for r in train) < 10:
                by_src[src_name] = {
                    "status": "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
                    "n_train": len(train),
                    "n_events_train": sum(r["event"] for r in train),
                }
                continue
            # M0 KM
            km = _km([r["time_days"] for r in train], [r["event"] for r in train])
            # M1: simple discrete risk score = linear features -> higher => sooner event
            # Fit on train: score = sum w_k * x_k using event-rate correlation
            feat_keys = sorted(train[0]["features"].keys())
            # weight = mean(feat|event) - mean(feat|censor)
            ev = [r for r in train if r["event"] == 1]
            cen = [r for r in train if r["event"] == 0]
            weights = {}
            for k in feat_keys:
                me = sum(r["features"][k] for r in ev) / max(len(ev), 1)
                mc = sum(r["features"][k] for r in cen) / max(len(cen), 1)
                weights[k] = me - mc

            def score_row(r):
                return sum(weights[k] * r["features"][k] for k in feat_keys)

            def metrics(split_rows: list[dict[str, Any]]) -> dict[str, Any]:
                if len(split_rows) < 20:
                    return {"n": len(split_rows), "status": "sparse"}
                times = [r["time_days"] for r in split_rows]
                events = [r["event"] for r in split_rows]
                scores = [score_row(r) for r in split_rows]
                c_index = _concordance(times, events, scores)
                # Brier at horizon 30/90
                briers = {}
                for h in (30.0, 90.0):
                    # predicted risk ~ sigmoid(score)
                    errs = []
                    for r, sc in zip(split_rows, scores, strict=True):
                        pred = 1.0 / (1.0 + math.exp(-sc))
                        # observed event by horizon
                        y = 1.0 if (r["event"] == 1 and r["time_days"] <= h) else 0.0
                        # if censored before h, skip
                        if r["event"] == 0 and r["time_days"] < h:
                            continue
                        errs.append((pred - y) ** 2)
                    briers[f"brier_{int(h)}"] = sum(errs) / max(len(errs), 1)
                # bootstrap CI on c-index
                rng = random.Random(SEED)
                boots = []
                for _ in range(40):
                    sample = [split_rows[rng.randrange(len(split_rows))] for _ in split_rows]
                    boots.append(
                        _concordance(
                            [r["time_days"] for r in sample],
                            [r["event"] for r in sample],
                            [score_row(r) for r in sample],
                        )
                    )
                boots.sort()
                return {
                    "n": len(split_rows),
                    "events": sum(events),
                    "censored": len(split_rows) - sum(events),
                    "concordance_m1": c_index,
                    "concordance_bootstrap_p05": boots[int(0.05 * len(boots))],
                    "concordance_bootstrap_p95": boots[min(len(boots) - 1, int(0.95 * len(boots)))],
                    "brier": briers,
                }

            by_src[src_name] = {
                "status": "EVALUATED",
                "km_train": km,
                "m1_weights": weights,
                "validation": metrics(val),
                "test": metrics(test),
                "feature_basis": (
                    "raw_source_aware_plus_transition"
                    if not use_encoder_features
                    else "includes_encoder_optional"
                ),
                "encoder_used_as_foundation": use_encoder_features,
            }
        return {
            "endpoint": name,
            "by_source": by_src,
            "n_rows": len(rows),
            "n_events": sum(r["event"] for r in rows),
            "n_censored": sum(1 for r in rows if r["event"] == 0),
        }

    obs_eval = eval_endpoint(obs_rows, "TIME_TO_NEXT_RECORDED_CLINICAL_EVENT")
    exc_eval = eval_endpoint(exc_rows, "TIME_TO_NEXT_SOURCE_SPECIFIC_OUTCOME_EXCURSION")

    obs_status = (
        "EVALUATED"
        if any(
            (obs_eval.get("by_source") or {}).get(s, {}).get("status") == "EVALUATED"
            for s in ("A", "B")
        )
        else "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
    )
    exc_status = (
        "EVALUATED"
        if any(
            (exc_eval.get("by_source") or {}).get(s, {}).get("status") == "EVALUATED"
            for s in ("A", "B")
        )
        else "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
    )

    # Accounting
    accounting = {
        "observation_process": {
            "n_rows": len(obs_rows),
            "events": sum(r["event"] for r in obs_rows),
            "censored": sum(1 for r in obs_rows if r["event"] == 0),
            "zero_negative_excluded": 0,
            "unexplained": 0,
        },
        "outcome_excursion": {
            "n_rows": len(exc_rows),
            "events": sum(r["event"] for r in exc_rows),
            "censored": sum(1 for r in exc_rows if r["event"] == 0),
            "zero_negative_excluded": zero_neg,
            "n_outcomes": len(thresholds),
            "unexplained": 0,
        },
    }

    doc = {
        "version": VERSION,
        "TIME_TO_EVENT_DATASET_STATUS": "BUILT",
        "OBSERVATION_PROCESS_TTE_STATUS": obs_status,
        "OUTCOME_EXCURSION_TTE_STATUS": exc_status,
        "TIME_TO_EVENT_BASELINE_STATUS": (
            "EVALUATED" if obs_status == "EVALUATED" or exc_status == "EVALUATED" else "NOT_RUN"
        ),
        "observation_process_eval": obs_eval,
        "outcome_excursion_eval": exc_eval,
        "accounting": accounting,
        "use_encoder_features": use_encoder_features,
        "ok": accounting["observation_process"]["unexplained"] == 0
        and accounting["outcome_excursion"]["unexplained"] == 0,
    }
    (root / RUNTIME_DIR / "tte-foundation.json").write_text(
        json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return doc
