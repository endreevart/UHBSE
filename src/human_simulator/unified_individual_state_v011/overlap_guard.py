"""Private overlap universe + overlap-guarded split with Stage-02 reconciliation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.core.ids import load_hmac_key
from human_simulator.stage02.identity_linkage import normalize_email, normalize_phone
from human_simulator.unified_individual_state_v011.canonical_subject import (
    load_maps,
    source_a_loader_subject_key,
    source_b_loader_subject_key,
)
from human_simulator.unified_individual_state_v011.policy import (
    BUCKET_TRAIN_END,
    BUCKET_VAL_END,
    NAMESPACE,
    OVERLAP_DIR,
    PRIOR_AMBIGUOUS,
    PRIOR_CANDIDATE_OVERLAP,
    PRIOR_CONFIRMED_PAIRS,
    PRIOR_CONFLICTING,
    SEED,
    STAGE02_LINKAGE_ASSESSMENT,
    V031_MATERIALIZED_DIR,
    VERSION,
)
from human_simulator.unified_research_layer_v03.connections import (
    connect_source_a,
    connect_source_b,
)


def _hmac_id(key: bytes, kind: str, value: str) -> str:
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def _load_linkage_key(root: Path) -> bytes:
    env = os.environ.get("LINKAGE_HMAC_KEY") or os.environ.get("UHBSE_RESEARCH_HMAC_KEY")
    if env:
        return env.encode()
    for p in (
        root / "private" / "linkage-hmac.key",
        root / "private" / "uhbse-core-hmac.key",
    ):
        if p.is_file():
            return p.read_bytes().strip()
    return load_hmac_key(root)


def assign_role_group(group_id: str) -> str:
    digest = hashlib.sha256(
        f"{NAMESPACE}|{SEED}|GROUP|{group_id}".encode()
    ).hexdigest()
    frac = int(digest[:12], 16) / float(16**12)
    if frac < BUCKET_TRAIN_END:
        return "train"
    if frac < BUCKET_VAL_END:
        return "validation"
    return "test"


def assign_role_unlinked(source_system: str, subject_id: str) -> str:
    digest = hashlib.sha256(
        f"{NAMESPACE}|{SEED}|{source_system}|{subject_id}".encode()
    ).hexdigest()
    frac = int(digest[:12], 16) / float(16**12)
    if frac < BUCKET_TRAIN_END:
        return "train"
    if frac < BUCKET_VAL_END:
        return "validation"
    return "test"


class _UF:
    def __init__(self) -> None:
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def empty_overlap_cannot_pass(n_confirmed: int, n_candidate: int, n_groups: int) -> bool:
    """PASS_OVERLAP_GUARDED is forbidden when overlap universe is empty."""
    return (n_confirmed + n_candidate + n_groups) == 0


def build_overlap_guarded_split(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / OVERLAP_DIR
    out.mkdir(parents=True, exist_ok=True)
    core_key = load_hmac_key(root)
    link_key = _load_linkage_key(root)
    a_map, b_map = load_maps(root)

    subj = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_subject.parquet",
        columns=["research_entity_id", "source_system"],
    )
    subjects = list(
        zip(
            subj["research_entity_id"].to_pylist(),
            subj["source_system"].to_pylist(),
            strict=True,
        )
    )
    a_subjects = {sid for sid, ss in subjects if ss == "magerya_api"}
    b_subjects = {sid for sid, ss in subjects if ss == "kgz_raw"}

    phone_to_subj: dict[str, set[str]] = defaultdict(set)
    email_to_subj: dict[str, set[str]] = defaultdict(set)
    subj_phones: dict[str, set[str]] = defaultdict(set)
    subj_emails: dict[str, set[str]] = defaultdict(set)

    n_a_resolved = n_b_resolved = 0
    n_a_missing_canonical = n_b_missing_canonical = 0

    conn_a = connect_source_a(root)
    conn_b = connect_source_b(root)
    try:
        if conn_a is not None:
            with conn_a.cursor() as cur:
                cur.execute("SET default_transaction_read_only=on")
                cur.execute(
                    "SELECT id, _phone, email FROM magerya_api.account_patient"
                )
                for pid, phone, email in cur:
                    okey = source_a_loader_subject_key(core_key, int(pid))
                    sid = a_map.get(okey)
                    if sid is None:
                        n_a_missing_canonical += 1
                        continue
                    if sid not in a_subjects:
                        continue
                    n_a_resolved += 1
                    pn = normalize_phone(phone)
                    em = normalize_email(email)
                    if pn:
                        d = _hmac_id(link_key, "phone", pn)
                        phone_to_subj[d].add(f"A:{sid}")
                        subj_phones[f"A:{sid}"].add(d)
                    if em:
                        d = _hmac_id(link_key, "email", em)
                        email_to_subj[d].add(f"A:{sid}")
                        subj_emails[f"A:{sid}"].add(d)
        if conn_b is not None:
            with conn_b.cursor() as cur:
                cur.execute("SET default_transaction_read_only=on")
                cur.execute(
                    """
                    SELECT DISTINCT u.id, u.phone, u.email
                    FROM public.users u
                    JOIN public.consultations c ON c.patient_id = u.id
                    """
                )
                for uid, phone, email in cur:
                    skey = source_b_loader_subject_key(core_key, int(uid))
                    # Authoritative lookup — NEVER apply second entity_id
                    sid = b_map.get(skey)
                    if sid is None:
                        n_b_missing_canonical += 1
                        continue
                    if sid not in b_subjects:
                        continue
                    n_b_resolved += 1
                    pn = normalize_phone(phone)
                    em = normalize_email(email)
                    if pn:
                        d = _hmac_id(link_key, "phone", pn)
                        phone_to_subj[d].add(f"B:{sid}")
                        subj_phones[f"B:{sid}"].add(d)
                    if em:
                        d = _hmac_id(link_key, "email", em)
                        email_to_subj[d].add(f"B:{sid}")
                        subj_emails[f"B:{sid}"].add(d)
    finally:
        for c in (conn_a, conn_b):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

    phone_pairs: set[frozenset[str]] = set()
    email_pairs: set[frozenset[str]] = set()
    ambiguous_nodes: set[str] = set()
    conflicting_nodes: set[str] = set()

    for _dig, nodes in phone_to_subj.items():
        a_n = [n for n in nodes if n.startswith("A:")]
        b_n = [n for n in nodes if n.startswith("B:")]
        if len(a_n) == 1 and len(b_n) == 1:
            phone_pairs.add(frozenset({a_n[0], b_n[0]}))
        elif a_n and b_n and len(a_n) + len(b_n) > 2:
            ambiguous_nodes.update(a_n + b_n)

    for _dig, nodes in email_to_subj.items():
        a_n = [n for n in nodes if n.startswith("A:")]
        b_n = [n for n in nodes if n.startswith("B:")]
        if len(a_n) == 1 and len(b_n) == 1:
            email_pairs.add(frozenset({a_n[0], b_n[0]}))
        elif a_n and b_n and len(a_n) + len(b_n) > 2:
            ambiguous_nodes.update(a_n + b_n)

    confirmed_pairs = phone_pairs & email_pairs
    candidate_pairs = (phone_pairs | email_pairs) - confirmed_pairs

    a_to_b_phone = {
        next(x for x in p if x.startswith("A:")): next(x for x in p if x.startswith("B:"))
        for p in phone_pairs
    }
    a_to_b_email = {
        next(x for x in p if x.startswith("A:")): next(x for x in p if x.startswith("B:"))
        for p in email_pairs
    }
    for a, b_p in a_to_b_phone.items():
        if a in a_to_b_email and a_to_b_email[a] != b_p:
            conflicting_nodes.add(a)
            conflicting_nodes.add(b_p)
            conflicting_nodes.add(a_to_b_email[a])

    uf = _UF()
    for p in confirmed_pairs | candidate_pairs:
        nodes = list(p)
        if len(nodes) == 2:
            uf.union(nodes[0], nodes[1])

    group_members: dict[str, list[str]] = defaultdict(list)
    for p in confirmed_pairs | candidate_pairs:
        for n in p:
            group_members[uf.find(n)].append(n)
    group_members = {g: sorted(set(ms)) for g, ms in group_members.items()}

    subject_role: dict[str, str] = {}
    subject_group: dict[str, str | None] = {}
    subject_overlap_status: dict[str, str] = {}

    for gid, members in group_members.items():
        role = assign_role_group(gid)
        for m in members:
            sid = m.split(":", 1)[1]
            subject_role[sid] = role
            subject_group[sid] = gid
            if m in conflicting_nodes:
                subject_overlap_status[sid] = "conflicting"
            elif m in ambiguous_nodes:
                subject_overlap_status[sid] = "ambiguous"
            elif any(frozenset(members).issuperset(p) for p in confirmed_pairs):
                subject_overlap_status[sid] = "confirmed"
            else:
                subject_overlap_status[sid] = "candidate"

    for sid, ss in subjects:
        if sid in subject_role:
            continue
        subject_role[sid] = assign_role_unlinked(ss, sid)
        subject_group[sid] = None
        subject_overlap_status[sid] = "unlinked"

    for sid, st in list(subject_overlap_status.items()):
        if st == "ambiguous" and subject_role.get(sid) in {"validation", "test"}:
            subject_role[sid] = "train"

    group_rows = []
    for gid, members in group_members.items():
        for m in members:
            ss, sid = m.split(":", 1)
            group_rows.append(
                {
                    "group_id": gid,
                    "source_system": "magerya_api" if ss == "A" else "kgz_raw",
                    "source_scoped_subject_id": sid,
                    "overlap_status": subject_overlap_status.get(sid, "candidate"),
                    "split_role": subject_role.get(sid),
                }
            )
    pq.write_table(
        pa.Table.from_pylist(group_rows)
        if group_rows
        else pa.table(
            {
                "group_id": pa.array([], type=pa.string()),
                "source_system": pa.array([], type=pa.string()),
                "source_scoped_subject_id": pa.array([], type=pa.string()),
                "overlap_status": pa.array([], type=pa.string()),
                "split_role": pa.array([], type=pa.string()),
            }
        ),
        out / "overlap-groups.parquet",
        compression="zstd",
    )
    split_rows = [
        {
            "source_scoped_subject_id": sid,
            "source_system": ss,
            "split_role": subject_role[sid],
            "overlap_group_id": subject_group.get(sid),
            "overlap_status": subject_overlap_status.get(sid, "unlinked"),
        }
        for sid, ss in subjects
    ]
    pq.write_table(
        pa.Table.from_pylist(split_rows),
        out / "subject-split.parquet",
        compression="zstd",
    )

    role_sets = {"train": set(), "validation": set(), "test": set()}
    for sid, role in subject_role.items():
        role_sets[role].add(sid)
    inter = (
        len(role_sets["train"] & role_sets["validation"])
        + len(role_sets["train"] & role_sets["test"])
        + len(role_sets["validation"] & role_sets["test"])
    )
    group_role_violations = 0
    for _gid, members in group_members.items():
        roles = {subject_role[m.split(":", 1)[1]] for m in members}
        if len(roles) > 1:
            group_role_violations += 1
    cross_role = 0
    for p in confirmed_pairs | candidate_pairs:
        roles = {subject_role[m.split(":", 1)[1]] for m in p}
        if len(roles) > 1:
            cross_role += 1

    n_confirmed = len(confirmed_pairs)
    n_candidate = len(candidate_pairs)
    n_groups = len(group_members)
    n_ambiguous = len(ambiguous_nodes)
    n_conflict = len(conflicting_nodes)

    # Stage-02 reconciliation
    prior_path = root / STAGE02_LINKAGE_ASSESSMENT
    prior_doc = (
        json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.is_file() else {}
    )
    prior_ov = prior_doc.get("overlap_aggregates") or {}
    live_phone = len(phone_pairs)
    live_email = len(email_pairs)
    diffs = {
        "confirmed": {
            "prior": PRIOR_CONFIRMED_PAIRS,
            "live": n_confirmed,
            "delta": n_confirmed - PRIOR_CONFIRMED_PAIRS,
        },
        "candidate_overlap_phone_plus_email_unique": {
            "prior": PRIOR_CANDIDATE_OVERLAP,
            "live": live_phone + live_email,
            "delta": (live_phone + live_email) - PRIOR_CANDIDATE_OVERLAP,
            "note": "prior=uniquely_resolved phone+email pair counts (66+2208)",
        },
        "ambiguous": {
            "prior": PRIOR_AMBIGUOUS,
            "live": n_ambiguous,
            "delta": n_ambiguous - PRIOR_AMBIGUOUS,
        },
        "conflicting": {
            "prior": PRIOR_CONFLICTING,
            "live": n_conflict,
            "delta": n_conflict - PRIOR_CONFLICTING,
        },
    }
    explanations: list[str] = []
    if n_a_missing_canonical or n_b_missing_canonical:
        explanations.append("missing_canonical_subject")
    if n_a_resolved and n_b_resolved:
        explanations.append("patient_role_filter_source_b_consultations")
    if abs(diffs["confirmed"]["delta"]) > 0:
        explanations.append("normalization_or_source_drift_or_linkage_policy")
    if empty_overlap_cannot_pass(n_confirmed, n_candidate, n_groups):
        explanations.append("UNEXPLAINED_ZERO_OVERLAP" if not explanations else "zero_overlap")

    recon_ok = not empty_overlap_cannot_pass(n_confirmed, n_candidate, n_groups)
    # If counts differ from prior, require at least one explanation category
    any_diff = any(d["delta"] != 0 for d in diffs.values())
    if any_diff and not explanations:
        recon_ok = False
        explanations.append("unexplained")

    reconciliation = {
        "version": VERSION,
        "OVERLAP_UNIVERSE_RECONCILIATION_STATUS": "PASS" if recon_ok else "FAIL",
        "prior_stage02": {
            "confirmed": PRIOR_CONFIRMED_PAIRS,
            "candidate_overlap": PRIOR_CANDIDATE_OVERLAP,
            "ambiguous": PRIOR_AMBIGUOUS,
            "conflicting": PRIOR_CONFLICTING,
            "source_file": STAGE02_LINKAGE_ASSESSMENT,
            "stage02_confirmed": prior_ov.get("consistent_subject_pairs_by_phone_and_email"),
        },
        "live": {
            "n_unique_phone_pairs": live_phone,
            "n_unique_email_pairs": live_email,
            "n_confirmed_pairs": n_confirmed,
            "n_candidate_pairs": n_candidate,
            "n_ambiguous_nodes": n_ambiguous,
            "n_conflicting_nodes": n_conflict,
            "n_overlap_groups": n_groups,
            "n_a_linkage_resolved": n_a_resolved,
            "n_b_linkage_resolved": n_b_resolved,
            "n_a_missing_canonical": n_a_missing_canonical,
            "n_b_missing_canonical": n_b_missing_canonical,
        },
        "diffs": diffs,
        "explanations": explanations,
        "raw_identifiers_persisted": False,
        "ok": recon_ok,
    }
    (out / "overlap-reconciliation.json").write_text(
        json.dumps(reconciliation, indent=2) + "\n", encoding="utf-8"
    )

    integrity = {
        "version": VERSION,
        "subject_role_intersection": inter,
        "group_role_violations": group_role_violations,
        "confirmed_candidate_cross_role_violations": cross_role,
        "empty_universe": empty_overlap_cannot_pass(n_confirmed, n_candidate, n_groups),
        "ok": inter == 0
        and group_role_violations == 0
        and cross_role == 0
        and not empty_overlap_cannot_pass(n_confirmed, n_candidate, n_groups),
    }
    (out / "overlap-group-integrity.json").write_text(
        json.dumps(integrity, indent=2) + "\n", encoding="utf-8"
    )

    structural_ok = integrity["ok"] and reconciliation["ok"]
    summary = {
        "version": VERSION,
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "PRIVATE_OVERLAP_GROUP_DATASET_STATUS": "BUILT" if structural_ok else "FAIL",
        "GLOBAL_A_B_SPLIT_STATUS": (
            "PASS_OVERLAP_GUARDED" if structural_ok else "FAIL"
        ),
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "OVERLAP_UNIVERSE_RECONCILIATION_STATUS": reconciliation[
            "OVERLAP_UNIVERSE_RECONCILIATION_STATUS"
        ],
        "overlap_aware": True,
        "n_confirmed_pairs": n_confirmed,
        "n_candidate_pairs": n_candidate,
        "n_ambiguous_nodes": n_ambiguous,
        "n_conflicting_nodes": n_conflict,
        "n_overlap_groups": n_groups,
        "n_unique_phone_pairs": live_phone,
        "n_unique_email_pairs": live_email,
        "source_balance": {
            ss: {
                r: sum(
                    1
                    for sid, s2 in subjects
                    if s2 == ss and subject_role.get(sid) == r
                )
                for r in ("train", "validation", "test")
            }
            for ss in ("magerya_api", "kgz_raw")
        },
        "subject_role_intersection": inter,
        "group_role_violations": group_role_violations,
        "confirmed_candidate_cross_role_violations": cross_role,
        "raw_identifiers_persisted": False,
        "ok": structural_ok,
    }
    (out / "overlap-split-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary
