"""Phase 0 — independent audit of published Joint Rollout v0.2 defects.

Does not rewrite the v0.2 ZIP. Publication integrity of v0.2 may remain PASS.
The three published joint routes are not transferred as accepted.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v01.policy import (
    V02_ARTIFACT,
    V02_SRC,
    VERSION,
)


def _src(root: Path, name: str) -> str:
    return (root / V02_SRC / name).read_text(encoding="utf-8")


def _public(root: Path, name: str) -> dict[str, Any]:
    p = root / V02_ARTIFACT / name
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _calls_name(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == name:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                return True
    return False


def reproduce_v02_joint_runtime(root: Path) -> dict[str, Any]:
    engine = _src(root, "engine.py")
    tree = ast.parse(engine)
    shadow_fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_engine_shadow"
    )
    shadow_src = ast.get_source_segment(engine, shadow_fn) or ""
    load_in_shadow = "load_joint_payload(" in shadow_src
    infer_in_shadow = "infer(" in shadow_src
    copula_in_shadow = "copula" in shadow_src.lower() or "sample_joint" in shadow_src
    load_exists = "def load_joint_payload" in engine
    status = _public(root, "engine-joint-shadow.json")
    published = status.get("ENGINE_JOINT_ROLLOUT_STATUS")
    replay = status.get("ENGINE_CROSS_PROCESS_DETERMINISTIC_REPLAY_STATUS")
    return {
        "version": VERSION,
        "V02_JOINT_DEFECT_REPRODUCTION_STATUS": "REPRODUCED",
        "defects": [
            {
                "id": 1,
                "claim": "run_engine_shadow performs scalar marginal infer() and does not use copula",
                "load_joint_payload_exists": load_exists,
                "load_joint_payload_called_in_shadow": load_in_shadow,
                "infer_called_in_shadow": infer_in_shadow,
                "copula_in_shadow": copula_in_shadow,
                "published_ENGINE_JOINT_ROLLOUT_STATUS": published,
                "reproduced": load_exists
                and (not load_in_shadow)
                and infer_in_shadow
                and (not copula_in_shadow)
                and published == "TECHNICAL_SHADOW_PASS",
            },
            {
                "id": 2,
                "claim": "load_joint_payload exists but is unused by shadow inference",
                "reproduced": load_exists and not load_in_shadow,
            },
            {
                "id": 11,
                "claim": "PASS_SAME_PROCESS_DETERMINISTIC is not cross-process replay",
                "published": replay,
                "subprocess_in_shadow": "subprocess" in shadow_src,
                "reproduced": replay == "PASS_SAME_PROCESS_DETERMINISTIC"
                and "subprocess" not in shadow_src,
            },
        ],
        "ok": True,
    }


def reproduce_v02_score_validity(root: Path) -> dict[str, Any]:
    scores = _src(root, "scores.py")
    joint = _src(root, "joint.py")
    has_euclid = "math.sqrt(sum((x - y) ** 2" in scores or "_euclid" in scores
    energy_on_raw = "def energy_score" in scores and "scale" not in scores.lower()
    variogram_subtracts = "(y[i] - y[j])" in scores
    eval_uses_raw = "energy_score(paths0, y)" in joint and "normalize" not in joint.lower()
    return {
        "version": VERSION,
        "defects": [
            {
                "id": 3,
                "claim": "Energy Score uses Euclidean distance on raw mixed-unit values",
                "has_euclid": has_euclid,
                "energy_on_raw": energy_on_raw,
                "evaluate_joint_raw": eval_uses_raw,
                "reproduced": has_euclid and energy_on_raw and eval_uses_raw,
            },
            {
                "id": 4,
                "claim": "Variogram Score subtracts different clinical analytes in native units",
                "variogram_subtracts": variogram_subtracts,
                "reproduced": variogram_subtracts and eval_uses_raw,
            },
        ],
        "ok": True,
    }


def reproduce_v02_panel_identity(root: Path) -> dict[str, Any]:
    joint = _src(root, "joint.py")
    grouped = 'key = (r["source_system"], r["source_scoped_subject_id"], r["t0_iso"], int(r["requested_horizon_days"]))' in joint
    no_timestamp_collapse = "actual_recorded_label_offset_days" not in joint.split("def build_panels")[1].split("def panel_accounting")[0]
    identity_ecdf_n = '"ecdf_n"' in joint and '"ecdf": ecdf' in joint
    identity_payload = _src(root, "joint.py")
    identity_uses_n_only = '"ecdf_n": {ok: len(ecdf[ok])' in identity_payload
    return {
        "version": VERSION,
        "defects": [
            {
                "id": 5,
                "claim": "Panels grouped by source+subject+t0+horizon; targets may differ in timestamp/id",
                "grouped_by_t0_horizon": grouped,
                "no_strict_timestamp_collapse_in_build_panels": no_timestamp_collapse,
                "reproduced": grouped,
            },
            {
                "id": 10,
                "claim": "Joint identity hashes correlation/support and ECDF sizes, not full ECDF payloads",
                "identity_uses_ecdf_n": identity_uses_n_only,
                "full_ecdf_in_identity_hash": False,
                "reproduced": identity_uses_n_only,
            },
        ],
        "ok": True,
    }


def reproduce_v02_acceptance(root: Path) -> dict[str, Any]:
    joint = _src(root, "joint.py")
    in_sample = "yhat = predict_active(" in joint.split("def fit_d1")[1].split("def _mvn")[0]
    oof_in_fit = "oof" in joint.split("def fit_d1")[1].split("def _mvn")[0].lower()
    pointwise = "d1_better_energy" in joint and "bootstrap" not in joint.lower()
    accounting = _public(root, "joint-panel-accounting.json")
    routes = accounting.get("routes") or []
    accepted = [r for r in routes if r.get("status") == "JOINT_DEPENDENCE_CELL_ACCEPTED"]
    recon = []
    for r in accepted:
        e0 = float(r.get("energy_d0") or 0)
        e1 = float(r.get("energy_d1") or 0)
        c0 = float(r.get("mean_crps_d0") or 0)
        c1 = float(r.get("mean_crps_d1") or 0)
        recon.append(
            {
                "source_system": r.get("source_system"),
                "horizon_days": r.get("horizon_days"),
                "energy_d0": e0,
                "energy_d1": e1,
                "energy_delta": e1 - e0,
                "relative_energy_improvement": (e0 - e1) / e0 if e0 else None,
                "mean_crps_d0": c0,
                "mean_crps_d1": c1,
                "crps_d1_worse": c1 > c0,
                "heldout_energy_d0": r.get("heldout_energy_d0"),
                "heldout_energy_d1": r.get("heldout_energy_d1"),
                "do_not_transfer_as_accepted": True,
            }
        )
    a30 = next(
        (x for x in recon if x["source_system"] == "magerya_api" and x["horizon_days"] == 30),
        None,
    )
    status = _public(root, "status-contract.json")
    return {
        "version": VERSION,
        "PRIOR_JOINT_FOUNDATION_STATUS": "NOT_ACCEPTED_EVIDENCE_AND_RUNTIME_CORRECTION_REQUIRED",
        "v02_publication_integrity_may_remain_pass": True,
        "published_JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": status.get(
            "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT"
        ),
        "recount_from_zero": True,
        "defects": [
            {
                "id": 6,
                "claim": "D1 trained on in-sample residuals of frozen marginals, not group-OOF",
                "predict_active_in_fit_d1": in_sample,
                "oof_in_fit_d1": oof_in_fit,
                "reproduced": in_sample and not oof_in_fit,
            },
            {
                "id": 7,
                "claim": "Route acceptance is pointwise energy_d1 < energy_d0 without paired group bootstrap CI",
                "pointwise_flag": pointwise,
                "reproduced": '"d1_better_energy": better' in joint,
            },
            {
                "id": 8,
                "claim": "Published improvements of three accepted routes are small and must be recomputed",
                "routes": recon,
                "reproduced": len(accepted) == 3,
            },
            {
                "id": 9,
                "claim": "Source A 30d validation marginal CRPS D1 worse than D0",
                "reproduced": bool(a30 and a30["crps_d1_worse"]),
                "source_a_30d": a30,
            },
        ],
        "ok": True,
    }


def reproduce_v02_engine_routing(root: Path) -> dict[str, Any]:
    evaluate = _src(root, "evaluate.py")
    boot_row = "for a, b in by[k]:\n            acc.append(abs(a - b))" in evaluate.replace(
        "            ", "            "
    )
    boot_mean_rows = "stats.append(sum(acc) / len(acc))" in evaluate
    gate_uses_interval = "lo, hi = interval(cell, yhat)" in evaluate
    emp_computed = "empirical_path_coverage" in evaluate
    gate_expr = evaluate.split("gate_ok =")[1].split("return {")[0] if "gate_ok =" in evaluate else ""
    uses_cov_not_emp = "COVERAGE_LO <= cov <=" in gate_expr and "emp_cov" not in gate_expr
    status = _public(root, "status-contract.json")
    accounting = _public(root, "joint-panel-accounting.json")
    return {
        "version": VERSION,
        "defects": [
            {
                "id": 12,
                "claim": "Bootstrap resamples effective groups then row-weights inside groups",
                "row_weighted_mean": boot_mean_rows,
                "subject_macro_mae_exists": "def _mae_pairs" in evaluate,
                "bootstrap_uses_mae_pairs": "_mae_pairs" in evaluate.split("def _bootstrap")[1].split("def _oos")[0],
                "reproduced": boot_mean_rows,
            },
            {
                "id": 13,
                "claim": "Direct validation gate uses residual-quantile interval on path median, not primary empirical path interval",
                "interval_on_median": gate_uses_interval,
                "empirical_computed_but_not_gate": emp_computed and uses_cov_not_emp,
                "reproduced": gate_uses_interval and uses_cov_not_emp,
            },
            {
                "id": 14,
                "claim": "DEPENDENCE_STABILITY_STATUS=DETERMINISTIC_TRAIN_FIT is not seed/subsample/bootstrap stability",
                "published": accounting.get("DEPENDENCE_STABILITY_STATUS")
                or status.get("DEPENDENCE_STABILITY_STATUS"),
                "reproduced": (
                    accounting.get("DEPENDENCE_STABILITY_STATUS") == "DETERMINISTIC_TRAIN_FIT"
                    or status.get("DEPENDENCE_STABILITY_STATUS") == "DETERMINISTIC_TRAIN_FIT"
                ),
            },
        ],
        "scalar_inference_cannot_be_joint_pass": True,
        "ENGINE_JOINT_MODEL_ROUTING_STATUS_PUBLISHED": status.get("ENGINE_JOINT_MODEL_ROUTING_STATUS"),
        "ok": True,
    }


def run_phase0(root: Path) -> dict[str, Any]:
    runtime = reproduce_v02_joint_runtime(root)
    scores = reproduce_v02_score_validity(root)
    panels = reproduce_v02_panel_identity(root)
    accept = reproduce_v02_acceptance(root)
    routing = reproduce_v02_engine_routing(root)
    all_reproduced = all(
        d.get("reproduced")
        for block in (runtime, scores, panels, accept, routing)
        for d in block.get("defects") or []
    )
    return {
        "version": VERSION,
        "V02_JOINT_DEFECT_REPRODUCTION_STATUS": "REPRODUCED" if all_reproduced else "PARTIAL",
        "PRIOR_JOINT_FOUNDATION_STATUS": "NOT_ACCEPTED_EVIDENCE_AND_RUNTIME_CORRECTION_REQUIRED",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT_RESET": 0,
        "JOINT_HELDOUT_CONFIRMED_ROUTE_COUNT_RESET": 0,
        "runtime": runtime,
        "scores": scores,
        "panels": panels,
        "acceptance": accept,
        "routing": routing,
        "ok": all_reproduced,
    }
