"""Typed EvidenceStateSnapshot construction with temporal cutoff (v0.1.2)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from human_simulator.core.policy import (
    SELECTION_POLICY_VERSION,
    SNAPSHOT_BUILDER_VERSION,
    SOURCE_SYSTEM_ID,
    TRANSFORMATION_ID,
    TRANSFORMATION_VERSION,
)
from human_simulator.core.provenance import typed_value_xor_status


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clinical_time_for_observation(obs: dict[str, Any]) -> datetime | None:
    for key in ("observed_at", "specimen_collected_at", "effective_at", "occurred_at"):
        ts = parse_ts(obs.get(key))
        if ts is not None:
            return ts
    return None


def clinical_time_for_encounter(enc: dict[str, Any]) -> datetime | None:
    for key in ("occurred_at", "completed_at", "effective_at"):
        ts = parse_ts(enc.get(key))
        if ts is not None:
            return ts
    return None


def event_after_cutoff(
    *,
    clinical: datetime | None,
    recorded: datetime | None,
    cutoff: datetime,
) -> bool:
    for ts in (clinical, recorded):
        if ts is not None and ts > cutoff:
            return True
    return False


def _now_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def computed_provenance(
    *,
    refs: list[dict[str, str]],
    input_artifact_sha256: str,
    method: str = "evidence_state_snapshot_selection",
) -> dict[str, Any]:
    """COMPUTED/DERIVED provenance — no source_record_locator."""
    return {
        "record_origin": "DERIVED",
        "input_record_references": refs,
        "computation_method": method,
        "computation_version": SNAPSHOT_BUILDER_VERSION,
        "uncertainty": {
            "kind": "none",
            "note": "point estimate from latest eligible source-backed evidence",
        },
        "transformation_id": TRANSFORMATION_ID,
        "transformation_version": TRANSFORMATION_VERSION,
        "transformed_at": _now_z(),
        "input_artifact_sha256": input_artifact_sha256,
        "confidence": "CANDIDATE",
        "mapping_status": "CANDIDATE",
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "snapshot_builder_version": SNAPSHOT_BUILDER_VERSION,
        "source_system_context": SOURCE_SYSTEM_ID,
    }


@dataclass
class StateSnapshotComponent:
    component_id: str
    snapshot_id: str
    variable_key: str
    raw_code: str | None
    raw_value: str | None
    numeric_value: float | None
    text_value: str | None
    categorical_value: str | None = None
    boolean_value: bool | None = None
    raw_unit: str | None = None
    missingness_status: str = "observed"
    missingness_reason: str | None = None
    selection_status: str = "single_value"
    input_record_references: list[dict[str, str]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    source_observation_ids: list[str] = field(default_factory=list)
    confidence: str | None = "CANDIDATE"
    concept_id: str | None = None
    normalized_unit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def assert_typed_xor(self) -> None:
        status = typed_value_xor_status(self)
        if not status["ok"]:
            raise ValueError(f"typed_value_xor_violated: {status}")


@dataclass
class EvidenceStateSnapshot:
    snapshot_id: str
    subject_id: str
    snapshot_at: str
    snapshot_kind: str
    source_event_cutoff: str
    provenance: dict[str, Any]
    components: list[StateSnapshotComponent] = field(default_factory=list)
    excluded_future_count: int = 0
    conflict_count: int = 0
    completeness: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def state_vector(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for c in self.components:
            if c.selection_status != "single_value":
                continue
            if c.numeric_value is None:
                continue
            if c.missingness_status != "observed":
                continue
            out[c.variable_key] = float(c.numeric_value)
        return out


def _component_id(snapshot_id: str, variable_key: str) -> str:
    return hashlib.sha256(f"{snapshot_id}|{variable_key}".encode()).hexdigest()


def _snapshot_id(subject_id: str, snapshot_at: str, kind: str) -> str:
    return hashlib.sha256(f"snap|{subject_id}|{snapshot_at}|{kind}".encode()).hexdigest()


def build_evidence_state_snapshot(
    *,
    subject_id: str,
    snapshot_at: datetime | str,
    source_event_cutoff: datetime | str | None = None,
    snapshot_kind: str = "baseline",
    characteristics: list[dict[str, Any]],
    encounters: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    components: list[dict[str, Any]],
    input_artifact_sha256: str = "unset",
) -> EvidenceStateSnapshot:
    snap_at = parse_ts(snapshot_at)
    if snap_at is None:
        raise ValueError("snapshot_at is required and must be a valid datetime")
    cutoff = parse_ts(source_event_cutoff) if source_event_cutoff is not None else snap_at
    if cutoff is None:
        raise ValueError("source_event_cutoff must be a valid datetime")
    if cutoff > snap_at:
        raise ValueError("source_event_cutoff must be <= snapshot_at")

    snap_at_s = iso_z(snap_at)
    cutoff_s = iso_z(cutoff)
    sid = _snapshot_id(subject_id, snap_at_s, snapshot_kind)

    all_refs: list[dict[str, str]] = []
    excluded_future = 0
    usable_obs: dict[str, dict[str, Any]] = {}
    for obs in observations:
        if obs.get("subject_id") != subject_id:
            continue
        clinical = clinical_time_for_observation(obs)
        recorded = parse_ts(obs.get("recorded_at"))
        if event_after_cutoff(clinical=clinical, recorded=recorded, cutoff=cutoff):
            excluded_future += 1
            continue
        usable_obs[str(obs["observation_id"])] = obs

    for enc in encounters:
        if enc.get("subject_id") != subject_id:
            continue
        clinical = clinical_time_for_encounter(enc)
        recorded = parse_ts(enc.get("recorded_at"))
        if event_after_cutoff(clinical=clinical, recorded=recorded, cutoff=cutoff):
            excluded_future += 1

    char_comps: list[StateSnapshotComponent] = []
    for ch in characteristics:
        if ch.get("subject_id") != subject_id:
            continue
        recorded = parse_ts(ch.get("recorded_at") or ch.get("effective_at"))
        if recorded is not None and recorded > cutoff:
            excluded_future += 1
            continue
        code = str(ch.get("characteristic_code") or "unknown")
        refs = [
            {
                "entity_type": "SubjectCharacteristic",
                "entity_id": str(ch.get("characteristic_id")),
                "role": "contributor",
            }
        ]
        all_refs.extend(refs)
        raw = None if ch.get("raw_value") is None else str(ch.get("raw_value"))
        # categorical typed value; raw_value is not a typed value
        comp = StateSnapshotComponent(
            component_id=_component_id(sid, f"char:{code}"),
            snapshot_id=sid,
            variable_key=f"characteristic.{code}",
            raw_code=code,
            raw_value=raw,
            numeric_value=None,
            text_value=None,
            categorical_value=raw,
            boolean_value=None,
            raw_unit=None,
            missingness_status="observed" if raw is not None else "missing",
            missingness_reason=None if raw is not None else "missing_characteristic_value",
            selection_status="single_value",
            input_record_references=refs,
            provenance=computed_provenance(refs=refs, input_artifact_sha256=input_artifact_sha256),
        )
        if raw is None:
            comp.categorical_value = None
        comp.assert_typed_xor()
        char_comps.append(comp)

    by_code: dict[str, list[tuple[datetime | None, dict[str, Any], dict[str, Any]]]] = {}
    for c in components:
        oid = str(c["observation_id"])
        obs = usable_obs.get(oid)
        if not obs:
            continue
        clinical = clinical_time_for_observation(obs)
        code = str(c.get("raw_code") or "unknown")
        by_code.setdefault(code, []).append((clinical, c, obs))

    lab_comps: list[StateSnapshotComponent] = []
    conflict_count = 0
    for code, candidates in sorted(by_code.items()):

        def sort_key(item: tuple[datetime | None, dict[str, Any], dict[str, Any]]) -> tuple:
            clinical, comp, _obs = item
            ts = clinical or datetime.min.replace(tzinfo=UTC)
            return (ts, str(comp.get("component_id")))

        ranked = sorted(candidates, key=sort_key)
        latest_ts = ranked[-1][0]
        if latest_ts is None:
            values = {(c.get("numeric_value"), c.get("raw_value")) for _, c, _ in ranked}
            if len(ranked) > 1:
                conflict_count += 1
                status = "conflict_unresolved"
            else:
                status = "single_value"
            chosen = ranked[-1]
            _ = values
        else:
            tie_group = [x for x in ranked if x[0] == latest_ts]
            if len(tie_group) > 1:
                conflict_count += 1
                status = "conflict_unresolved"
            else:
                status = "single_value"
            chosen = tie_group[-1]

        _clinical, src_comp, obs = chosen
        refs = [
            {
                "entity_type": "ObservationComponent",
                "entity_id": str(src_comp.get("component_id")),
                "role": "contributor",
            },
            {
                "entity_type": "Observation",
                "entity_id": str(obs.get("observation_id")),
                "role": "parent_observation",
            },
        ]
        all_refs.extend(refs)
        num = src_comp.get("numeric_value")
        raw = None if src_comp.get("raw_value") is None else str(src_comp.get("raw_value"))
        if num is not None:
            # XOR: numeric only; raw_value holds source representation separately
            typed_num = float(num)
            typed_text = None
            typed_cat = None
            miss = "observed"
            miss_reason = None
        elif raw is not None and str(raw).strip() != "":
            typed_num = None
            typed_text = raw
            typed_cat = None
            miss = "observed"
            miss_reason = None
        else:
            typed_num = None
            typed_text = None
            typed_cat = None
            miss = "missing"
            miss_reason = "no_numeric_or_raw_value"

        lab = StateSnapshotComponent(
            component_id=_component_id(sid, f"lab:{code}"),
            snapshot_id=sid,
            variable_key=code,
            raw_code=code,
            raw_value=raw,
            numeric_value=typed_num,
            text_value=typed_text,
            categorical_value=typed_cat,
            boolean_value=None,
            raw_unit=src_comp.get("raw_unit"),
            missingness_status=miss,
            missingness_reason=miss_reason,
            selection_status=status,
            input_record_references=refs,
            provenance=computed_provenance(refs=refs, input_artifact_sha256=input_artifact_sha256),
            source_observation_ids=[str(obs.get("observation_id")), str(src_comp.get("component_id"))],
        )
        lab.assert_typed_xor()
        lab_comps.append(lab)

    # Snapshot-level refs = union of component refs (deduped)
    seen: set[str] = set()
    snap_refs: list[dict[str, str]] = []
    for r in all_refs:
        key = f"{r.get('entity_type')}:{r.get('entity_id')}"
        if key in seen:
            continue
        seen.add(key)
        snap_refs.append(r)
    if not snap_refs:
        snap_refs = [{"entity_type": "Subject", "entity_id": subject_id, "role": "subject_scope"}]

    snap_prov = computed_provenance(
        refs=snap_refs,
        input_artifact_sha256=input_artifact_sha256,
        method="evidence_state_snapshot_aggregate",
    )
    snap_prov["snapshot_at"] = snap_at_s
    snap_prov["source_event_cutoff"] = cutoff_s

    return EvidenceStateSnapshot(
        snapshot_id=sid,
        subject_id=subject_id,
        snapshot_at=snap_at_s,
        snapshot_kind=snapshot_kind,
        source_event_cutoff=cutoff_s,
        provenance=snap_prov,
        components=char_comps + lab_comps,
        excluded_future_count=excluded_future,
        conflict_count=conflict_count,
        completeness={
            "demographics_count": len(char_comps),
            "lab_count": len(lab_comps),
            "imputed_count": 0,
            "conflict_count": conflict_count,
            "excluded_future_count": excluded_future,
        },
    )


def snapshot_content_hash(snapshot: EvidenceStateSnapshot) -> str:
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "subject_id": snapshot.subject_id,
        "snapshot_at": snapshot.snapshot_at,
        "snapshot_kind": snapshot.snapshot_kind,
        "source_event_cutoff": snapshot.source_event_cutoff,
        "components": [
            {
                "variable_key": c.variable_key,
                "numeric_value": c.numeric_value,
                "text_value": c.text_value,
                "categorical_value": c.categorical_value,
                "boolean_value": c.boolean_value,
                "raw_value": c.raw_value,
                "selection_status": c.selection_status,
                "missingness_status": c.missingness_status,
                "input_record_references": c.input_record_references,
            }
            for c in sorted(snapshot.components, key=lambda x: x.variable_key)
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
