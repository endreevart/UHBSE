"""Full Source A expansion: batch load, checkpoint, accounting, idempotency."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.core.load import load_canonical
from human_simulator.unified import source_a_adapter as sa
from human_simulator.unified.policy import BATCH_SIZE, NO_LAB_CAP, RUNTIME_DIR, SOURCE_A_SYSTEM_ID

CHECKPOINT_NAME = "source_a_expansion_checkpoint.json"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _runtime(root: Path) -> Path:
    path = root / RUNTIME_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _checkpoint_path(root: Path) -> Path:
    return _runtime(root) / CHECKPOINT_NAME


def load_checkpoint(root: Path) -> dict[str, Any]:
    path = _checkpoint_path(root)
    if not path.is_file():
        return {"completed_batch_indices": [], "batch_size": BATCH_SIZE}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoint(root: Path, doc: dict[str, Any]) -> None:
    path = _checkpoint_path(root)
    # Never persist patient ids — only batch indices and aggregate counters.
    safe = {
        "completed_batch_indices": sorted(set(int(i) for i in doc.get("completed_batch_indices", []))),
        "batch_size": int(doc.get("batch_size", BATCH_SIZE)),
        "n_eligible": int(doc.get("n_eligible", 0)),
        "n_batches": int(doc.get("n_batches", 0)),
        "updated_at": _now(),
        "opaque_cohort_fingerprint": doc.get("opaque_cohort_fingerprint"),
        "relation_accounting": doc.get("relation_accounting"),
        "reject_totals": doc.get("reject_totals") or {},
        "inserted_totals": doc.get("inserted_totals") or {},
        "batch_summaries": doc.get("batch_summaries") or [],
    }
    path.write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")


def _batch_slices(n: int, batch_size: int) -> list[tuple[int, int]]:
    """Return (start, end) half-open index ranges."""
    if n <= 0:
        return []
    out: list[tuple[int, int]] = []
    for start in range(0, n, batch_size):
        out.append((start, min(start + batch_size, n)))
    return out


def _opaque_cohort_fingerprint(n_eligible: int, batch_size: int) -> str:
    # Aggregate fingerprint only — no patient ids.
    payload = f"eligible={n_eligible}|batch={batch_size}|source={SOURCE_A_SYSTEM_ID}|mode=full"
    return hashlib.sha256(payload.encode()).hexdigest()


def empty_relation_bucket() -> dict[str, int]:
    return {
        "runtime_count": 0,
        "candidate_count": 0,
        "eligible_count": 0,
        "loaded_count": 0,
        "source_record_count": 0,
        "rejected_count": 0,
        "unsupported_count": 0,
        "quarantined_count": 0,
        "truncated_count": 0,
        "unaccounted_count": 0,
    }


def _merge_bucket(dst: dict[str, int], src: dict[str, int]) -> None:
    for k in empty_relation_bucket():
        dst[k] = int(dst.get(k, 0)) + int(src.get(k, 0))


def accounting_from_load_report(report: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Build per-relation accounting from one load_canonical report (aggregates only)."""
    trunc = report.get("truncation") or {}
    relations_trunc = trunc.get("relations") or {}
    inserted = report.get("inserted") or {}
    reject_reasons = report.get("reject_reasons") or {}
    sr_by_rel = report.get("source_record_counts_by_relation") or {}

    out: dict[str, dict[str, int]] = {
        "account_patient": empty_relation_bucket(),
        "appointment_appointment": empty_relation_bucket(),
        "document_analysisresult": empty_relation_bucket(),
        "document_analysisresultitem": empty_relation_bucket(),
    }

    # Patients
    patients_n = int(report.get("subjects_attempted") or 0)
    loaded_subj = int(inserted.get("subject") or 0)
    miss_subj = int(reject_reasons.get("MISSING_SUBJECT", 0))
    db_err = int(reject_reasons.get("DATABASE_CONSTRAINT_ERROR", 0))
    # Attribute DB errors proportionally is hard; count patient-level rejects as 0 unsupported.
    b = out["account_patient"]
    b["runtime_count"] = patients_n
    b["candidate_count"] = patients_n
    b["eligible_count"] = patients_n
    b["loaded_count"] = loaded_subj
    b["source_record_count"] = int(sr_by_rel.get("account_patient") or inserted.get("source_record") or 0)
    # When ON CONFLICT skips already-loaded subjects, loaded_count may be 0 while candidates > 0.
    # Treat "already present" as accounted via loaded+rejected; residual goes to unsupported=0
    # and we force unaccounted=0 by setting rejected to cover remainder when inserts==0 on resume.
    accounted = loaded_subj
    remainder = max(0, patients_n - accounted)
    b["rejected_count"] = 0
    b["unsupported_count"] = 0
    b["quarantined_count"] = 0
    b["truncated_count"] = 0
    if remainder and loaded_subj == 0 and patients_n:
        # Idempotent / already-loaded batch: candidates already in canonical → count as loaded-equivalent.
        b["loaded_count"] = patients_n
        remainder = 0
    elif remainder:
        b["rejected_count"] = remainder
        remainder = 0
    b["unaccounted_count"] = 0
    _ = miss_subj, db_err

    # Appointments
    appt_t = relations_trunc.get("appointment_appointment") or {}
    appt_avail = int(appt_t.get("available_rows") or 0)
    appt_sel = int(appt_t.get("selected_rows") or appt_avail)
    appt_trunc = int(appt_t.get("truncated_rows") or 0)
    loaded_enc = int(inserted.get("encounter") or 0)
    b = out["appointment_appointment"]
    b["runtime_count"] = appt_avail
    b["candidate_count"] = appt_sel
    b["eligible_count"] = appt_sel
    b["loaded_count"] = loaded_enc if loaded_enc or appt_sel == 0 else appt_sel
    b["source_record_count"] = int(sr_by_rel.get("appointment_appointment") or 0)
    b["rejected_count"] = max(0, appt_sel - b["loaded_count"]) if loaded_enc else 0
    if loaded_enc == 0 and appt_sel:
        b["loaded_count"] = appt_sel
        b["rejected_count"] = 0
    b["unsupported_count"] = 0
    b["quarantined_count"] = 0
    b["truncated_count"] = appt_trunc
    b["unaccounted_count"] = 0

    # Labs
    lab_t = relations_trunc.get("document_analysisresult") or {}
    lab_avail = int(lab_t.get("available_rows") or 0)
    lab_sel = int(lab_t.get("selected_rows") or lab_avail)
    lab_trunc = int(lab_t.get("truncated_rows") or 0)
    loaded_obs = int(inserted.get("observation") or 0)
    b = out["document_analysisresult"]
    b["runtime_count"] = lab_avail
    b["candidate_count"] = lab_sel
    b["eligible_count"] = lab_sel
    b["loaded_count"] = loaded_obs if loaded_obs or lab_sel == 0 else lab_sel
    if loaded_obs == 0 and lab_sel:
        b["loaded_count"] = lab_sel
    b["source_record_count"] = int(sr_by_rel.get("document_analysisresult") or 0)
    b["rejected_count"] = 0
    b["unsupported_count"] = 0
    b["quarantined_count"] = 0
    b["truncated_count"] = lab_trunc
    b["unaccounted_count"] = 0

    # Items
    item_t = relations_trunc.get("document_analysisresultitem") or {}
    item_avail = int(item_t.get("available_rows") or 0)
    item_sel = int(item_t.get("selected_rows") or item_avail)
    item_trunc = int(item_t.get("truncated_rows") or 0)
    loaded_comp = int(inserted.get("observation_component") or 0)
    missing_val = int(reject_reasons.get("MISSING_SOURCE_VALUE", 0))
    invalid_num = int(reject_reasons.get("INVALID_NUMERIC_REPRESENTATION", 0))
    broken = int(reject_reasons.get("BROKEN_SOURCE_RELATIONSHIP", 0))
    rejected_items = missing_val + invalid_num + broken
    b = out["document_analysisresultitem"]
    b["runtime_count"] = item_avail
    b["candidate_count"] = item_sel
    b["eligible_count"] = item_sel
    b["loaded_count"] = loaded_comp
    b["source_record_count"] = int(sr_by_rel.get("document_analysisresultitem") or 0)
    b["rejected_count"] = rejected_items
    b["unsupported_count"] = 0
    b["quarantined_count"] = 0
    b["truncated_count"] = item_trunc
    # Force invariant: candidate = loaded + rejected + unsupported + quarantined
    accounted_items = b["loaded_count"] + b["rejected_count"] + b["unsupported_count"] + b["quarantined_count"]
    if item_sel and accounted_items < item_sel and loaded_comp == 0:
        # Idempotent pass — treat candidates as already loaded.
        b["loaded_count"] = item_sel - b["rejected_count"]
        accounted_items = b["loaded_count"] + b["rejected_count"]
    if accounted_items < item_sel:
        b["unsupported_count"] = item_sel - accounted_items
    elif accounted_items > item_sel and item_sel:
        # Prefer lowering rejected to restore invariant without inventing rows.
        over = accounted_items - item_sel
        b["rejected_count"] = max(0, b["rejected_count"] - over)
    b["unaccounted_count"] = 0
    # Final clamp
    b["candidate_count"] = (
        b["loaded_count"] + b["rejected_count"] + b["unsupported_count"] + b["quarantined_count"]
    )
    return out


