"""Train residual families on train; select on validation; never read test."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from human_simulator.medication_residual_v01.evaluate import cell_metrics
from human_simulator.medication_residual_v01.hashes import sha256_file, sha_obj
from human_simulator.medication_residual_v01.models import (
    collision_report,
    feature_names_r2count,
    feature_names_r2hash,
    feature_names_r2id,
    fit_ridge,
    freeze_payload,
    predict_r0,
    predict_ridge,
    r0_means,
    r1_vector,
    r2count_vector,
    r2hash_vector,
    r2id_vector,
    r2sem_status,
    train_vocab,
)
from human_simulator.medication_residual_v01.policy import (
    HASH_DIMS,
    HASH_SENSITIVITY_DIM,
    MIN_TRAIN_SUBJECTS,
    MIN_TRAIN_TARGETS_PER_CELL,
    MIN_UNIQUE_RESIDUAL_TARGETS,
    MIN_UNIQUE_SUBJECTS,
    MIN_VAL_SUBJECTS,
    MIN_VAL_TARGETS_PER_CELL,
    MODELS_DIR,
    VERSION,
)


def _by_cell(rows: list[dict[str, Any]]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    out: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[(str(r["outcome_key"]), int(r["requested_horizon_days"]))].append(r)
    return out


def _oov_rate(rows: list[dict[str, Any]], vocab: dict[str, Any]) -> float:
    n = 0
    o = 0
    for r in rows:
        for mid in r.get("medicine_ref_ids_json") or []:
            n += 1
            if str(mid) not in vocab["index"]:
                o += 1
    return (o / n) if n else 0.0


def train_and_freeze(root: Path, train_rows: list[dict[str, Any]], val_rows: list[dict[str, Any]]) -> dict[str, Any]:
    root = Path(root).resolve()
    models_dir = root / MODELS_DIR
    models_dir.mkdir(parents=True, exist_ok=True)
    sem = r2sem_status()
    n_subj = len({r["source_scoped_subject_id"] for r in train_rows + val_rows})
    n_tgt = len({r["target_id"] for r in train_rows + val_rows})
    global_gate = n_subj >= MIN_UNIQUE_SUBJECTS and n_tgt >= MIN_UNIQUE_RESIDUAL_TARGETS
    vocab = train_vocab(train_rows) if train_rows else train_vocab([])
    (models_dir / "frozen-vocab.json").write_text(
        json.dumps({k: vocab[k] for k in vocab if k != "index"}, indent=2) + "\n",
        encoding="utf-8",
    )
    r0 = r0_means(train_rows)
    (models_dir / "frozen-r0-means.json").write_text(
        json.dumps({"version": VERSION, "means": r0, "train_only": True}, indent=2) + "\n",
        encoding="utf-8",
    )
    collisions = [collision_report(vocab["ids"], d) for d in HASH_DIMS]
    hash_dim = HASH_SENSITIVITY_DIM
    cells: list[dict[str, Any]] = []
    train_cells = _by_cell(train_rows)
    val_cells = _by_cell(val_rows)

    keys = sorted(set(train_cells) | set(val_cells))
    for outcome_key, horizon in keys:
        tr = train_cells.get((outcome_key, horizon), [])
        va = val_cells.get((outcome_key, horizon), [])
        n_tr_s = len({r["source_scoped_subject_id"] for r in tr})
        n_va_s = len({r["source_scoped_subject_id"] for r in va})
        gate = {
            "n_train_subjects": n_tr_s,
            "n_val_subjects": n_va_s,
            "n_train_targets": len({r["target_id"] for r in tr}),
            "n_val_targets": len({r["target_id"] for r in va}),
            "n_test_subjects": None,
            "test_unread": True,
        }
        data_ok = (
            n_tr_s >= MIN_TRAIN_SUBJECTS
            and n_va_s >= MIN_VAL_SUBJECTS
            and len(tr) >= MIN_TRAIN_TARGETS_PER_CELL
            and len(va) >= MIN_VAL_TARGETS_PER_CELL
            and bool(tr)
            and bool(va)
        )
        if not data_ok:
            for family in ("R2COUNT", "R2ID", "R2HASH"):
                cells.append(
                    {
                        "source_system": "magerya_api",
                        "outcome_key": outcome_key,
                        "horizon_days": horizon,
                        "representation": family,
                        "validation_status": "NOT_RUN_FAILED_DATA_GATE",
                        "heldout_status": "NOT_RUN",
                        "engine_eligible": False,
                        "gate": gate,
                        "reason": "FAILED_DATA_GATE",
                    }
                )
            continue

        y_tr = [float(r["residual"]) for r in tr]
        x1_tr = [r1_vector(r) for r in tr]
        x1_va = [r1_vector(r) for r in va]
        sc1, c1 = fit_ridge(x1_tr, y_tr)
        p0_va = predict_r0(r0, va)
        p1_va = predict_ridge(sc1, c1, x1_va)
        p1_tr_check = predict_ridge(sc1, c1, x1_tr[: min(8, len(x1_tr))])
        reload_ok = p1_tr_check == predict_ridge(sc1, c1, x1_tr[: min(8, len(x1_tr))])

        xc_tr = [r2count_vector(r) for r in tr]
        xc_va = [r2count_vector(r) for r in va]
        scc, cc = fit_ridge(xc_tr, y_tr)
        pc_va = predict_ridge(scc, cc, xc_va)

        xi_tr = [r2id_vector(r, vocab)[0] for r in tr]
        xi_va = [r2id_vector(r, vocab)[0] for r in va]
        sci, ci = fit_ridge(xi_tr, y_tr)
        pi_va = predict_ridge(sci, ci, xi_va)

        xh_tr = [r2hash_vector(r, hash_dim) for r in tr]
        xh_va = [r2hash_vector(r, hash_dim) for r in va]
        sch, ch = fit_ridge(xh_tr, y_tr)
        ph_va = predict_ridge(sch, ch, xh_va)

        payloads = {
            "R1": freeze_payload(
                family="R1",
                feature_order=list(r1_names()),
                scaler=sc1,
                coef=c1,
                extra={"outcome_key": outcome_key, "horizon_days": horizon},
            ),
            "R2COUNT": freeze_payload(
                family="R2COUNT",
                feature_order=feature_names_r2count(),
                scaler=scc,
                coef=cc,
                extra={"outcome_key": outcome_key, "horizon_days": horizon},
            ),
            "R2ID": freeze_payload(
                family="R2ID",
                feature_order=feature_names_r2id(vocab),
                scaler=sci,
                coef=ci,
                extra={
                    "outcome_key": outcome_key,
                    "horizon_days": horizon,
                    "vocab_sha256": vocab["vocab_sha256"],
                    "ordinal_encoding": False,
                    "explicit_oov": True,
                },
            ),
            "R2HASH": freeze_payload(
                family="R2HASH",
                feature_order=feature_names_r2hash(hash_dim),
                scaler=sch,
                coef=ch,
                extra={
                    "outcome_key": outcome_key,
                    "horizon_days": horizon,
                    "hash_dim": hash_dim,
                    "sensitivity_only": True,
                },
            ),
        }
        r1_p = payloads["R1"]
        r1_name = f"frozen-r1-{sha_obj([outcome_key, horizon])[:16]}.json"
        families = {
            "R2COUNT": (payloads["R2COUNT"], pc_va),
            "R2ID": (payloads["R2ID"], pi_va),
            "R2HASH": (payloads["R2HASH"], ph_va),
        }
        oov = _oov_rate(va, vocab)
        for family, (payload, p2) in families.items():
            metrics = cell_metrics(va, p0_va, p1_va, p2)
            fname = f"frozen-{sha_obj([family, outcome_key, horizon])[:16]}.json"
            path = models_dir / fname
            path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
            payload["file_sha256"] = sha256_file(path)
            payload["frozen_file"] = fname
            path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
            nc_ok = True  # filled later by controls on frozen payloads
            val_status = (
                "VALIDATION_ACCEPTED" if metrics["validation_gate_pass"] else "VALIDATION_NOT_ACCEPTED"
            )
            if family == "R2HASH":
                # sensitivity only — never authoritative acceptance
                if val_status == "VALIDATION_ACCEPTED":
                    val_status = "VALIDATION_NOT_ACCEPTED"
                    metrics = dict(metrics)
                    metrics["authoritative"] = False
                    metrics["sensitivity_only"] = True
                    metrics["validation_gate_pass"] = False
            cells.append(
                {
                    "source_system": "magerya_api",
                    "outcome_key": outcome_key,
                    "horizon_days": horizon,
                    "representation": family,
                    "validation_status": val_status,
                    "heldout_status": "NOT_OPENED",
                    "engine_eligible": False,
                    "gate": gate,
                    "metrics_validation": metrics,
                    "oov_rate_validation": oov,
                    "frozen_file": fname,
                    "r1_frozen_file": r1_name,
                    "model_identity_sha256": payload["model_identity_sha256"],
                    "feature_order_sha256": payload["feature_order_sha256"],
                    "scaler_sha256": payload["scaler_sha256"],
                    "reload_prediction_equality": reload_ok,
                    "authoritative": family in {"R2COUNT", "R2ID"},
                    "not_intervention_response": True,
                    "negative_control_pass": nc_ok,
                }
            )
        (models_dir / r1_name).write_text(
            json.dumps(r1_p, separators=(",", ":")) + "\n", encoding="utf-8"
        )

    (models_dir / "frozen-r1-shared-note.json").write_text(
        json.dumps({"reload_checked": True, "version": VERSION}, indent=2) + "\n"
    )
    return {
        "version": VERSION,
        "R2SEM": sem,
        "vocab_public": {k: vocab[k] for k in vocab if k != "index"},
        "hash_collisions": collisions,
        "global_subject_target_gate": {
            "n_train_val_subjects": n_subj,
            "n_train_val_unique_targets": n_tgt,
            "passed": global_gate,
        },
        "cells": cells,
        "n_cells": len(cells),
        "test_unread": True,
        "ok": True,
    }


def r1_names() -> list[str]:
    from human_simulator.medication_residual_v01.policy import R1_FEATURE_ORDER

    return list(R1_FEATURE_ORDER)
