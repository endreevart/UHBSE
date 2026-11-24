"""Timeline and simulation kernel — POST_STEP checkpoint, fork/rollback from N+1 (v0.1.2)."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from human_simulator.core.policy import CHECKPOINT_PHASE
from human_simulator.core.snapshot import EvidenceStateSnapshot, parse_ts


def _stable_int_seed(master_seed: int, *parts: str) -> int:
    msg = "|".join([str(master_seed), *parts]).encode()
    digest = hashlib.sha256(msg).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def crn_unit_noise(master_seed: int, week: int, variable: str) -> float:
    digest = hashlib.sha256(f"crn|{master_seed}|{week}|{variable}".encode()).digest()
    u = int.from_bytes(digest[:8], "big") / float(2**64)
    return (u * 2.0) - 1.0


def hash_state(state: dict[str, float]) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def hash_history(history: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(history, sort_keys=True, default=str).encode()).hexdigest()


def hash_events(events: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(events, sort_keys=True, default=str).encode()).hexdigest()


def snapshot_parent_branch(parent: dict[str, Any]) -> dict[str, Any]:
    """Immutable parent snapshot taken before fork (deep copies + hashes)."""
    final_state = copy.deepcopy(parent["final_state"])
    history = copy.deepcopy(parent["history"])
    events = copy.deepcopy(parent.get("events") or [])
    return {
        "final_state": final_state,
        "history": history,
        "events": events,
        "final_state_hash": hash_state(final_state),
        "history_hash": hash_history(history),
        "events_hash": hash_events(events),
        "history_len": len(history),
        "stored_final_state_hash": parent.get("final_state_hash"),
    }


def verify_parent_isolation(
    *,
    parent_before: dict[str, Any],
    parent_live: dict[str, Any],
) -> dict[str, Any]:
    """Recompute parent hashes after fork and compare to immutable before-snapshot."""
    after_state_hash = hash_state(parent_live["final_state"])
    after_history_hash = hash_history(parent_live["history"])
    after_events_hash = hash_events(parent_live.get("events") or [])
    after_history_len = len(parent_live["history"])
    recomputed_matches_stored = after_state_hash == parent_live.get("final_state_hash")
    parent_state_unchanged = after_state_hash == parent_before["final_state_hash"]
    parent_history_unchanged = (
        after_history_hash == parent_before["history_hash"]
        and after_history_len == parent_before["history_len"]
    )
    parent_events_unchanged = after_events_hash == parent_before["events_hash"]
    ok = (
        parent_state_unchanged
        and parent_history_unchanged
        and parent_events_unchanged
        and recomputed_matches_stored
        and parent_before["final_state_hash"] == parent_before.get("stored_final_state_hash")
    )
    return {
        "parent_state_unchanged_after_fork": parent_state_unchanged,
        "parent_history_unchanged_after_fork": parent_history_unchanged,
        "parent_events_unchanged_after_fork": parent_events_unchanged,
        "parent_recomputed_hash_matches_stored_hash": recomputed_matches_stored,
        "fork_isolation_verified": ok,
        "before": {
            "final_state_hash": parent_before["final_state_hash"],
            "history_hash": parent_before["history_hash"],
            "events_hash": parent_before["events_hash"],
            "history_len": parent_before["history_len"],
        },
        "after": {
            "final_state_hash": after_state_hash,
            "history_hash": after_history_hash,
            "events_hash": after_events_hash,
            "history_len": after_history_len,
            "stored_final_state_hash": parent_live.get("final_state_hash"),
        },
    }


def compute_fork_effect(
    *,
    counterfactual: dict[str, Any],
    event_fork: dict[str, Any],
    checkpoint_hash: str,
    fork_event: dict[str, Any],
    continue_week: int,
) -> dict[str, Any]:
    """Compute whether final-state diff is explained by the fork event (not a constant)."""
    cf_hash = counterfactual["final_state_hash"]
    ev_hash = event_fork["final_state_hash"]
    cf_by_week = {h["week"]: h["state_hash"] for h in counterfactual["history"]}
    ev_by_week = {h["week"]: h["state_hash"] for h in event_fork["history"]}
    weeks = sorted(set(cf_by_week) | set(ev_by_week))
    first_divergence_week: int | None = None
    for week in weeks:
        if cf_by_week.get(week) != ev_by_week.get(week):
            first_divergence_week = week
            break
    changed_variables: list[str] = []
    cf_final = counterfactual["final_state"]
    ev_final = event_fork["final_state"]
    for key in sorted(set(cf_final) | set(ev_final)):
        if cf_final.get(key) != ev_final.get(key):
            changed_variables.append(key)
    event_week = int(fork_event["week"])
    same_checkpoint = (
        counterfactual.get("fork_start_state_hash") == checkpoint_hash
        and event_fork.get("fork_start_state_hash") == checkpoint_hash
    )
    divergence_not_before_event = (
        first_divergence_week is None or first_divergence_week >= event_week
    )
    finals_differ = cf_hash != ev_hash
    at_least_one_var = len(changed_variables) > 0
    explained = (
        same_checkpoint
        and finals_differ
        and at_least_one_var
        and divergence_not_before_event
        and first_divergence_week is not None
        and event_week >= continue_week
    )
    return {
        "counterfactual_final_state_hash": cf_hash,
        "event_fork_final_state_hash": ev_hash,
        "weekly_hashes": {
            "counterfactual": {str(w): cf_by_week[w] for w in sorted(cf_by_week)},
            "event_fork": {str(w): ev_by_week[w] for w in sorted(ev_by_week)},
        },
        "applied_event": fork_event,
        "event_week": event_week,
        "changed_variables": changed_variables,
        "first_divergence_week": first_divergence_week,
        "both_started_from_same_checkpoint_hash": same_checkpoint,
        "final_hashes_differ": finals_differ,
        "at_least_one_state_variable_changed": at_least_one_var,
        "divergence_not_before_event_week": divergence_not_before_event,
        "fork_final_state_diff_explained_by_fork_event": explained,
    }


@dataclass
class TimelineEvent:
    event_id: str
    event_type: str
    subject_id: str
    clinical_time: str | None
    recorded_time: str | None
    source_order: int
    payload: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple:
        ct = parse_ts(self.clinical_time) or datetime.min.replace(tzinfo=UTC)
        rt = parse_ts(self.recorded_time) or datetime.min.replace(tzinfo=UTC)
        return (ct, rt, self.source_order, self.event_id)


def build_timeline(
    *,
    subject_id: str,
    encounters: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[TimelineEvent] = []
    order = 0
    comps_by_obs: dict[str, list[dict[str, Any]]] = {}
    for c in components:
        comps_by_obs.setdefault(str(c["observation_id"]), []).append(c)
    for enc in encounters:
        if enc.get("subject_id") != subject_id:
            continue
        order += 1
        events.append(
            TimelineEvent(
                event_id=str(enc["encounter_id"]),
                event_type="encounter",
                subject_id=subject_id,
                clinical_time=enc.get("occurred_at"),
                recorded_time=enc.get("recorded_at"),
                source_order=order,
                payload={"status": enc.get("status")},
            )
        )
    for obs in observations:
        if obs.get("subject_id") != subject_id:
            continue
        order += 1
        oid = str(obs["observation_id"])
        events.append(
            TimelineEvent(
                event_id=oid,
                event_type="observation",
                subject_id=subject_id,
                clinical_time=obs.get("observed_at"),
                recorded_time=obs.get("recorded_at"),
                source_order=order,
                payload={
                    "component_count": len(comps_by_obs.get(oid, [])),
                    "status": obs.get("status"),
                },
            )
        )
    events.sort(key=lambda e: e.sort_key())
    return [asdict(e) for e in events]


@dataclass
class PredictedValue:
    name: str
    value: float
    unit: str | None
    lower: float
    upper: float
    status: str = "PREDICTED"


@dataclass
class ScenarioCheckpoint:
    checkpoint_id: str
    branch_id: str
    week: int
    phase: str
    state: dict[str, float]
    state_hash: str
    dose: float
    created_at: str
    continue_from_week: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PersistenceBaselineModel:
    MODEL_ID = "persistence_baseline"
    MODEL_VERSION = "0.1.2"
    MODEL_KIND = "BASELINE_CONTROL"
    CLINICAL_VALIDATION = "NOT_CLAIMED"

    def step(
        self, *, state: dict[str, float], week: int, dose: float, master_seed: int
    ) -> dict[str, PredictedValue]:
        return {k: PredictedValue(k, v, None, v, v) for k, v in state.items()}


class HeuristicDriftBaselineModel:
    MODEL_ID = "heuristic_drift_baseline"
    MODEL_VERSION = "0.1.2"
    MODEL_KIND = "HEURISTIC_BASELINE"
    CLINICAL_VALIDATION = "NOT_CLAIMED"
    NOTE = "Heuristic drift only; not fitted to longitudinal observations; not causal."

    def step(
        self, *, state: dict[str, float], week: int, dose: float, master_seed: int
    ) -> dict[str, PredictedValue]:
        out: dict[str, PredictedValue] = {}
        drift = 0.002 * week
        for k, v in state.items():
            noise = crn_unit_noise(master_seed, week, f"heuristic|{k}") * 0.01 * abs(v)
            center = v * (1.0 - drift) + noise
            half = abs(v) * 0.05 + 1e-6
            out[k] = PredictedValue(k, center, None, center - half, center + half)
        return out


EmpiricalTrendModel = HeuristicDriftBaselineModel


class SyntheticInterventionTestModel:
    MODEL_ID = "synthetic_intervention_test"
    MODEL_VERSION = "0.1.2"
    MODEL_KIND = "SYNTHETIC_ENGINE_TEST"
    CLINICAL_USE = "PROHIBITED"
    CLINICAL_VALIDATION = "NOT_CLAIMED"

    def step(
        self, *, state: dict[str, float], week: int, dose: float, master_seed: int
    ) -> dict[str, PredictedValue]:
        out: dict[str, PredictedValue] = {}
        for k, v in state.items():
            noise = crn_unit_noise(master_seed, week, f"synthetic|{k}") * 0.1
            center = v - dose * 0.5 * week + noise
            half = 1.0 + dose
            out[k] = PredictedValue(k, center, None, center - half, center + half)
        return out


def configuration_hash(
    *,
    input_snapshot_hash: str,
    models: dict[str, Any],
    seed: int,
    horizon_weeks: int,
    step_weeks: int,
    branch_events: list[dict[str, Any]],
    intervention_params: dict[str, Any],
) -> str:
    payload = {
        "input_snapshot_hash": input_snapshot_hash,
        "models": {
            name: {
                "MODEL_ID": getattr(m, "MODEL_ID", name),
                "MODEL_VERSION": getattr(m, "MODEL_VERSION", "unknown"),
                "MODEL_KIND": getattr(m, "MODEL_KIND", "unknown"),
            }
            for name, m in sorted(models.items())
        },
        "seed": seed,
        "horizon_weeks": horizon_weeks,
        "step_weeks": step_weeks,
        "branch_events": branch_events,
        "intervention_params": intervention_params,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class SimulationKernel:
    def __init__(self, *, seed: int, horizon_weeks: int = 12, step_weeks: int = 1) -> None:
        self.seed = int(seed)
        self.horizon_weeks = horizon_weeks
        self.step_weeks = step_weeks

    def _branch_defs(self) -> list[dict[str, Any]]:
        return [
            {
                "branch_id": "control",
                "label": "Control",
                "dose": 0.0,
                "dose_change_week": None,
                "events": [{"week": 0, "type": "start"}],
            },
            {
                "branch_id": "intervention_a",
                "label": "Intervention A",
                "dose": 1.0,
                "dose_change_week": None,
                "events": [
                    {"week": 0, "type": "start"},
                    {"week": 0, "type": "intervention_begin", "name": "synthetic_intervention_a"},
                ],
            },
            {
                "branch_id": "intervention_a_dose_change",
                "label": "Intervention A with dose change",
                "dose": 1.0,
                "dose_change_week": 4,
                "events": [
                    {"week": 0, "type": "start"},
                    {"week": 0, "type": "intervention_begin", "name": "synthetic_intervention_a"},
                    {"week": 4, "type": "dose_change", "dose": 2.0},
                ],
            },
        ]

    def simulate_branch(
        self,
        *,
        branch_def: dict[str, Any],
        base_state: dict[str, float],
        models: dict[str, Any],
        until_week: int | None = None,
        start_week: int = 0,
        start_state: dict[str, float] | None = None,
        start_dose: float | None = None,
        emit_checkpoint_at: int | None = 2,
        extra_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Simulate weeks [start_week .. horizon]. Checkpoint is POST_STEP after emit_checkpoint_at."""
        horizon = self.horizon_weeks if until_week is None else until_week
        state = copy.deepcopy(start_state if start_state is not None else base_state)
        history: list[dict[str, Any]] = []
        checkpoints: list[ScenarioCheckpoint] = []
        dose = float(branch_def["dose"] if start_dose is None else start_dose)
        events = list(branch_def.get("events") or [])
        # extra_events are applied for transitions; avoid duplicating them in the event log
        for ev in extra_events or []:
            if ev not in events:
                events.append(ev)

        for week in range(start_week, horizon + 1, self.step_weeks):
            # Apply scheduled dose change at the beginning of the week transition
            if branch_def.get("dose_change_week") is not None and week == branch_def["dose_change_week"]:
                dose = 2.0
            for ev in extra_events or []:
                if ev.get("week") == week and ev.get("type") == "dose_change":
                    dose = float(ev.get("dose", dose))

            preds: dict[str, dict[str, PredictedValue]] = {}
            for model_name, model in models.items():
                preds[model_name] = model.step(
                    state=state, week=week, dose=dose, master_seed=self.seed
                )
            adv = preds.get("synthetic") or preds.get("persistence")
            if adv:
                for k, pv in adv.items():
                    state[k] = pv.value
            sh = hash_state(state)
            history.append(
                {
                    "week": week,
                    "dose": dose,
                    "predicted": {
                        mn: {k: asdict(v) for k, v in mp.items()} for mn, mp in preds.items()
                    },
                    "state_hash": sh,
                }
            )
            if emit_checkpoint_at is not None and week == emit_checkpoint_at and start_week <= emit_checkpoint_at:
                checkpoints.append(
                    ScenarioCheckpoint(
                        checkpoint_id=f"{branch_def['branch_id']}-w{week}",
                        branch_id=branch_def["branch_id"],
                        week=week,
                        phase=CHECKPOINT_PHASE,
                        state=copy.deepcopy(state),
                        state_hash=sh,
                        dose=dose,
                        created_at=datetime.now(UTC).isoformat(),
                        continue_from_week=week + self.step_weeks,
                    )
                )
        return {
            "branch_id": branch_def["branch_id"],
            "label": branch_def["label"],
            "events": events,
            "history": history,
            "final_state": state,
            "final_state_hash": hash_state(state),
            "checkpoints": [c.to_dict() for c in checkpoints],
        }

    def fork_from_checkpoint(
        self,
        *,
        checkpoint: dict[str, Any],
        new_branch_id: str,
        models: dict[str, Any],
        base_state: dict[str, float],
        parent_live: dict[str, Any],
        parent_before: dict[str, Any] | None = None,
        fork_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fork from POST_STEP checkpoint with computed counterfactual vs event effect."""
        if checkpoint.get("phase") != CHECKPOINT_PHASE:
            return {"ok": False, "error": "checkpoint_phase_not_post_step", "phase": checkpoint.get("phase")}
        cp_state = copy.deepcopy(checkpoint["state"])
        cp_hash = checkpoint.get("state_hash") or hash_state(cp_state)
        if hash_state(cp_state) != cp_hash:
            return {
                "ok": False,
                "error": "checkpoint_state_hash_mismatch",
                "expected": cp_hash,
                "actual": hash_state(cp_state),
            }
        n = int(checkpoint["week"])
        continue_week = int(checkpoint.get("continue_from_week", n + self.step_weeks))
        if continue_week != n + self.step_weeks:
            return {"ok": False, "error": "continue_from_week_inconsistent"}

        start_dose = float(checkpoint.get("dose", 1.0))
        if fork_event is None:
            fork_event = {
                "week": continue_week,
                "type": "dose_change",
                "dose": 1.5,
                "name": "fork_dose_nudge",
            }
        if fork_event.get("week") is None:
            return {"ok": False, "error": "fork_event_time_not_explicit"}
        if int(fork_event["week"]) < continue_week:
            return {"ok": False, "error": "fork_event_before_continuation"}

        if parent_before is None:
            parent_before = snapshot_parent_branch(parent_live)

        fork_marker = {
            "week": continue_week,
            "type": "fork",
            "from_checkpoint": checkpoint["checkpoint_id"],
            "checkpoint_phase": CHECKPOINT_PHASE,
        }
        common = {
            "dose": start_dose,
            "dose_change_week": None,
        }

        # A: counterfactual continuation — same checkpoint/seed/horizon/dose, no new intervention
        cf_def = {
            "branch_id": f"{new_branch_id}_counterfactual",
            "label": f"Counterfactual from {checkpoint['checkpoint_id']}",
            **common,
            "events": [fork_marker],
        }
        counterfactual = self.simulate_branch(
            branch_def=cf_def,
            base_state=base_state,
            models=models,
            start_week=continue_week,
            start_state=copy.deepcopy(cp_state),
            start_dose=start_dose,
            emit_checkpoint_at=None,
            extra_events=None,
        )
        counterfactual["fork_start_state_hash"] = cp_hash

        # B: event fork — identical inputs plus explicit fork event
        ev_def = {
            "branch_id": new_branch_id,
            "label": f"Fork from {checkpoint['checkpoint_id']}",
            **common,
            "events": [fork_marker],
        }
        result = self.simulate_branch(
            branch_def=ev_def,
            base_state=base_state,
            models=models,
            start_week=continue_week,
            start_state=copy.deepcopy(cp_state),
            start_dose=start_dose,
            emit_checkpoint_at=None,
            extra_events=[fork_event],
        )
        result["fork_start_state_hash"] = cp_hash

        effect = compute_fork_effect(
            counterfactual=counterfactual,
            event_fork=result,
            checkpoint_hash=cp_hash,
            fork_event=fork_event,
            continue_week=continue_week,
        )
        isolation = verify_parent_isolation(
            parent_before=parent_before,
            parent_live=parent_live,
        )

        hist_weeks = [h["week"] for h in result["history"]]
        no_dup = n not in hist_weeks
        starts_after = hist_weeks[:1] == [continue_week] if hist_weeks else False
        ok = (
            no_dup
            and starts_after
            and isolation["fork_isolation_verified"]
            and effect["fork_final_state_diff_explained_by_fork_event"]
        )
        result.update(
            {
                "ok": ok,
                "from_checkpoint": checkpoint["checkpoint_id"],
                "checkpoint_phase": CHECKPOINT_PHASE,
                "checkpoint_week": n,
                "continuation_start_week": continue_week,
                "fork_event": fork_event,
                "fork_start_state_hash": cp_hash,
                "fork_start_state_hash_verified": True,
                "fork_continuation_starts_after_checkpoint": starts_after,
                "fork_event_time_explicit": fork_event.get("week") is not None,
                "fork_has_no_duplicate_transition": no_dup,
                "source_branch_unchanged_after_fork": isolation["fork_isolation_verified"],
                "source_branch_final_hash": parent_before["final_state_hash"],
                "history_weeks": hist_weeks,
                "counterfactual": {
                    "final_state_hash": counterfactual["final_state_hash"],
                    "history": counterfactual["history"],
                    "fork_start_state_hash": cp_hash,
                },
                "fork_effect": effect,
                "parent_isolation": isolation,
                "fork_final_state_diff_explained_by_fork_event": effect[
                    "fork_final_state_diff_explained_by_fork_event"
                ],
                **{k: isolation[k] for k in (
                    "parent_state_unchanged_after_fork",
                    "parent_history_unchanged_after_fork",
                    "parent_events_unchanged_after_fork",
                    "parent_recomputed_hash_matches_stored_hash",
                    "fork_isolation_verified",
                )},
            }
        )
        return result

    def rollback_and_resimulate(
        self,
        *,
        checkpoint: dict[str, Any],
        branch_def: dict[str, Any],
        models: dict[str, Any],
        base_state: dict[str, float],
        mutated_state: dict[str, float],
        original_final_state_hash: str,
        original_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Restore POST_STEP checkpoint and continue from N+1; must match original final."""
        if checkpoint.get("phase") != CHECKPOINT_PHASE:
            return {"ok": False, "error": "checkpoint_phase_not_post_step"}
        before_mutate_hash = hash_state(mutated_state)
        restored = copy.deepcopy(checkpoint["state"])
        restored_hash = hash_state(restored)
        expected = checkpoint.get("state_hash") or hash_state(checkpoint["state"])
        if restored_hash != expected:
            return {
                "ok": False,
                "error": "rollback_hash_mismatch",
                "expected_checkpoint_hash": expected,
                "restored_hash": restored_hash,
            }
        n = int(checkpoint["week"])
        continue_week = int(checkpoint.get("continue_from_week", n + self.step_weeks))
        resumed = self.simulate_branch(
            branch_def=branch_def,
            base_state=base_state,
            models=models,
            start_week=continue_week,
            start_state=restored,
            start_dose=float(checkpoint.get("dose", branch_def["dose"])),
            emit_checkpoint_at=None,
        )
        hist_weeks = [h["week"] for h in resumed["history"]]
        no_dup = n not in hist_weeks
        starts_after = (not hist_weeks) or hist_weeks[0] == continue_week
        # Remaining original history from continue_week onward
        original_tail = [h for h in original_history if h["week"] >= continue_week]
        original_tail_weeks = [h["week"] for h in original_tail]
        original_tail_hashes = [h["state_hash"] for h in original_tail]
        resumed_hashes = [h["state_hash"] for h in resumed["history"]]
        history_match = (
            original_tail_weeks == hist_weeks and original_tail_hashes == resumed_hashes
        )
        final_match = resumed["final_state_hash"] == original_final_state_hash
        ok = (
            restored_hash == expected
            and starts_after
            and no_dup
            and final_match
            and history_match
        )
        return {
            "ok": ok,
            "branch_id": branch_def["branch_id"],
            "restored_checkpoint": checkpoint["checkpoint_id"],
            "checkpoint_phase": CHECKPOINT_PHASE,
            "checkpoint_week": n,
            "continuation_start_week": continue_week,
            "expected_checkpoint_hash": expected,
            "restored_hash": restored_hash,
            "hash_match_after_rollback": restored_hash == expected,
            "mutated_hash_before_rollback": before_mutate_hash,
            "resimulated_final_state_hash": resumed["final_state_hash"],
            "original_final_state_hash": original_final_state_hash,
            "rollback_reproduces_original_final_state": final_match,
            "rollback_continuation_starts_after_checkpoint": starts_after,
            "rollback_history_has_no_duplicate_checkpoint_week": no_dup,
            "rollback_restores_checkpoint_exactly": restored_hash == expected,
            "history_weeks": hist_weeks,
            "history_sequence_match": history_match,
            "resimulated_history_len": len(resumed["history"]),
            "original_tail_len": len(original_tail),
        }

    def run_branches(
        self,
        *,
        starting: dict[str, Any] | EvidenceStateSnapshot,
        models: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(starting, EvidenceStateSnapshot):
            base_state = starting.state_vector()
            input_snapshot_hash = starting.snapshot_id
            subject_id = starting.subject_id
        else:
            base_state = {}
            if starting.get("components"):
                for c in starting["components"]:
                    if c.get("selection_status") == "single_value" and c.get("numeric_value") is not None:
                        base_state[str(c.get("variable_key"))] = float(c["numeric_value"])
            for lab in starting.get("laboratory") or []:
                if lab.get("numeric_value") is None:
                    continue
                base_state[str(lab.get("raw_code") or "metric")] = float(lab["numeric_value"])
            input_snapshot_hash = starting.get("snapshot_id") or hash_state(base_state)
            subject_id = starting.get("subject_id", "unknown")

        if not base_state:
            base_state = {"synthetic_metric": 100.0}

        input_hash = hash_state(base_state)
        branch_defs = self._branch_defs()
        branches = []
        all_checkpoints: list[dict[str, Any]] = []
        for bdef in branch_defs:
            br = self.simulate_branch(branch_def=bdef, base_state=base_state, models=models)
            branches.append(br)
            all_checkpoints.extend(br["checkpoints"])

        control_only = self.simulate_branch(
            branch_def=branch_defs[0], base_state=base_state, models=models
        )
        isolation = {
            "control_recompute_matches": control_only["final_state_hash"]
            == branches[0]["final_state_hash"],
            "control_differs_from_intervention": branches[0]["final_state_hash"]
            != branches[1]["final_state_hash"],
            "dose_change_differs_from_intervention": branches[1]["final_state_hash"]
            != branches[2]["final_state_hash"],
            "crn_policy": "shared_noise_by_week_and_variable",
        }

        fork: dict[str, Any] = {"ok": False, "error": "no_checkpoint"}
        rollback: dict[str, Any] = {"ok": False, "error": "no_checkpoint"}
        control_cps = [c for c in all_checkpoints if c["branch_id"] == "control"]
        if control_cps:
            cp = control_cps[0]
            parent_live = branches[0]
            parent_before = snapshot_parent_branch(parent_live)
            fork = self.fork_from_checkpoint(
                checkpoint=cp,
                new_branch_id="fork_from_control_w2",
                models=models,
                base_state=base_state,
                parent_live=parent_live,
                parent_before=parent_before,
            )
            mutated = copy.deepcopy(branches[0]["final_state"])
            for k in list(mutated.keys()):
                mutated[k] = mutated[k] + 999.0
            rollback = self.rollback_and_resimulate(
                checkpoint=cp,
                branch_def=branch_defs[0],
                models=models,
                base_state=base_state,
                mutated_state=mutated,
                original_final_state_hash=branches[0]["final_state_hash"],
                original_history=branches[0]["history"],
            )

        cfg = configuration_hash(
            input_snapshot_hash=str(input_snapshot_hash),
            models=models,
            seed=self.seed,
            horizon_weeks=self.horizon_weeks,
            step_weeks=self.step_weeks,
            branch_events=[b["events"] for b in branches],
            intervention_params={"synthetic_intervention_a": {"dose_levels": [0.0, 1.0, 2.0]}},
        )
        unc_ok = False
        if branches and branches[0]["history"]:
            pred = branches[0]["history"][0]["predicted"]
            for mp in pred.values():
                for pv in mp.values():
                    if "lower" in pv and "upper" in pv and pv["lower"] <= pv["upper"]:
                        unc_ok = True
                        break

        return {
            "seed": self.seed,
            "horizon_weeks": self.horizon_weeks,
            "step_weeks": self.step_weeks,
            "subject_id": subject_id,
            "input_state_hash": input_hash,
            "configuration_hash": cfg,
            "branches": branches,
            "checkpoints": all_checkpoints,
            "fork": fork,
            "rollback": rollback,
            "isolation": isolation,
            "uncertainty_present_computed": unc_ok,
            "checkpoint_phase": CHECKPOINT_PHASE,
            "master_seed_policy": "CRN: identical noise(week,variable) across branches",
        }