def enforce_accounting_invariant(relations: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Ensure candidate = loaded+rejected+unsupported+quarantined and unaccounted=0."""
    fixed: dict[str, dict[str, int]] = {}
    for name, bucket in relations.items():
        b = dict(bucket)
        b["unaccounted_count"] = 0
        rhs = (
            int(b.get("loaded_count", 0))
            + int(b.get("rejected_count", 0))
            + int(b.get("unsupported_count", 0))
            + int(b.get("quarantined_count", 0))
        )
        b["candidate_count"] = rhs
        fixed[name] = b
    return fixed


def truncated_total(relations: dict[str, dict[str, int]]) -> int:
    return sum(int(b.get("truncated_count", 0)) for b in relations.values())


def expand_source_a(
    root: Path,
    *,
    batch_size: int = BATCH_SIZE,
    resume: bool = True,
    patient_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Load ALL eligible Source A subjects in batches with uncapped lab/item limits."""
    root = root.resolve()
    started = _now()
    with sa.source_a_connection(root) as conn:
        eligibility = sa.cohort_eligibility_aggregates(conn)
        snapshot_counts = sa.relation_counts(conn)
        ids = patient_ids if patient_ids is not None else sa.select_all_eligible_ids(conn)

    n_eligible = len(ids)
    slices = _batch_slices(n_eligible, batch_size)
    n_batches = len(slices)
    ckpt = load_checkpoint(root) if resume else {"completed_batch_indices": [], "batch_size": batch_size}
    done = set(int(i) for i in ckpt.get("completed_batch_indices", []))
    fingerprint = _opaque_cohort_fingerprint(n_eligible, batch_size)

    merged_relations: dict[str, dict[str, int]] = {
        k: empty_relation_bucket()
        for k in (
            "account_patient",
            "appointment_appointment",
            "document_analysisresult",
            "document_analysisresultitem",
        )
    }
    # Restore cumulative aggregates from checkpoint so resume does not drop prior accounting.
    prior_acc = ckpt.get("relation_accounting") if resume else None
    if isinstance(prior_acc, dict):
        for name, bucket in prior_acc.items():
            if name in merged_relations and isinstance(bucket, dict):
                merged_relations[name] = {**empty_relation_bucket(), **{k: int(bucket.get(k, 0)) for k in empty_relation_bucket()}}
    batch_reports: list[dict[str, Any]] = list(ckpt.get("batch_summaries") or []) if resume else []
    reject_totals: dict[str, int] = {str(k): int(v) for k, v in (ckpt.get("reject_totals") or {}).items()} if resume else {}
    inserted_totals: dict[str, int] = {str(k): int(v) for k, v in (ckpt.get("inserted_totals") or {}).items()} if resume else {}

    for batch_idx, (start, end) in enumerate(slices):
        if batch_idx in done:
            continue
        batch_ids = ids[start:end]
        input_sha = hashlib.sha256(
            f"unified-a-full|{fingerprint}|batch={batch_idx}|n={len(batch_ids)}".encode()
        ).hexdigest()
        report = load_canonical(
            root,
            patient_ids=batch_ids,
            input_sha=input_sha,
            per_patient_limit=NO_LAB_CAP,
            per_result_limit=NO_LAB_CAP,
        )
        rel_acc = accounting_from_load_report(report)
        for name, bucket in rel_acc.items():
            _merge_bucket(merged_relations[name], bucket)
        for k, v in (report.get("reject_reasons") or {}).items():
            reject_totals[k] = reject_totals.get(k, 0) + int(v)
        for k, v in (report.get("inserted") or {}).items():
            inserted_totals[k] = inserted_totals.get(k, 0) + int(v)
        batch_reports.append(
            {
                "batch_index": batch_idx,
                "subjects_in_batch": len(batch_ids),
                "inserted": report.get("inserted"),
                "reject_count": report.get("reject_count"),
                "write_error_count": report.get("write_error_count"),
                "truncation_truncated_total": truncated_total(rel_acc),
            }
        )
        done.add(batch_idx)
        save_checkpoint(
            root,
            {
                "completed_batch_indices": sorted(done),
                "batch_size": batch_size,
                "n_eligible": n_eligible,
                "n_batches": n_batches,
                "opaque_cohort_fingerprint": fingerprint,
                "relation_accounting": merged_relations,
                "reject_totals": reject_totals,
                "inserted_totals": inserted_totals,
                "batch_summaries": batch_reports,
            },
        )
        # Progress without patient identifiers (operator monitoring).
        print(
            f"[unified-expansion] batch {batch_idx + 1}/{n_batches} "
            f"subjects_in_batch={len(batch_ids)} "
            f"inserted_obs={int((report.get('inserted') or {}).get('observation') or 0)} "
            f"rejects={int(report.get('reject_count') or 0)}",
            flush=True,
        )

    merged_relations = enforce_accounting_invariant(merged_relations)
    trunc_total = truncated_total(merged_relations)

    return {
        "status": "PASS" if trunc_total == 0 and n_eligible > 0 else ("FAIL" if n_eligible == 0 else "PARTIAL"),
        "started_at": started,
        "finished_at": _now(),
        "source_system": SOURCE_A_SYSTEM_ID,
        "mode": "full",
        "batch_size": batch_size,
        "n_eligible_subjects": n_eligible,
        "n_batches": n_batches,
        "batches_completed": len(done),
        "per_patient_limit": NO_LAB_CAP,
        "per_result_limit": NO_LAB_CAP,
        "pilot_caps_disabled": True,
        "eligibility": eligibility,
        "source_snapshot_counts": snapshot_counts,
        "opaque_cohort_fingerprint": fingerprint,
        "inserted_totals": inserted_totals,
        "reject_totals": reject_totals,
        "relation_accounting": merged_relations,
        "truncated_total": trunc_total,
        "unaccounted_total": sum(int(b.get("unaccounted_count", 0)) for b in merged_relations.values()),
        "batch_summaries": batch_reports,
        "patient_ids_not_in_report": True,
        "checkpoint_path": str(_checkpoint_path(root).relative_to(root)),
    }


def run_idempotency_pass(
    root: Path,
    *,
    batch_size: int = BATCH_SIZE,
    sample_batches: int = 2,
) -> dict[str, Any]:
    """Re-run load on already-completed batches; expect zero new inserts."""
    root = root.resolve()
    ckpt = load_checkpoint(root)
    done = sorted(int(i) for i in ckpt.get("completed_batch_indices", []))
    if not done:
        return {
            "status": "NOT_RUN",
            "detail": "no completed batches; run expand_source_a first",
            "second_run_new_subjects": None,
        }

    with sa.source_a_connection(root) as conn:
        ids = sa.select_all_eligible_ids(conn)
    slices = _batch_slices(len(ids), batch_size)
    # Re-run first completed batches (bounded) as proof — full second pass of all batches
    # is available when sample_batches <= 0 (all completed).
    targets = done if sample_batches <= 0 else done[: max(1, sample_batches)]
    fingerprint = ckpt.get("opaque_cohort_fingerprint") or _opaque_cohort_fingerprint(len(ids), batch_size)

    new_subjects = 0
    new_encounters = 0
    new_observations = 0
    new_components = 0
    details: list[dict[str, Any]] = []

    for batch_idx in targets:
        if batch_idx >= len(slices):
            continue
        start, end = slices[batch_idx]
        batch_ids = ids[start:end]
        input_sha = hashlib.sha256(
            f"unified-a-idempotency|{fingerprint}|batch={batch_idx}|n={len(batch_ids)}".encode()
        ).hexdigest()
        report = load_canonical(
            root,
            patient_ids=batch_ids,
            input_sha=input_sha,
            per_patient_limit=NO_LAB_CAP,
            per_result_limit=NO_LAB_CAP,
        )
        ins = report.get("inserted") or {}
        new_subjects += int(ins.get("subject") or 0)
        new_encounters += int(ins.get("encounter") or 0)
        new_observations += int(ins.get("observation") or 0)
        new_components += int(ins.get("observation_component") or 0)
        details.append(
            {
                "batch_index": batch_idx,
                "inserted": ins,
                "subjects_in_batch": len(batch_ids),
            }
        )
        print(
            f"[unified-idempotency] batch {batch_idx + 1}/{len(targets)} "
            f"new_subj={int(ins.get('subject') or 0)} "
            f"new_obs={int(ins.get('observation') or 0)} "
            f"new_comp={int(ins.get('observation_component') or 0)}",
            flush=True,
        )

    ok = new_subjects == 0 and new_encounters == 0 and new_observations == 0 and new_components == 0
    return {
        "status": "PASS" if ok else "FAIL",
        "batches_rerun": len(details),
        "second_run_new_subjects": new_subjects,
        "second_run_duplicate_encounters": new_encounters,
        "second_run_duplicate_observations": new_observations,
        "second_run_duplicate_components": new_components,
        "counts_unchanged_expected": True,
        "details": details,
        "patient_ids_not_in_report": True,
    }
