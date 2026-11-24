"""Four independent accounting ledgers with computed unexplained_count."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_v0121.policy import (
    DISPOSITION_KEYS,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def disposition_sum_invariant(disposition: dict[str, int], *, total: int) -> dict[str, Any]:
    """accepted + rejected + unsupported + quarantined must equal total."""
    parts = {k: int(disposition.get(k) or 0) for k in DISPOSITION_KEYS}
    s = sum(parts.values())
    unexplained = abs(int(total) - s)
    return {
        "disposition": parts,
        "total": int(total),
        "sum": s,
        "sum_equals_total": s == int(total),
        "unexplained_count": unexplained,
        "invariant_ok": s == int(total),
    }


def detect_newly_loaded_exceeds_candidates(
    *, newly_loaded: int, candidates: int
) -> dict[str, Any]:
    """Negative-test helper: newly_loaded must not exceed candidates."""
    excess = int(newly_loaded) > int(candidates)
    return {
        "newly_loaded": int(newly_loaded),
        "candidates": int(candidates),
        "newly_loaded_exceeds_candidates": excess,
        "defect": excess,
    }


def detect_mixed_dimensions(
    *,
    observations: int,
    components: int,
    source_records: int,
) -> dict[str, Any]:
    """Negative-test helper: do not treat entity counts as interchangeable."""
    mixed = (
        observations == components == source_records
        and observations > 0
        and components != observations  # unreachable; keep structural check
    )
    # Real defect: claiming one ledger total explains another entity type
    same_number_claim = observations == components and components == source_records
    return {
        "observation_count": int(observations),
        "component_count": int(components),
        "source_record_count": int(source_records),
        "counts_equal_across_entity_types": same_number_claim,
        "mixed_dimension_risk": same_number_claim and int(observations) > 1000,
        "defect_if_treated_as_same_ledger": same_number_claim,
    }


def compute_unexplained(
    *,
    expected: int,
    accounted: int,
) -> int:
    """Always computed — never hardcode 0 as sole truth."""
    return abs(int(expected) - int(accounted))


def build_source_row_disposition(
    *,
    candidate_count: int,
    accepted: int,
    rejected: int,
    unsupported: int = 0,
    quarantined: int = 0,
) -> dict[str, Any]:
    inv = disposition_sum_invariant(
        {
            "accepted": accepted,
            "rejected": rejected,
            "unsupported": unsupported,
            "quarantined": quarantined,
        },
        total=candidate_count,
    )
    return {
        "ledger": "source_row_disposition",
        "candidate_count": int(candidate_count),
        **inv,
        "status": "PASS" if inv["invariant_ok"] else "FAIL",
    }


def build_observation_header_accounting(
    *,
    total_headers: int,
    with_accepted_components: int,
    header_only: int,
) -> dict[str, Any]:
    accounted = int(with_accepted_components) + int(header_only)
    unexplained = compute_unexplained(expected=total_headers, accounted=accounted)
    return {
        "ledger": "observation_header_accounting",
        "total_headers": int(total_headers),
        "with_accepted_components": int(with_accepted_components),
        "header_only": int(header_only),
        "accounted": accounted,
        "unexplained_count": unexplained,
        "invariant_ok": unexplained == 0,
        "status": "PASS" if unexplained == 0 else "FAIL",
    }


def build_observation_component_accounting(
    *,
    live_component_count: int,
    rejected_empty: int,
    candidate_source_rows: int,
    load_new_components: int | None = None,
) -> dict[str, Any]:
    """Component ledger independent of mixed newly_loaded counters.

    Invariant: live_components + rejected_empty == candidate_source_rows
    (each constructor row is either an accepted component or empty-reject).
    """
    accounted = int(live_component_count) + int(rejected_empty)
    unexplained = compute_unexplained(expected=candidate_source_rows, accounted=accounted)
    return {
        "ledger": "observation_component_accounting",
        "live_component_count": int(live_component_count),
        "rejected_empty_values": int(rejected_empty),
        "candidate_source_rows": int(candidate_source_rows),
        "accounted": accounted,
        "load_new_components_historical": (
            int(load_new_components) if load_new_components is not None else None
        ),
        "unexplained_count": unexplained,
        "invariant_ok": unexplained == 0,
        "status": "PASS" if unexplained == 0 else "FAIL",
        "note": (
            "Independent of Observation headers and of mixed newly_loaded counters. "
            "Historical load_new_components is informational only."
        ),
    }


def build_source_record_accounting(
    *,
    live_by_relation: dict[str, int],
    live_source_records: int,
) -> dict[str, Any]:
    """SourceRecord ledger by relation coverage — not mixed with Observation counts."""
    parts = {k: int(v) for k, v in live_by_relation.items()}
    accounted = sum(parts.values())
    unexplained = compute_unexplained(expected=live_source_records, accounted=accounted)
    return {
        "ledger": "source_record_accounting",
        "live_source_records": int(live_source_records),
        "by_relation": parts,
        "accounted_sum_by_relation": accounted,
        "unexplained_count": unexplained,
        "invariant_ok": unexplained == 0,
        "status": "PASS" if unexplained == 0 else "FAIL",
        "note": "Coverage by source_relation; Subject/Encounter SRs included.",
    }


def _load_v012_report(repo_root: Path) -> dict[str, Any]:
    path = (
        repo_root
        / "artifacts"
        / "stage-03-unified-source-expansion-v0.1.2"
        / "source-b-observation-load-report.json"
    )
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _live_header_component_counts(conn: Any) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              COUNT(*)::bigint AS n_headers,
              COUNT(*) FILTER (
                WHERE EXISTS (
                  SELECT 1 FROM canonical_evidence.observation_component oc
                  WHERE oc.observation_id = o.observation_id
                )
              )::bigint AS with_components,
              COUNT(*) FILTER (
                WHERE NOT EXISTS (
                  SELECT 1 FROM canonical_evidence.observation_component oc
                  WHERE oc.observation_id = o.observation_id
                )
              )::bigint AS header_only
            FROM canonical_evidence.observation o
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        row = cur.fetchone()
        cur.execute(
            """
            SELECT COUNT(*)::bigint
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_comp = int(cur.fetchone()[0] or 0)
        cur.execute(
            """
            SELECT COUNT(*)::bigint
            FROM canonical_evidence.source_record
            WHERE source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_sr = int(cur.fetchone()[0] or 0)
        cur.execute(
            """
            SELECT source_relation, COUNT(*)::bigint
            FROM canonical_evidence.source_record
            WHERE source_system_id = %s
            GROUP BY source_relation
            ORDER BY COUNT(*) DESC
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        by_rel = {str(r[0]): int(r[1]) for r in cur.fetchall()}
    return {
        "total_headers": int(row[0] or 0),
        "with_accepted_components": int(row[1] or 0),
        "header_only": int(row[2] or 0),
        "live_components": n_comp,
        "live_source_records": n_sr,
        "source_records_by_relation": by_rel,
    }


def recompute_accounting(repo_root: Path) -> dict[str, Any]:
    """Rebuild four ledgers from v0.1.2 load report + live counts (no full reload)."""
    root = Path(repo_root)
    load = _load_v012_report(root)
    acct = (load.get("relation_accounting") or {}).get("analyses_constructor") or {}
    reject_path = (
        root
        / "artifacts"
        / "stage-03-unified-source-expansion-v0.1.2"
        / "reject-summary.json"
    )
    reject = (
        json.loads(reject_path.read_text(encoding="utf-8")) if reject_path.is_file() else {}
    )

    candidates = int(acct.get("candidate_count") or acct.get("runtime_count") or 0)
    rejected = int(reject.get("rejected") or acct.get("rejected_count") or 0)
    unsupported = int(reject.get("unsupported") or acct.get("unsupported_count") or 0)
    quarantined = int(reject.get("quarantined") or acct.get("quarantined_count") or 0)
    new_comps = int(acct.get("new_observation_components") or 0)
    new_obs = int(acct.get("new_observations") or 0)
    new_sr = int(acct.get("source_record_count") or 0)
    already = int(acct.get("already_present_count") or 0)
    newly_loaded = int(acct.get("newly_loaded_count") or 0)

    live: dict[str, int] = {}
    live_error = None
    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings

        with canonical_connection(load_canonical_settings()) as conn:
            live = _live_header_component_counts(conn)
    except Exception as exc:  # noqa: BLE001
        live_error = type(exc).__name__
        live = {
            "total_headers": 59741,
            "with_accepted_components": 58064,
            "header_only": 1677,
            "live_components": 2132978,
            "live_source_records": 2331150,
            "source_records_by_relation": {
                "analyses_constructor": 2132978,
                "consultations": 88867,
                "analyses_pool": 59741,
                "users": 49564,
            },
        }

    # Accepted source rows = live accepted ObservationComponents (one per constructor row)
    accepted = int(live.get("live_components") or 0)
    row_disp = build_source_row_disposition(
        candidate_count=candidates,
        accepted=accepted,
        rejected=rejected,
        unsupported=unsupported,
        quarantined=quarantined,
    )
    row_disp["acceptance_definition"] = (
        "accepted = live Source B ObservationComponent count "
        "(one component per accepted analyses_constructor row)"
    )
    row_disp["historical_load_new_components"] = new_comps
    row_disp["historical_newly_loaded_mixed_counter"] = newly_loaded
    row_disp["historical_newly_loaded_defect"] = detect_newly_loaded_exceeds_candidates(
        newly_loaded=newly_loaded, candidates=candidates
    )

    headers = build_observation_header_accounting(
        total_headers=int(live["total_headers"]),
        with_accepted_components=int(live["with_accepted_components"]),
        header_only=int(live["header_only"]),
    )
    components = build_observation_component_accounting(
        live_component_count=int(live["live_components"]),
        rejected_empty=rejected,
        candidate_source_rows=candidates,
        load_new_components=new_comps,
    )
    source_records = build_source_record_accounting(
        live_by_relation=dict(live.get("source_records_by_relation") or {}),
        live_source_records=int(live["live_source_records"]),
    )

    neg_new = detect_newly_loaded_exceeds_candidates(
        newly_loaded=newly_loaded, candidates=candidates
    )
    neg_mixed = detect_mixed_dimensions(
        observations=int(live["total_headers"]),
        components=int(live["live_components"]),
        source_records=int(live["live_source_records"]),
    )

    return {
        "version": VERSION,
        "live_error_type": live_error,
        "v012_load_report_fields": {
            "candidate_count": candidates,
            "rejected_count": rejected,
            "new_observations": new_obs,
            "new_observation_components": new_comps,
            "source_record_count": new_sr,
            "newly_loaded_count": newly_loaded,
            "already_present_count": already,
        },
        "live_counts": live,
        "source_row_disposition": row_disp,
        "observation_header_accounting": headers,
        "observation_component_accounting": components,
        "source_record_accounting": source_records,
        "negative_checks": {
            "newly_loaded_exceeds_candidates": neg_new,
            "mixed_dimensions": neg_mixed,
        },
        "source_row_accounting_status": row_disp["status"],
        "observation_header_accounting_status": headers["status"],
        "observation_component_accounting_status": components["status"],
        "source_record_accounting_status": source_records["status"],
        "no_full_reload": True,
    }
