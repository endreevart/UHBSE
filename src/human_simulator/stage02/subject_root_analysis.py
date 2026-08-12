"""Subject-root analysis for Source A and Source B."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from human_simulator.stage02.relation_scope import PROFILE_EXTENSION_LABELS

SUBJECT_ROOT_CONFIRMED_COVERAGE = 0.95

SOURCE_A_HYPOTHESIS = ("magerya_api", "account_patient")
SOURCE_B_PERSON_HYPOTHESIS = ("public", "persons")
CONSULTATIONS = ("public", "consultations")

PATIENT_ID_CANDIDATES: tuple[dict[str, str], ...] = (
    {"schema": "public", "table": "users", "column": "id", "label": "public.users.id"},
    {"schema": "public", "table": "persons", "column": "id", "label": "public.persons.id"},
    {"schema": "public", "table": "profilaxys_profile", "column": "id", "label": "public.profilaxys_profile.id"},
    {
        "schema": "public",
        "table": "profilaxys_profile",
        "column": "user_id",
        "label": "public.profilaxys_profile.user_id",
    },
    {"schema": "public", "table": "users_profile", "column": "user_id", "label": "public.users_profile.user_id"},
    {"schema": "public", "table": "profilaxys_users", "column": "id", "label": "public.profilaxys_users.id"},
)


@dataclass(frozen=True)
class SubjectRootVerdict:
    verdict: str
    reason: str


def analyze_subject_roots(
    mg_engine: Engine,
    kgz_engine: Engine,
    *,
    profile_a_path: Path,
    profile_b_path: Path,
) -> dict[str, Any]:
    profile_a = json.loads(profile_a_path.read_text(encoding="utf-8"))
    profile_b = json.loads(profile_b_path.read_text(encoding="utf-8"))

    source_a = _analyze_source_a(mg_engine, profile_a)
    source_b = _analyze_source_b(kgz_engine, profile_b)

    return {
        "assessed_at": datetime.now(tz=UTC).isoformat(),
        "coverage_threshold_confirmed": SUBJECT_ROOT_CONFIRMED_COVERAGE,
        "source_a": source_a,
        "source_b": source_b,
        "notes": [
            "Aggregates only; no patient IDs or PII emitted.",
            "CONFIRMED requires explicit FK or coverage >= threshold.",
        ],
    }


def _analyze_source_a(engine: Engine, profile: dict[str, Any]) -> dict[str, Any]:
    schema, relation = SOURCE_A_HYPOTHESIS
    incoming_fks = _count_incoming_fks(profile, schema, relation)
    outgoing_fks = _outgoing_fks(profile, schema, relation)
    explicit_patient_fks = incoming_fks > 0

    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT
                  COUNT(*) AS row_count,
                  COUNT(DISTINCT id) AS distinct_ids,
                  COUNT(*) FILTER (WHERE id IS NULL) AS null_ids,
                  COUNT(*) - COUNT(DISTINCT id) AS duplicate_id_rows,
                  COUNT(*) FILTER (WHERE user_id IS NULL) AS null_user_id,
                  COUNT(DISTINCT user_id) AS distinct_user_ids
                FROM {schema}.{relation}
                """
            )
        ).one()

    row_count = int(row[0])
    distinct_ids = int(row[1])
    duplicate_id_rows = int(row[3])
    id_collision_count = max(0, duplicate_id_rows)

    aggregates = {
        "row_count": row_count,
        "distinct_id_count": distinct_ids,
        "null_id_count": int(row[2]),
        "null_id_rate": _rate(int(row[2]), row_count),
        "duplicate_id_rows": duplicate_id_rows,
        "id_collision_count": id_collision_count,
        "null_user_id_count": int(row[4]),
        "null_user_id_rate": _rate(int(row[4]), row_count),
        "distinct_user_id_count": int(row[5]),
        "incoming_foreign_key_count": incoming_fks,
        "outgoing_foreign_keys": outgoing_fks,
    }

    verdict = _verdict_source_a(
        row_count=row_count,
        distinct_ids=distinct_ids,
        id_collision_count=id_collision_count,
        explicit_patient_fks=explicit_patient_fks,
        has_pk=_has_pk(profile, schema, relation),
    )

    return {
        "hypothesis": {"schema": schema, "relation": relation},
        "verdict": verdict.verdict,
        "verdict_reason": verdict.reason,
        "aggregates": aggregates,
    }


