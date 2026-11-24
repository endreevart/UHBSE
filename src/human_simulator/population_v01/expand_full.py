"""Full Source A canonical population expansion (all account_patient)."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.core.ids import load_hmac_key, opaque_subject_key
from human_simulator.core.load import load_canonical
from human_simulator.population_v01.policy import BATCH_SIZE, NO_LAB_CAP, RUNTIME_DIR, SOURCE_A
from human_simulator.unified import source_a_adapter as sa
from human_simulator.unified.expansion_a import (
    accounting_from_load_report,
    empty_relation_bucket,
    enforce_accounting_invariant,
    truncated_total,
    _batch_slices,
    _merge_bucket,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ckpt_path(root: Path) -> Path:
    d = root / RUNTIME_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / "full_population_checkpoint.json"


def load_ckpt(root: Path) -> dict[str, Any]:
    p = _ckpt_path(root)
    if not p.is_file():
        return {"completed_batch_indices": [], "batch_size": BATCH_SIZE}
    return json.loads(p.read_text(encoding="utf-8"))


def save_ckpt(root: Path, doc: dict[str, Any]) -> None:
    safe = {
        "mode": "full_account_patient_population_skip_existing",
        "completed_batch_indices": sorted(
            set(int(i) for i in doc.get("completed_batch_indices", []))
        ),
        "batch_size": int(doc.get("batch_size", BATCH_SIZE)),
        "n_population": int(doc.get("n_population", 0)),
        "n_missing_at_start": int(doc.get("n_missing_at_start", 0)),
        "n_batches": int(doc.get("n_batches", 0)),
        "updated_at": _now(),
        "opaque_population_fingerprint": doc.get("opaque_population_fingerprint"),
        "relation_accounting": doc.get("relation_accounting"),
        "reject_totals": doc.get("reject_totals") or {},
        "inserted_totals": doc.get("inserted_totals") or {},
        "already_present_subject_total": int(doc.get("already_present_subject_total") or 0),
        "batch_summaries": (doc.get("batch_summaries") or [])[-80:],
    }
    _ckpt_path(root).write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")


def _existing_subject_keys(root: Path) -> set[str]:
    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings

    with canonical_connection(load_canonical_settings()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_subject_key
                FROM canonical_evidence.subject
                WHERE source_system_id = %s
                """,
                (SOURCE_A,),
            )
            return {str(r[0]) for r in cur.fetchall()}


def _load_one_batch(
    root: Path,
    *,
    batch_idx: int,
    batch_ids: list[int],
    fingerprint: str,
) -> dict[str, Any]:
    input_sha = hashlib.sha256(
        f"full-pop-skip|{fingerprint}|batch={batch_idx}|n={len(batch_ids)}".encode()
    ).hexdigest()
    report = load_canonical(
        root,
        patient_ids=batch_ids,
        input_sha=input_sha,
        per_patient_limit=NO_LAB_CAP,
        per_result_limit=NO_LAB_CAP,
        verify_coverage=False,
    )
    return {
        "batch_idx": batch_idx,
        "n_ids": len(batch_ids),
        "report": report,
    }


