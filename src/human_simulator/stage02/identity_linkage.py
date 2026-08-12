"""Aggregate identity linkage assessment using HMAC-SHA256."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

SOURCE_A_TABLE = ("magerya_api", "account_patient")
SOURCE_B_USERS = ("public", "users")

PHONE_FIELD_A = "_phone"
EMAIL_FIELD_A = "email"
PHONE_FIELD_B = "phone"
EMAIL_FIELD_B = "email"

POTENTIAL_OVERLAP_MIN_MATCHES = 1

CONFLICT_DEFINITION: dict[str, Any] = {
    "summary": (
        "Conflicts and ambiguities are counted at aggregate level only; "
        "no subject IDs or HMAC digests are persisted."
    ),
    "cross_field_conflict": (
        "A matched unique phone identifier appears in both sources, both sides attach "
        "at least one email identifier to that phone, and the email identifier sets are disjoint."
    ),
    "within_field_duplicate": (
        "A normalized phone or email identifier maps to more than one subject within the same source."
    ),
    "one_to_many_across_sources": (
        "A matched identifier maps to exactly one subject on one source and to more than one "
        "subject on the other source; such matches are not uniquely resolved subject pairs."
    ),
    "duplicate_identifiers_preclude_unique_pair": (
        "Identifier intersection alone does not imply a patient/subject match when duplicates/collisions exist."
    ),
    "denominators": {
        "cross_field_conflicts": "matched_unique_phone_identifiers with email evidence on both sides",
        "within_field_phone_ambiguity": "matched_unique_phone_identifiers",
        "within_field_email_ambiguity": "matched_unique_email_identifiers",
        "uniquely_resolved_subject_pairs_by_phone": "matched_unique_phone_identifiers",
        "uniquely_resolved_subject_pairs_by_email": "matched_unique_email_identifiers",
        "consistent_subject_pairs_by_phone_and_email": "intersecting (phone, email) signature pairs",
        "observed_unique_phone_identifier_overlap_rate_source_a_available": (
            "matched_unique_phone_identifiers / unique phone identifiers present in Source A"
        ),
        "observed_unique_email_identifier_overlap_rate_source_a_available": (
            "matched_unique_email_identifiers / unique email identifiers present in Source A"
        ),
        "observed_unique_email_identifier_overlap_rate_source_b_available": (
            "matched_unique_email_identifiers / unique email identifiers present in Source B"
        ),
    },
}


def normalize_phone(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value).strip())
    if len(digits) < 10:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) > 11:
        digits = digits[-11:]
    return digits


def normalize_email(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if "@" not in normalized or normalized in {"", "null", "none"}:
        return None
    return normalized


def normalize_name(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value).strip().lower())
    return cleaned or None


def hmac_identifier(key: bytes, kind: str, value: str) -> str:
    return hmac.new(key, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def assess_identity_linkage(
    mg_engine: Engine,
    kgz_engine: Engine,
    *,
    hmac_key: bytes,
    source_b_subject_verdict: str,
    source_b_resolution: dict[str, Any] | None,
) -> dict[str, Any]:
    if source_b_subject_verdict in {"NO_SUBJECT_ROOT", "SUBJECT_ROOT_AMBIGUOUS"}:
        return _not_assessed_payload(source_b_subject_verdict)

    source_b_target = _resolve_source_b_target(source_b_resolution)
    if source_b_target is None:
        return _not_assessed_payload("NO_SUBJECT_ROOT")

    a_stats = _collect_source_a(mg_engine, hmac_key)
    b_stats = _collect_source_b(kgz_engine, hmac_key, source_b_target)
    overlap = _compute_overlap(a_stats, b_stats)
    identity_verdict = _identity_verdict(overlap, a_stats, b_stats)

    return {
        "assessed_at": datetime.now(tz=UTC).isoformat(),
        "method": "HMAC-SHA256 aggregate linkage",
        "hmac_key_present_in_runtime": True,
        "hmac_key_persisted_in_artifacts": False,
        "hmac_key_source": "local_env",
        "source_a_subject_table": f"{SOURCE_A_TABLE[0]}.{SOURCE_A_TABLE[1]}",
        "source_b_subject_resolution": source_b_target,
        "source_a_aggregates": a_stats["summary"],
        "source_b_aggregates": b_stats["summary"],
        "overlap_aggregates": overlap,
        "conflict_definition": CONFLICT_DEFINITION,
        "identity_verdict": identity_verdict,
        "notes": [
            "No per-patient HMAC digests or raw identifiers written to artifacts.",
            "Plain SHA-256 without secret key was not used.",
            "Identifier intersections are not subject/patient matches when duplicates or conflicts exist.",
            "Population overlap is not extrapolated from observed unique-identifier rates.",
            "LINKAGE_PROVEN is not assigned at Stage 02.",
        ],
    }


def _not_assessed_payload(reason: str) -> dict[str, Any]:
    return {
        "assessed_at": datetime.now(tz=UTC).isoformat(),
        "method": "HMAC-SHA256 aggregate linkage",
        "hmac_key_present_in_runtime": True,
        "hmac_key_persisted_in_artifacts": False,
        "hmac_key_source": "local_env",
        "identity_verdict": {
            "verdict": "NOT_ASSESSED",
            "reason": f"Source B subject root status: {reason}",
        },
        "notes": ["Identity linkage skipped because Source B subject root is unresolved."],
    }


def _resolve_source_b_target(resolution: dict[str, Any] | None) -> str | None:
    if not resolution:
        return None
    label = resolution.get("label") or resolution.get("target")
    if not label:
        return None
    if label.startswith("public.users"):
        return "public.users.via_consultations.patient_id"
    return label


def _collect_source_a(engine: Engine, hmac_key: bytes) -> dict[str, Any]:
    schema, relation = SOURCE_A_TABLE
    phone_subjects: dict[str, set[int]] = defaultdict(set)
    email_subjects: dict[str, set[int]] = defaultdict(set)
    signature_subjects: Counter[tuple[str | None, str | None]] = Counter()
    email_by_subject: dict[int, str | None] = {}

    without_phone = 0
    without_email = 0
    without_any_strong = 0
    total = 0

    with engine.connect() as conn:
        for row in conn.execute(
            text(
                f"""
                SELECT id, {PHONE_FIELD_A}, {EMAIL_FIELD_A}
                FROM {schema}.{relation}
                """
            )
        ):
            subject_id = int(row[0])
            total += 1
            phone = normalize_phone(row[1])
            email = normalize_email(row[2])
            phone_hmac = hmac_identifier(hmac_key, "phone", phone) if phone else None
            email_hmac = hmac_identifier(hmac_key, "email", email) if email else None
            email_by_subject[subject_id] = email_hmac
            if phone_hmac:
                phone_subjects[phone_hmac].add(subject_id)
            else:
                without_phone += 1
            if email_hmac:
                email_subjects[email_hmac].add(subject_id)
            else:
                without_email += 1
            if not phone_hmac and not email_hmac:
                without_any_strong += 1
            signature_subjects[(phone_hmac, email_hmac)] += 1

    phone_hmacs = Counter({key: len(subjects) for key, subjects in phone_subjects.items()})
    email_hmacs = Counter({key: len(subjects) for key, subjects in email_subjects.items()})

    return {
        "summary": _identifier_summary(
            total,
            without_phone,
            without_email,
            without_any_strong,
            phone_hmacs,
            email_hmacs,
        ),
        "phone_hmacs": phone_hmacs,
        "email_hmacs": email_hmacs,
        "phone_subjects": phone_subjects,
        "email_subjects": email_subjects,
        "signature_subjects": signature_subjects,
        "phone_to_emails": _phone_email_map_from_subjects(phone_subjects, email_by_subject),
    }


def _collect_source_b(engine: Engine, hmac_key: bytes, target: str) -> dict[str, Any]:
    phone_subjects: dict[str, set[int]] = defaultdict(set)
    email_subjects: dict[str, set[int]] = defaultdict(set)
    signature_subjects: Counter[tuple[str | None, str | None]] = Counter()
    email_by_subject: dict[int, str | None] = {}

    without_phone = 0
    without_email = 0
    without_any_strong = 0
    total = 0

    if target.startswith("public.users"):
        query = """
            SELECT u.id, u.phone, u.email
            FROM public.users u
            WHERE EXISTS (SELECT 1 FROM public.consultations c WHERE c.patient_id = u.id)
        """
    else:
        query = f"SELECT id, {PHONE_FIELD_B}, {EMAIL_FIELD_B} FROM public.users"

    with engine.connect() as conn:
        seen_users: set[int] = set()
        for row in conn.execute(text(query)):
            subject_id = int(row[0])
            if subject_id in seen_users:
                continue
            seen_users.add(subject_id)
            total += 1
            phone = normalize_phone(row[1])
            email = normalize_email(row[2])
            phone_hmac = hmac_identifier(hmac_key, "phone", phone) if phone else None
            email_hmac = hmac_identifier(hmac_key, "email", email) if email else None
            email_by_subject[subject_id] = email_hmac
            if phone_hmac:
                phone_subjects[phone_hmac].add(subject_id)
            else:
                without_phone += 1
            if email_hmac:
                email_subjects[email_hmac].add(subject_id)
            else:
                without_email += 1
            if not phone_hmac and not email_hmac:
                without_any_strong += 1
            signature_subjects[(phone_hmac, email_hmac)] += 1

    phone_hmacs = Counter({key: len(subjects) for key, subjects in phone_subjects.items()})
    email_hmacs = Counter({key: len(subjects) for key, subjects in email_subjects.items()})

    return {
        "summary": _identifier_summary(
            total,
            without_phone,
            without_email,
            without_any_strong,
            phone_hmacs,
            email_hmacs,
        ),
        "phone_hmacs": phone_hmacs,
        "email_hmacs": email_hmacs,
        "phone_subjects": phone_subjects,
        "email_subjects": email_subjects,
        "signature_subjects": signature_subjects,
        "phone_to_emails": _phone_email_map_from_subjects(phone_subjects, email_by_subject),
    }


def _identifier_summary(
    subject_count: int,
    without_phone: int,
    without_email: int,
    without_any_strong: int,
    phone_hmacs: Counter[str],
    email_hmacs: Counter[str],
) -> dict[str, Any]:
    phone_present = subject_count - without_phone
    email_present = subject_count - without_email
    return {
        "subject_count": subject_count,
        "subjects_without_phone": without_phone,
        "subjects_without_email": without_email,
        "subjects_without_any_strong_identifier": without_any_strong,
        "phone_present_count": phone_present,
        "phone_missing_rate": _rate(without_phone, subject_count),
        "email_present_count": email_present,
        "email_missing_rate": _rate(without_email, subject_count),
        "unique_phone_identifiers": len(phone_hmacs),
        "unique_email_identifiers": len(email_hmacs),
        "duplicate_phone_identifier_count": sum(1 for count in phone_hmacs.values() if count > 1),
        "duplicate_email_identifier_count": sum(1 for count in email_hmacs.values() if count > 1),
        "phone_collision_count": sum(count - 1 for count in phone_hmacs.values() if count > 1),
        "email_collision_count": sum(count - 1 for count in email_hmacs.values() if count > 1),
    }


def _phone_email_map_from_subjects(
    phone_subjects: dict[str, set[int]],
    email_by_subject: dict[int, str | None],
) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for phone_hmac, subjects in phone_subjects.items():
        for subject_id in subjects:
            email_hmac = email_by_subject.get(subject_id)
            if email_hmac:
                mapping[phone_hmac].add(email_hmac)
    return mapping


def _compute_overlap(a_stats: dict[str, Any], b_stats: dict[str, Any]) -> dict[str, Any]:
    phone_a = set(a_stats["phone_hmacs"])
    phone_b = set(b_stats["phone_hmacs"])
    email_a = set(a_stats["email_hmacs"])
    email_b = set(b_stats["email_hmacs"])

    matched_unique_phone = phone_a & phone_b
    matched_unique_email = email_a & email_b

    cross_field_conflicts = 0
    for phone_hmac in matched_unique_phone:
        emails_a = a_stats["phone_to_emails"].get(phone_hmac, set())
        emails_b = b_stats["phone_to_emails"].get(phone_hmac, set())
        if emails_a and emails_b and emails_a.isdisjoint(emails_b):
            cross_field_conflicts += 1

    uniquely_resolved_phone = 0
    uniquely_resolved_email = 0
    ambiguous_subject_pairs = 0
    one_to_many_across_sources = 0

    for phone_hmac in matched_unique_phone:
        a_count = len(a_stats["phone_subjects"][phone_hmac])
        b_count = len(b_stats["phone_subjects"][phone_hmac])
        if a_count == 1 and b_count == 1:
            uniquely_resolved_phone += 1
        else:
            ambiguous_subject_pairs += 1
            if (a_count == 1) ^ (b_count == 1):
                one_to_many_across_sources += 1

    for email_hmac in matched_unique_email:
        a_count = len(a_stats["email_subjects"][email_hmac])
        b_count = len(b_stats["email_subjects"][email_hmac])
        if a_count == 1 and b_count == 1:
            uniquely_resolved_email += 1
        else:
            ambiguous_subject_pairs += 1
            if (a_count == 1) ^ (b_count == 1):
                one_to_many_across_sources += 1

    consistent_pairs = 0
    signatures_a = {
        sig: count
        for sig, count in a_stats["signature_subjects"].items()
        if sig[0] is not None and sig[1] is not None
    }
    signatures_b = {
        sig: count
        for sig, count in b_stats["signature_subjects"].items()
        if sig[0] is not None and sig[1] is not None
    }
    for signature in signatures_a.keys() & signatures_b.keys():
        if signatures_a[signature] == 1 and signatures_b[signature] == 1:
            consistent_pairs += 1

    phone_rate_a = _rate(len(matched_unique_phone), len(phone_a))
    phone_rate_b = _rate(len(matched_unique_phone), len(phone_b))
    email_rate_a = _rate(len(matched_unique_email), len(email_a))
    email_rate_b = _rate(len(matched_unique_email), len(email_b))

    population_overlap = _population_overlap_estimate(
        a_stats["summary"],
        consistent_pairs=consistent_pairs,
    )

    return {
        "matched_unique_phone_identifiers": len(matched_unique_phone),
        "matched_unique_email_identifiers": len(matched_unique_email),
        "uniquely_resolved_subject_pairs_by_phone": uniquely_resolved_phone,
        "uniquely_resolved_subject_pairs_by_email": uniquely_resolved_email,
        "consistent_subject_pairs_by_phone_and_email": consistent_pairs,
        "ambiguous_subject_pairs": ambiguous_subject_pairs,
        "cross_field_conflicts": cross_field_conflicts,
        "one_to_many_across_sources": one_to_many_across_sources,
        "observed_unique_phone_identifier_overlap_rate_source_a_available": phone_rate_a,
        "observed_unique_phone_identifier_overlap_rate_source_b_available": phone_rate_b,
        "observed_unique_email_identifier_overlap_rate_source_a_available": email_rate_a,
        "observed_unique_email_identifier_overlap_rate_source_b_available": email_rate_b,
        "population_overlap_estimate": population_overlap,
        "source_a_subjects_without_phone": a_stats["summary"].get("subjects_without_phone", 0),
        "source_a_subjects_without_email": a_stats["summary"].get("subjects_without_email", 0),
        "source_a_subjects_without_any_strong_identifier": a_stats["summary"].get(
            "subjects_without_any_strong_identifier", 0
        ),
        "source_b_subjects_without_phone": b_stats["summary"].get("subjects_without_phone", 0),
        "source_b_subjects_without_email": b_stats["summary"].get("subjects_without_email", 0),
        "source_b_subjects_without_any_strong_identifier": b_stats["summary"].get(
            "subjects_without_any_strong_identifier", 0
        ),
    }


def _population_overlap_estimate(summary_a: dict[str, Any], *, consistent_pairs: int) -> dict[str, str]:
    phone_coverage = _rate(summary_a["phone_present_count"], summary_a["subject_count"])
    if phone_coverage < 0.05:
        reason = (
            f"Source A phone coverage is {phone_coverage * 100:.1f}%; "
            "missingness cannot be assumed random"
        )
        if consistent_pairs == 0:
            reason += "; no consistent dual-identifier matches"
        else:
            reason += (
                f"; only {consistent_pairs} consistent dual-identifier subject pairs — "
                "insufficient for population extrapolation"
            )
        return {"status": "NOT_ESTIMABLE", "reason": reason}
    return {
        "status": "NOT_ESTIMABLE",
        "reason": (
            "Observed identifier intersections are insufficient for population extrapolation; "
            "missingness is asymmetric across sources and dual-identifier agreement is limited"
        ),
    }


def _identity_verdict(
    overlap: dict[str, Any],
    a_stats: dict[str, Any],
    b_stats: dict[str, Any],
) -> dict[str, Any]:
    if not a_stats["phone_hmacs"] and not a_stats["email_hmacs"]:
        return {"verdict": "NO_COMMON_IDENTIFIERS", "reason": "Source A lacks usable phone/email identifiers"}
    if not b_stats["phone_hmacs"] and not b_stats["email_hmacs"]:
        return {"verdict": "NO_COMMON_IDENTIFIERS", "reason": "Source B lacks usable phone/email identifiers"}

    phone_matches = overlap["matched_unique_phone_identifiers"]
    email_matches = overlap["matched_unique_email_identifiers"]
    if phone_matches == 0 and email_matches == 0:
        return {
            "verdict": "STRUCTURAL_ONLY",
            "reason": "Shared identifier columns exist but aggregate HMAC identifier overlap is zero",
        }

    has_conflicts_or_ambiguity = (
        overlap["cross_field_conflicts"] > 0
        or overlap["ambiguous_subject_pairs"] > 0
        or overlap["consistent_subject_pairs_by_phone_and_email"] == 0
    )
    lacks_unique_pairs = (
        overlap["uniquely_resolved_subject_pairs_by_phone"] == 0
        and overlap["uniquely_resolved_subject_pairs_by_email"] == 0
    )

    if phone_matches >= POTENTIAL_OVERLAP_MIN_MATCHES or email_matches >= POTENTIAL_OVERLAP_MIN_MATCHES:
        if has_conflicts_or_ambiguity or lacks_unique_pairs:
            return {
                "verdict": "POTENTIAL_OVERLAP",
                "reason": (
                    f"Identifier intersections exist ({phone_matches} phone, {email_matches} email) "
                    "but uniquely resolved subject pairs are unavailable; "
                    f"cross-field conflicts={overlap['cross_field_conflicts']}, "
                    f"consistent dual-identifier pairs={overlap['consistent_subject_pairs_by_phone_and_email']}"
                ),
            }

    return {"verdict": "STRUCTURAL_ONLY", "reason": "Insufficient overlap for population linkage hypothesis"}


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def render_identity_linkage_markdown(payload: dict[str, Any]) -> str:
    verdict = payload.get("identity_verdict", {})
    lines = [
        "# Identity linkage assessment",
        "",
        f"Assessed at: {payload.get('assessed_at', 'unknown')}",
        f"Method: {payload.get('method', 'unknown')}",
        "",
        f"## Verdict: **{verdict.get('verdict', 'UNKNOWN')}**",
        "",
        verdict.get("reason", ""),
        "",
    ]
    overlap = payload.get("overlap_aggregates")
    if overlap:
        pop = overlap.get("population_overlap_estimate", {})
        lines.extend(
            [
                "## Overlap aggregates",
                "",
                f"- Matched unique phone identifiers: {overlap['matched_unique_phone_identifiers']:,}",
                f"- Matched unique email identifiers: {overlap['matched_unique_email_identifiers']:,}",
                f"- Uniquely resolved subject pairs (phone): {overlap['uniquely_resolved_subject_pairs_by_phone']:,}",
                f"- Uniquely resolved subject pairs (email): {overlap['uniquely_resolved_subject_pairs_by_email']:,}",
                f"- Consistent subject pairs (phone+email): {overlap['consistent_subject_pairs_by_phone_and_email']:,}",
                f"- Cross-field conflicts: {overlap['cross_field_conflicts']:,}",
                f"- Population overlap estimate: **{pop.get('status', 'UNKNOWN')}** — {pop.get('reason', '')}",
                "",
                "Observed unique-identifier overlap rates use unique identifiers as denominators; "
                "they are not extrapolated to full patient populations.",
                "",
            ]
        )
    for note in payload.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