def _analyze_source_b(engine: Engine, profile: dict[str, Any]) -> dict[str, Any]:
    person_schema, person_relation = SOURCE_B_PERSON_HYPOTHESIS
    consult_schema, consult_relation = CONSULTATIONS

    with engine.connect() as conn:
        persons_row = conn.execute(
            text(
                f"""
                SELECT COUNT(*) AS row_count, COUNT(DISTINCT id) AS distinct_ids
                FROM {person_schema}.{person_relation}
                """
            )
        ).one()
        consult_row = conn.execute(
            text(
                f"""
                SELECT
                  COUNT(*) AS row_count,
                  COUNT(DISTINCT patient_id) AS distinct_patient_ids,
                  COUNT(*) FILTER (WHERE patient_id IS NULL) AS null_patient_ids
                FROM {consult_schema}.{consult_relation}
                """
            )
        ).one()

        candidate_coverage = _patient_id_candidate_coverage(conn, consult_schema, consult_relation)

    persons_row_count = int(persons_row[0])
    persons_verdict = (
        SubjectRootVerdict("NO_SUBJECT_ROOT", "candidate table is empty (0 rows)")
        if persons_row_count == 0
        else _verdict_from_coverage(
            coverage_rate=1.0,
            explicit_fk=_has_explicit_fk_to(profile, consult_schema, consult_relation, "patient_id", person_schema, person_relation),
            multi_role_note=False,
        )
    )

    consult_total = int(consult_row[0])
    consult_aggregates = {
        "row_count": consult_total,
        "distinct_patient_id_count": int(consult_row[1]),
        "null_patient_id_count": int(consult_row[2]),
        "null_patient_id_rate": _rate(int(consult_row[2]), consult_total),
    }

    match_candidates = [
        item
        for item in candidate_coverage
        if "match_rate" in item and item.get("candidate_role") != "profile_extension"
    ]
    ranked = sorted(match_candidates, key=lambda item: item["match_rate"], reverse=True)
    best = ranked[0] if ranked else None
    second_best_rate = ranked[1]["match_rate"] if len(ranked) > 1 else 0.0

    resolved = None
    overall_verdict = SubjectRootVerdict("NO_SUBJECT_ROOT", "no patient_id resolution candidate")
    if best and consult_total > 0:
        resolved = {
            "anchor": f"{consult_schema}.{consult_relation}.patient_id",
            "target": best["label"],
            "aggregates": best,
        }
        overall_verdict = _verdict_patient_id_resolution(
            best=best,
            second_best_rate=second_best_rate,
            profile=profile,
            consult_schema=consult_schema,
            consult_relation=consult_relation,
        )
        resolved["verdict"] = overall_verdict.verdict
        resolved["verdict_reason"] = overall_verdict.reason

    return {
        "persons_hypothesis": {"schema": person_schema, "relation": person_relation},
        "persons_hypothesis_verdict": persons_verdict.verdict,
        "persons_hypothesis_reason": persons_verdict.reason,
        "persons_aggregates": {
            "row_count": persons_row_count,
            "distinct_id_count": int(persons_row[1]),
        },
        "consultations_anchor": {"schema": consult_schema, "relation": consult_relation},
        "consultations_aggregates": consult_aggregates,
        "patient_id_candidate_coverage": candidate_coverage,
        "patient_id_resolution": resolved,
        "overall_verdict": overall_verdict.verdict,
        "overall_verdict_reason": overall_verdict.reason,
    }