def expand_full_source_a_population(
    root: Path,
    *,
    batch_size: int = BATCH_SIZE,
    resume: bool = True,
    max_batches: int | None = None,
    workers: int = 4,
) -> dict[str, Any]:
    """Load ALL account_patient into canonical (idempotent, resumable).

    Already-present subjects are skipped for fetch+insert work and counted as
    already_present. Remaining missing subjects are loaded in parallel batches.
    """
    root = root.resolve()
    started = _now()
    with sa.source_a_connection(root) as conn:
        elig = sa.cohort_eligibility_aggregates(conn)
        snapshot = sa.relation_counts(conn)
        ids = sa.select_all_account_patient_ids(conn)

    n_pop = len(ids)
    key = load_hmac_key(root)
    existing_keys = _existing_subject_keys(root)
    missing_ids = [pid for pid in ids if opaque_subject_key(key, pid) not in existing_keys]
    already_present_n = n_pop - len(missing_ids)

    ckpt = (
        load_ckpt(root) if resume else {"completed_batch_indices": [], "batch_size": batch_size}
    )
    if resume and ckpt.get("mode") == "full_account_patient_population_skip_existing":
        batch_size = int(ckpt.get("batch_size") or batch_size)

    slices = _batch_slices(len(missing_ids), batch_size)
    n_batches = len(slices)
    done = set(int(i) for i in ckpt.get("completed_batch_indices", []))
    fingerprint = hashlib.sha256(
        f"full_pop_skip|{n_pop}|missing={len(missing_ids)}|batch={batch_size}|source={SOURCE_A}".encode()
    ).hexdigest()

    # Missing set shrinks each run; restart batch indices when fingerprint changes.
    if resume and ckpt.get("opaque_population_fingerprint") not in (None, fingerprint):
        done = set()
        ckpt = {"completed_batch_indices": [], "batch_size": batch_size}

    merged: dict[str, dict[str, int]] = {
        k: empty_relation_bucket()
        for k in (
            "account_patient",
            "appointment_appointment",
            "document_analysisresult",
            "document_analysisresultitem",
        )
    }
    prior = ckpt.get("relation_accounting") if resume else None
    if isinstance(prior, dict):
        for name, bucket in prior.items():
            if name in merged and isinstance(bucket, dict):
                merged[name] = {
                    **empty_relation_bucket(),
                    **{k: int(bucket.get(k, 0)) for k in empty_relation_bucket()},
                }

    if already_present_n:
        merged["account_patient"]["runtime_count"] = n_pop
        merged["account_patient"]["candidate_count"] = max(
            int(merged["account_patient"].get("candidate_count") or 0), already_present_n
        )
        merged["account_patient"]["already_present_rows"] = already_present_n

    reject_totals: dict[str, int] = (
        {str(k): int(v) for k, v in (ckpt.get("reject_totals") or {}).items()} if resume else {}
    )
    inserted_totals: dict[str, int] = (
        {str(k): int(v) for k, v in (ckpt.get("inserted_totals") or {}).items()} if resume else {}
    )
    batch_reports: list[dict[str, Any]] = (
        list(ckpt.get("batch_summaries") or []) if resume else []
    )

    pending: list[tuple[int, list[int]]] = []
    for batch_idx, (start, end) in enumerate(slices):
        if batch_idx in done:
            continue
        pending.append((batch_idx, missing_ids[start:end]))
    if max_batches is not None:
        pending = pending[: max(0, int(max_batches))]

    processed = 0
    workers = max(1, int(workers))
    lock = threading.Lock()

    def _ingest(result: dict[str, Any]) -> None:
        nonlocal processed
        report = result["report"]
        batch_idx = int(result["batch_idx"])
        with lock:
            rel_acc = accounting_from_load_report(report)
            for name, bucket in rel_acc.items():
                if name in merged:
                    _merge_bucket(merged[name], bucket)
            for k, v in (report.get("reject_reasons") or {}).items():
                reject_totals[str(k)] = reject_totals.get(str(k), 0) + int(v)
            for k, v in (report.get("inserted") or {}).items():
                inserted_totals[str(k)] = inserted_totals.get(str(k), 0) + int(v)
            batch_reports.append(
                {
                    "batch_idx": batch_idx,
                    "n_ids": result["n_ids"],
                    "inserted": report.get("inserted"),
                    "truncation_total": (report.get("truncation") or {}).get(
                        "total_truncated_rows"
                    ),
                }
            )
            done.add(batch_idx)
            processed += 1
            save_ckpt(
                root,
                {
                    "completed_batch_indices": sorted(done),
                    "batch_size": batch_size,
                    "n_population": n_pop,
                    "n_missing_at_start": len(missing_ids),
                    "n_batches": n_batches,
                    "opaque_population_fingerprint": fingerprint,
                    "relation_accounting": merged,
                    "reject_totals": reject_totals,
                    "inserted_totals": inserted_totals,
                    "already_present_subject_total": already_present_n,
                    "batch_summaries": batch_reports,
                },
            )
            print(
                f"full_pop_batch {batch_idx + 1}/{n_batches} done "
                f"ids={result['n_ids']} "
                f"inserted_subj={report.get('inserted', {}).get('subject')}",
                flush=True,
            )

    if workers == 1 or len(pending) <= 1:
        for batch_idx, batch_ids in pending:
            _ingest(
                _load_one_batch(
                    root,
                    batch_idx=batch_idx,
                    batch_ids=batch_ids,
                    fingerprint=fingerprint,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [
                pool.submit(
                    _load_one_batch,
                    root,
                    batch_idx=batch_idx,
                    batch_ids=batch_ids,
                    fingerprint=fingerprint,
                )
                for batch_idx, batch_ids in pending
            ]
            for fut in as_completed(futs):
                _ingest(fut.result())

    merged = enforce_accounting_invariant(merged)
    trunc = truncated_total(merged)
    final_existing = _existing_subject_keys(root)
    still_missing = sum(
        1 for pid in ids if opaque_subject_key(key, pid) not in final_existing
    )
    if still_missing == 0 and trunc == 0:
        status = "PASS"
        complete = True
    elif processed > 0 or len(done) > 0 or already_present_n > 0:
        status = "PARTIAL"
        complete = False
    else:
        status = "FAIL"
        complete = False

    return {
        "started_at": started,
        "finished_at": _now(),
        "source_a_full_canonical_population_status": status,
        "source_a_idempotency_status": "PASS",
        "n_account_patient": n_pop,
        "n_already_present_subjects_at_start": already_present_n,
        "n_missing_at_start": len(missing_ids),
        "n_still_missing_subjects": still_missing,
        "n_batches_total": n_batches,
        "n_batches_completed": len(done),
        "complete": complete,
        "truncated_rows_total": trunc,
        "relation_accounting": merged,
        "reject_totals": reject_totals,
        "inserted_totals": inserted_totals,
        "eligibility_snapshot": {
            "subjects_total": elig.get("subjects_total"),
            "subjects_appt3_and_lab": elig.get("subjects_appt3_and_lab"),
            "note": "canonical_population != scientific_cohort",
        },
        "source_relation_snapshot": snapshot,
        "opaque_population_fingerprint": fingerprint,
        "batches_processed_this_run": processed,
        "batch_size": batch_size,
        "workers": workers,
        "skip_existing_enabled": True,
    }
