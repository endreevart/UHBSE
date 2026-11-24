"""Engine audit: synthetic e2e, frozen A/B execution, identity mutations, two-process replay."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v012.composition import compose_joint_distribution
from human_simulator.integrated_research_runtime_v012.fixtures import synthetic_request, synthetic_runtime_bundle
from human_simulator.integrated_research_runtime_v012.loader import build_frozen_bundle, public_cell_record
from human_simulator.integrated_research_runtime_v012.policy import FROZEN_A_H90, FROZEN_B_P0_H90, MODELS_DIR, SOURCE_A, SOURCE_B, SYN_OUTCOMES, VERSION


def _state_req(value: float) -> dict[str, Any]:
    ok0, ok1 = SYN_OUTCOMES
    return synthetic_request(
        state_at_t0={ok0: value, ok1: value / 2.0},
        history={ok0: [value], ok1: [value / 2.0]},
    )


def frozen_request(bundle: dict[str, Any], *, state: dict[str, float], seed: int = 42) -> dict[str, Any]:
    outcomes = list(bundle["outcomes"])
    return {
        "namespace": bundle["namespace"],
        "source_system": bundle["source_system"],
        "requested_horizon_days": bundle["horizon_days"],
        "outcome_keys": outcomes,
        "state_at_t0": state,
        "history": {ok: [state[ok]] for ok in outcomes},
        "history_days": {ok: [] for ok in outcomes},
        "history_is_pre_t0_summary": True,
        "cutoff_t0": "2000-01-01T00:00:00Z",
        "cell_identities": {
            ok: {
                "active_payload_sha256": bundle["cells"][ok]["active_payload_sha256"],
                "feature_order_sha256": bundle["cells"][ok]["feature_order_sha256"],
                "scaler_sha256": bundle["cells"][ok]["scaler_sha256"],
                "residual_distribution_sha256": bundle["cells"][ok]["residual_distribution_sha256"],
                "unit": bundle["cells"][ok]["unit"],
            }
            for ok in outcomes
        },
        "n_paths": 8,
        "seed": seed,
        "replay_key": "frozen-audit",
    }


def run_cross_process_replay(root: Path, request: dict[str, Any], bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    req_path = Path(root) / MODELS_DIR / "_replay-request.json"
    bun_path = Path(root) / MODELS_DIR / "_replay-bundle.json"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text(json.dumps(request), encoding="utf-8")
    if bundle and not bundle.get("synthetic_fixture"):
        public = dict(bundle)
        public["cells"] = {ok: public_cell_record(c) | {"residual_blocks": c.get("residual_blocks"), "p1_payload": c.get("p1_payload")} for ok, c in bundle["cells"].items()}
        bun_path.write_text(json.dumps(public, default=str), encoding="utf-8")
        py = r"""
import json, sys
from pathlib import Path
from human_simulator.integrated_research_runtime_v012.composition import compose_joint_distribution
req = json.loads(Path(sys.argv[1]).read_text())
bun = json.loads(Path(sys.argv[2]).read_text())
out = compose_joint_distribution(req, bun)
print(json.dumps({"status": out.get("status"), "paths": out.get("paths"), "marginal_forecasts": out.get("marginal_forecasts")}, sort_keys=True, default=str))
"""
        args_base = [sys.executable, "-c", py, str(req_path), str(bun_path)]
    else:
        py = r"""
import json, sys
from pathlib import Path
from human_simulator.integrated_research_runtime_v012.composition import compose_joint_distribution
req = json.loads(Path(sys.argv[1]).read_text())
out = compose_joint_distribution(req)
print(json.dumps({"status": out.get("status"), "paths": out.get("paths"), "marginal_forecasts": out.get("marginal_forecasts")}, sort_keys=True, default=str))
"""
        args_base = [sys.executable, "-c", py, str(req_path)]
    runs = []
    for _ in range(2):
        proc = subprocess.run(args_base, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return {"ok": False, "ENGINE_CROSS_PROCESS_REPLAY_STATUS": "FAIL", "stderr": (proc.stderr or "")[-1500:]}
        runs.append(proc.stdout.strip())
    same = runs[0] == runs[1]
    a = json.loads(runs[0]) if runs[0] else {}
    req_path.unlink(missing_ok=True)
    bun_path.unlink(missing_ok=True)
    ok = same and a.get("status") == "OK"
    return {"ok": ok, "ENGINE_CROSS_PROCESS_REPLAY_STATUS": "PASS_TWO_SUBPROCESS" if ok else "FAIL", "byte_identical_same_seed": same}


def _frozen_audit(root: Path, source: str, outcomes: list[str], horizon: int) -> dict[str, Any]:
    bundle = build_frozen_bundle(root, source, outcomes, horizon)
    public = {
        "source_system": source,
        "outcomes": outcomes,
        "horizon_days": horizon,
        "status": bundle.get("status"),
        "reason": bundle.get("reason"),
        "cells": {ok: public_cell_record(c) for ok, c in (bundle.get("cells") or {}).items()},
        "registry_notes": bundle.get("registry_notes"),
    }
    if bundle.get("status") != "OK":
        return {**public, "executed": False, "ok": False}
    state = {ok: float(10 + i) for i, ok in enumerate(outcomes)}
    req = frozen_request(bundle, state=state)
    a = compose_joint_distribution(req, bundle)
    state2 = {ok: float(100 + i) for i, ok in enumerate(outcomes)}
    b = compose_joint_distribution(frozen_request(bundle, state=state2), bundle)
    mut = deepcopy(req)
    first = outcomes[0]
    mut["cell_identities"][first]["active_payload_sha256"] = "0" * 64
    mut_out = compose_joint_distribution(mut, bundle)
    replay = compose_joint_distribution(req, bundle)
    ok = (
        a.get("status") == "OK"
        and b.get("status") == "OK"
        and a.get("paths") != b.get("paths")
        and a.get("residual_added_to_marginal") is True
        and mut_out.get("reason") == "MODEL_HASH_MISMATCH"
        and replay.get("paths") == a.get("paths")
        and a.get("endpoint_type") == "SOURCE_SPECIFIC_JOINT_OUTCOME_DISTRIBUTION_AT_REQUESTED_HORIZON"
    )
    return {
        **public,
        "executed": a.get("status") == "OK",
        "state_changes_paths": a.get("paths") != b.get("paths"),
        "residual_added": a.get("residual_added_to_marginal"),
        "mutation_rejected": mut_out.get("reason") == "MODEL_HASH_MISMATCH",
        "replay_identical": replay.get("paths") == a.get("paths"),
        "active_providers": {ok: bundle["cells"][ok]["active_provider"] for ok in outcomes},
        "ok": ok,
    }


def run_engine_audit(root: Path) -> dict[str, Any]:
    bundle = synthetic_runtime_bundle()
    a = compose_joint_distribution(_state_req(-1000.0), bundle)
    b = compose_joint_distribution(_state_req(1000.0), bundle)
    replay = compose_joint_distribution(_state_req(-1000.0), bundle)
    mutated = deepcopy(bundle)
    for cell in mutated["cells"].values():
        cell["active_payload_sha256"] = "0" * 64
    mut = compose_joint_distribution(synthetic_request(), mutated)
    p1 = deepcopy(bundle)
    p1["cells"][SYN_OUTCOMES[0]]["active_provider"] = "P1"
    p1["cells"][SYN_OUTCOMES[0]]["p1_payload"] = None
    p1_out = compose_joint_distribution(synthetic_request(), p1)
    src_a = compose_joint_distribution(synthetic_request(source_system=SOURCE_A), bundle)
    no_cut = dict(synthetic_request())
    no_cut.pop("cutoff_t0")
    cut = compose_joint_distribution(no_cut, bundle)
    fo_as_model = dict(synthetic_request())
    fo_as_model["cell_identities"] = {}
    fo_out = compose_joint_distribution(fo_as_model, bundle)
    xproc = run_cross_process_replay(root, _state_req(1.0))
    syn_ok = (
        a.get("status") == "OK"
        and a.get("paths") != b.get("paths")
        and a.get("residual_added_to_marginal") is True
        and replay.get("paths") == a.get("paths")
        and mut.get("reason") == "MODEL_HASH_MISMATCH"
        and p1_out.get("reason") == "P1_PAYLOAD_MISSING"
        and src_a.get("reason") == "SYNTHETIC_PROVIDER_FORBIDDEN_FOR_CLINICAL_SOURCE"
        and cut.get("reason") == "CUTOFF_T0_REQUIRED"
        and fo_out.get("reason") == "PER_OUTCOME_CELL_IDENTITIES_REQUIRED"
        and xproc.get("ok")
        and a.get("not_a_trajectory") is True
    )
    frozen_a = _frozen_audit(root, SOURCE_A, list(FROZEN_A_H90), 90)
    frozen_b = _frozen_audit(root, SOURCE_B, [FROZEN_B_P0_H90], 90)
    return {
        "version": VERSION,
        "SYNTHETIC_E2E_STATUS": "PASS" if syn_ok else "FAIL",
        "SOURCE_A_FROZEN_INFERENCE_STATUS": "PASS" if frozen_a.get("ok") else (frozen_a.get("reason") or "FAIL"),
        "SOURCE_B_FROZEN_INFERENCE_STATUS": "PASS" if frozen_b.get("ok") else (frozen_b.get("reason") or "FAIL"),
        "EXACT_PROVIDER_IDENTITY_STATUS": "PASS" if mut.get("reason") == "MODEL_HASH_MISMATCH" else "FAIL",
        "NO_SILENT_PROVIDER_FALLBACK_STATUS": "PASS" if p1_out.get("reason") == "P1_PAYLOAD_MISSING" else "FAIL",
        "MARGINAL_PROVIDER_RUNTIME_CONSUMPTION_STATUS": "PASS" if a.get("status") == "OK" else "FAIL",
        "STATE_CONDITIONED_MARGINAL_INFERENCE_STATUS": "PASS" if a.get("paths") != b.get("paths") else "FAIL",
        "STATE_CONDITIONED_JOINT_COMPOSITION_STATUS": "PASS" if a.get("residual_added_to_marginal") else "FAIL",
        "D0_JOINT_OUTCOME_DISTRIBUTION_STATUS": "PASS" if a.get("route_used") == "D0" else "FAIL",
        "D1_JOINT_DEPENDENCE_STATUS": "NOT_ACCEPTED",
        "CROSS_HORIZON_DEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": a.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": xproc.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS"),
        "frozen_a": {k: v for k, v in frozen_a.items() if k != "cells"} | {"n_cells": len(frozen_a.get("cells") or {})},
        "frozen_b": {k: v for k, v in frozen_b.items() if k != "cells"} | {"n_cells": len(frozen_b.get("cells") or {})},
        "frozen_a_cells_public": frozen_a.get("cells"),
        "frozen_b_cells_public": frozen_b.get("cells"),
        "opposite_state_changes_paths": a.get("paths") != b.get("paths"),
        "same_state_seed_identical": replay.get("paths") == a.get("paths"),
        "not_a_trajectory": a.get("not_a_trajectory"),
        "ok": syn_ok and frozen_a.get("ok") and frozen_b.get("ok") and xproc.get("ok"),
    }