def _patient_id_candidate_coverage(
    conn: Any,
    consult_schema: str,
    consult_relation: str,
) -> list[dict[str, Any]]:
    totals = conn.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE patient_id IS NULL) AS null_patient_id,
              COUNT(DISTINCT patient_id) AS distinct_patient_ids
            FROM {consult_schema}.{consult_relation}
            """
        )
    ).one()
    total = int(totals[0])
    non_null = total - int(totals[1])
    distinct_patient_ids = int(totals[2])

    results: list[dict[str, Any]] = []
    for candidate in PATIENT_ID_CANDIDATES:
        match_count = conn.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM {consult_schema}.{consult_relation} AS c
                WHERE c.patient_id IS NOT NULL
                  AND EXISTS (
                    SELECT 1
                    FROM {candidate['schema']}.{candidate['table']} AS target
                    WHERE target.{candidate['column']} = c.patient_id
                  )
                """
            )
        ).scalar_one()
        match_count = int(match_count)
        orphan_count = max(0, non_null - match_count)
        entry: dict[str, Any] = {
            "label": candidate["label"],
            "match_count": match_count,
            "match_rate": _rate(match_count, non_null),
            "orphan_count": orphan_count,
            "orphan_rate": _rate(orphan_count, non_null),
        }
        if candidate["label"] in PROFILE_EXTENSION_LABELS:
            entry["candidate_role"] = "profile_extension"
            entry["note"] = "Profile extension table; not an independent subject root"
        results.append(entry)
    results.append(
        {
            "label": "distinct_patient_ids",
            "distinct_patient_id_count": distinct_patient_ids,
        }
    )
    return results


def _verdict_source_a(
    *,
    row_count: int,
    distinct_ids: int,
    id_collision_count: int,
    explicit_patient_fks: bool,
    has_pk: bool,
) -> SubjectRootVerdict:
    if row_count == 0:
        return SubjectRootVerdict("NO_SUBJECT_ROOT", "hypothesis table is empty")
    if id_collision_count > 0 or not has_pk:
        return SubjectRootVerdict("SUBJECT_ROOT_AMBIGUOUS", "primary identifier collisions detected")
    if explicit_patient_fks and distinct_ids == row_count:
        return SubjectRootVerdict(
            "SUBJECT_ROOT_CONFIRMED",
            "dedicated patient table with PK and multiple incoming foreign keys",
        )
    if distinct_ids == row_count:
        return SubjectRootVerdict("SUBJECT_ROOT_CANDIDATE", "patient table present without sufficient FK evidence")
    return SubjectRootVerdict("SUBJECT_ROOT_AMBIGUOUS", "row count differs from distinct id count")


def _verdict_patient_id_resolution(
    *,
    best: dict[str, Any],
    second_best_rate: float,
    profile: dict[str, Any],
    consult_schema: str,
    consult_relation: str,
) -> SubjectRootVerdict:
    label = best["label"]
    coverage = best["match_rate"]
    parts = label.split(".")
    target_schema, target_table, target_column = parts[0], parts[1], parts[2]
    explicit_fk = _has_explicit_fk_to(
        profile, consult_schema, consult_relation, "patient_id", target_schema, target_table
    )

    if coverage >= SUBJECT_ROOT_CONFIRMED_COVERAGE and abs(coverage - second_best_rate) >= 0.05:
        if explicit_fk:
            return SubjectRootVerdict(
                "SUBJECT_ROOT_CONFIRMED",
                f"explicit FK or full coverage ({coverage:.4f}) for {label}",
            )
        if target_table == "users":
            return SubjectRootVerdict(
                "SUBJECT_ROOT_CANDIDATE",
                (
                    "100% consultations.patient_id coverage in public.users.id, but only CANDIDATE "
                    "because public.users is multi-role and there is no explicit patient-only FK/root"
                ),
            )
        return SubjectRootVerdict(
            "SUBJECT_ROOT_CONFIRMED",
            f"coverage {coverage:.4f} >= threshold {SUBJECT_ROOT_CONFIRMED_COVERAGE}",
        )

    if coverage >= 0.5:
        return SubjectRootVerdict("SUBJECT_ROOT_CANDIDATE", f"partial coverage {coverage:.4f} for {label}")

    if second_best_rate >= coverage - 0.01:
        return SubjectRootVerdict("SUBJECT_ROOT_AMBIGUOUS", "multiple candidates with similar coverage")

    return SubjectRootVerdict("NO_SUBJECT_ROOT", "insufficient patient_id resolution coverage")


def _verdict_from_coverage(*, coverage_rate: float, explicit_fk: bool, multi_role_note: bool) -> SubjectRootVerdict:
    if coverage_rate >= SUBJECT_ROOT_CONFIRMED_COVERAGE and explicit_fk:
        return SubjectRootVerdict("SUBJECT_ROOT_CONFIRMED", "explicit FK with full coverage")
    if coverage_rate >= SUBJECT_ROOT_CONFIRMED_COVERAGE and not multi_role_note:
        return SubjectRootVerdict("SUBJECT_ROOT_CONFIRMED", f"coverage {coverage_rate:.4f} >= threshold")
    if coverage_rate >= SUBJECT_ROOT_CONFIRMED_COVERAGE:
        return SubjectRootVerdict("SUBJECT_ROOT_CANDIDATE", "full coverage but entity is multi-role")
    if coverage_rate > 0:
        return SubjectRootVerdict("SUBJECT_ROOT_CANDIDATE", f"partial coverage {coverage_rate:.4f}")
    return SubjectRootVerdict("NO_SUBJECT_ROOT", "no coverage")


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _count_incoming_fks(profile: dict[str, Any], schema: str, relation: str) -> int:
    return sum(
        1
        for fk in profile.get("foreign_keys", [])
        if fk.get("foreign_schema") == schema and fk.get("foreign_table") == relation
    )


def _outgoing_fks(profile: dict[str, Any], schema: str, relation: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for fk in profile.get("foreign_keys", []):
        if fk.get("schema_name") == schema and fk.get("relation_name") == relation:
            results.append(
                {
                    "column": fk.get("column_name", ""),
                    "foreign_schema": fk.get("foreign_schema", ""),
                    "foreign_table": fk.get("foreign_table", ""),
                    "foreign_column": fk.get("foreign_column", ""),
                }
            )
    return results


def _has_pk(profile: dict[str, Any], schema: str, relation: str) -> bool:
    for pk in profile.get("primary_keys", []):
        if pk.get("schema_name") == schema and pk.get("relation_name") == relation:
            return True
    return False


def _has_explicit_fk_to(
    profile: dict[str, Any],
    schema: str,
    relation: str,
    column: str,
    foreign_schema: str,
    foreign_table: str,
) -> bool:
    for fk in profile.get("foreign_keys", []):
        if (
            fk.get("schema_name") == schema
            and fk.get("relation_name") == relation
            and fk.get("column_name") == column
            and fk.get("foreign_schema") == foreign_schema
            and fk.get("foreign_table") == foreign_table
        ):
            return True
    return False


def render_subject_root_markdown(payload: dict[str, Any]) -> str:
    a = payload["source_a"]
    b = payload["source_b"]
    lines = [
        "# Subject root analysis",
        "",
        f"Assessed at: {payload['assessed_at']}",
        "",
        "## Source A",
        "",
        f"- Hypothesis: `{a['hypothesis']['schema']}.{a['hypothesis']['relation']}`",
        f"- Verdict: **{a['verdict']}**",
        f"- Reason: {a['verdict_reason']}",
        f"- Rows: {a['aggregates']['row_count']:,}",
        f"- Distinct IDs: {a['aggregates']['distinct_id_count']:,}",
        f"- Incoming FK count: {a['aggregates']['incoming_foreign_key_count']}",
        "",
        "## Source B",
        "",
        f"- Persons hypothesis: `{b['persons_hypothesis']['schema']}.{b['persons_hypothesis']['relation']}` → **{b['persons_hypothesis_verdict']}**",
        f"- Consultations anchor rows: {b['consultations_aggregates']['row_count']:,}",
        f"- Distinct patient_id values: {b['consultations_aggregates']['distinct_patient_id_count']:,}",
        f"- Overall verdict: **{b['overall_verdict']}**",
        f"- Reason: {b['overall_verdict_reason']}",
        "",
        "### patient_id candidate coverage",
        "",
        "| Target | Match rate | Orphan count |",
        "|--------|------------|--------------|",
    ]
    for item in b["patient_id_candidate_coverage"]:
        if "match_rate" not in item:
            continue
        lines.append(
            f"| {item['label']} | {item['match_rate']:.4f} | {item['orphan_count']:,} |"
        )
    lines.extend(["", "## Notes", ""])
    for note in payload.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
