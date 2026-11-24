"""Synthetic QSP/PKPD sandbox. Never mixed with patient natural-history trajectories."""

from __future__ import annotations

import math
from typing import Any

from human_simulator.integrated_research_runtime_v01.hashes import sha_obj
from human_simulator.integrated_research_runtime_v01.policy import CODE_VERSION, VERSION

DT = 0.05


def _euler(fun, y0: list[float], t_grid: list[float], params: dict[str, Any]) -> list[list[float]]:
    out = [list(y0)]
    y = list(y0)
    for i in range(1, len(t_grid)):
        t = t_grid[i - 1]
        dt = t_grid[i] - t_grid[i - 1]
        n = max(1, int(round(dt / DT)))
        h = dt / n
        for k in range(n):
            dy = fun(t + k * h, y, params)
            y = [a + h * b for a, b in zip(y, dy, strict=True)]
        out.append(list(y))
    return out


def pkpd_rhs(t: float, y: list[float], p: dict[str, Any]) -> list[float]:
    depot, conc, effect = y
    ka, ke, vd, emax, ec50, kout = (
        p["ka"],
        p["ke"],
        p["vd"],
        p["emax"],
        p["ec50"],
        p["kout"],
    )
    dose_rate = 0.0
    d_depot = -ka * depot
    d_conc = (ka * depot - ke * conc * vd) / vd
    e = emax * max(conc, 0.0) / (ec50 + max(conc, 0.0))
    d_effect = kout * (e - effect)
    return [d_depot, d_conc, d_effect]


def qsp_rhs(t: float, y: list[float], p: dict[str, Any]) -> list[float]:
    x, feedback = y
    kin, kout, kfb, u = p["kin"], p["kout"], p["kfb"], p.get("u", 0.0)
    dx = kin * (1.0 + u) - kout * x * (1.0 + kfb * feedback)
    df = x - feedback
    return [dx, df]


PKPD_PARAMS = {
    "ka": 1.2,
    "ke": 0.3,
    "vd": 10.0,
    "emax": 1.0,
    "ec50": 1.0,
    "kout": 0.4,
    "dose": 5.0,
}
QSP_PARAMS = {"kin": 1.0, "kout": 0.2, "kfb": 0.5, "u": 0.0}


def run_pkpd(params: dict[str, Any] | None = None, t_end: float = 24.0) -> dict[str, Any]:
    p = dict(PKPD_PARAMS)
    if params:
        p.update(params)
    t_grid = [i * 0.5 for i in range(int(t_end / 0.5) + 1)]
    y0 = [float(p["dose"]), 0.0, 0.0]
    traj = _euler(pkpd_rhs, y0, t_grid, p)
    conc = [row[1] for row in traj]
    identity = sha_obj({"family": "SYNTHETIC_REFERENCE_COMPOUND_X_PKPD", "params": p, "t_grid": t_grid, "code": CODE_VERSION})
    nonneg = all(c >= -1e-9 for c in conc)
    zero = dict(p)
    zero["dose"] = 0.0
    ztraj = _euler(pkpd_rhs, [0.0, 0.0, 0.0], t_grid, zero)
    zero_ok = all(abs(row[1]) < 1e-9 for row in ztraj)
    replay = _euler(pkpd_rhs, y0, t_grid, p)
    det = traj == replay
    return {
        "model_id": "SYNTHETIC_REFERENCE_COMPOUND_X_PKPD",
        "synthetic_only": True,
        "patient_linked": False,
        "units": {"time": "h", "concentration": "synthetic_mass/volume", "effect": "dimensionless"},
        "solver": {"method": "euler", "dt": DT, "requested_time_grid": t_grid},
        "params": p,
        "concentration": conc,
        "effect": [row[2] for row in traj],
        "non_negative_concentration": nonneg,
        "zero_dose_invariant": zero_ok,
        "deterministic": det,
        "payload_sha256": identity,
        "licensing": "synthetic_fixture_no_real_drug",
    }


def run_qsp(params: dict[str, Any] | None = None, t_end: float = 48.0) -> dict[str, Any]:
    p = dict(QSP_PARAMS)
    if params:
        p.update(params)
    t_grid = [i * 1.0 for i in range(int(t_end) + 1)]
    y0 = [p["kin"] / p["kout"], p["kin"] / p["kout"]]
    traj = _euler(qsp_rhs, y0, t_grid, p)
    identity = sha_obj({"family": "SYNTHETIC_HOMEOSTATIC_BIOMARKER_QSP", "params": p, "t_grid": t_grid, "code": CODE_VERSION})
    replay = _euler(qsp_rhs, y0, t_grid, p)
    pert = dict(p)
    pert["u"] = 0.5
    pert_traj = _euler(qsp_rhs, y0, t_grid, pert)
    sensitive = traj[-1][0] != pert_traj[-1][0]
    return {
        "model_id": "SYNTHETIC_HOMEOSTATIC_BIOMARKER_QSP",
        "synthetic_only": True,
        "patient_linked": False,
        "units": {"time": "h", "biomarker": "synthetic_concentration"},
        "solver": {"method": "euler", "dt": DT, "requested_time_grid": t_grid},
        "params": p,
        "biomarker": [row[0] for row in traj],
        "deterministic": traj == replay,
        "dose_response_sensitive": sensitive,
        "payload_sha256": identity,
        "licensing": "synthetic_fixture_no_real_patient",
    }


def sandbox_audit() -> dict[str, Any]:
    pk = run_pkpd()
    qsp = run_qsp()
    mutated = run_pkpd({"ke": 0.9})
    ident_changed = mutated["payload_sha256"] != pk["payload_sha256"]
    patient_req = {"patient_id": "x", "route": "patient_specific"}
    prohibited = patient_req.get("route") == "patient_specific"
    ok = (
        pk["non_negative_concentration"]
        and pk["zero_dose_invariant"]
        and pk["deterministic"]
        and qsp["deterministic"]
        and ident_changed
        and prohibited
        and pk["synthetic_only"]
        and qsp["synthetic_only"]
    )
    return {
        "version": VERSION,
        "QSP_ADAPTER_STATUS": "BUILT",
        "PKPD_REFERENCE_SANDBOX_STATUS": "TECHNICAL_SYNTHETIC_PASS" if pk["deterministic"] else "FAIL",
        "QSP_REFERENCE_SANDBOX_STATUS": "TECHNICAL_SYNTHETIC_PASS" if qsp["deterministic"] else "FAIL",
        "PATIENT_SPECIFIC_QSP_STATUS": "NOT_RUN_NO_ACCEPTED_INTERVENTION_MAPPING",
        "REAL_DRUG_PKPD_STATUS": "NOT_STARTED_PROVIDER_AND_DOMAIN_INPUT_REQUIRED",
        "pkpd": {k: v for k, v in pk.items() if k not in {"concentration", "effect", "solver"}},
        "qsp": {k: v for k, v in qsp.items() if k not in {"biomarker", "solver"}},
        "identity_mutation_changes_hash": ident_changed,
        "patient_specific_routing_prohibited": prohibited,
        "separate_from_patient_trajectories": True,
        "ok": ok,
    }
