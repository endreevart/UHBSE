"""Honest Source A coverage check (not a full loader upsert replay)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.policy import SOURCE_A, VERSION
from human_simulator.population_v011.lifecycle import canonical_counts


def full_source_a_expected_id_coverage_check(
    root: Path, conn_canonical: Any
) -> dict[str, Any]:
    """Read-only expected-ID coverage — NOT a loader upsert replay.

    Method name is intentional: do not call this SOURCE_A_IDEMPOTENCY PASS
    via a false 'replay' claim.
    """
    from human_simulator.core.ids import load_hmac_key, opaque_subject_key
    from human_simulator.unified import source_a_adapter as sa

    root = Path(root).resolve()
    before = canonical_counts(conn_canonical)
    key = load_hmac_key(root)

    with sa.source_a_connection(root) as conn_a:
        ids = sa.select_all_account_patient_ids(conn_a)

    missing = 0
    present = 0
    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT source_subject_key FROM canonical_evidence.subject
            WHERE source_system_id = %s
            """,
            (SOURCE_A,),
        )
        existing = {str(r[0]) for r in cur.fetchall()}
        for pid in ids:
            if opaque_subject_key(key, pid) in existing:
                present += 1
            else:
                missing += 1

    after = canonical_counts(conn_canonical)
    counts_unchanged = (
        before.get("subject") == after.get("subject")
        and before.get("encounter") == after.get("encounter")
        and before.get("observation") == after.get("observation")
        and before.get("observation_component") == after.get("observation_component")
        and before.get("schema_fingerprint") == after.get("schema_fingerprint")
    )
    source_a_subjects = int(
        (before.get("subject_by_system") or {}).get(SOURCE_A)
        or before.get("magerya_api_subject")
        or -1
    )
    coverage_ok = missing == 0 and present == len(ids) and present == source_a_subjects

    status = (
        "PASS"
        if coverage_ok and counts_unchanged
        else ("PARTIAL" if missing == 0 else "FAIL")
    )
    return {
        "version": VERSION,
        "SOURCE_A_IDEMPOTENCY_STATUS": "NOT_CLAIMED_AS_LOADER_REPLAY",
        "idempotency_method": "FULL_SOURCE_A_EXPECTED_ID_COVERAGE_CHECK",
        "FULL_SOURCE_A_EXPECTED_ID_COVERAGE_CHECK_STATUS": status,
        "method_description": (
            "Resolves opaque subject keys for all account_patient rows and verifies "
            "presence in canonical_evidence.subject. Does not re-execute the full "
            "Source A upsert path. Counts are compared before/after the read-only check."
        ),
        "source_a_account_patient_count": len(ids),
        "canonical_subjects_present": present,
        "canonical_subjects_missing": missing,
        "counts_before": before,
        "counts_after": after,
        "counts_unchanged": counts_unchanged,
        "zero_new_entities_claimed": False,
        "note": (
            "Preferred full upsert replay was not executed in this changeset; "
            "coverage check is the honest fallback."
        ),
    }
