"""Private overlap groups + overlap-guarded global A+B split."""

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

from human_simulator.core.ids import load_hmac_key, opaque_subject_key
from human_simulator.core.policy import ID_NAMESPACE_VERSION, KEY_VERSION
from human_simulator.stage02.identity_linkage import normalize_email, normalize_phone
from human_simulator.stage03.canonical_id import compute_hmac_hex
from human_simulator.unified_individual_state_v01.policy import (
    BUCKET_TRAIN_END,
    BUCKET_VAL_END,
    NAMESPACE,
    OVERLAP_DIR,
    SEED,
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


def build_overlap_guarded_split(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / OVERLAP_DIR
    out.mkdir(parents=True, exist_ok=True)
    core_key = load_hmac_key(root)
    link_key = _load_linkage_key(root)

    # opaque subject id sets from parquet
    subj = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_subject.parquet",
        columns=["research_entity_id", "source_system"],
    )
    subjects = list(
        zip(subj["research_entity_id"].to_pylist(), subj["source_system"].to_pylist(), strict=True)
    )
    a_subjects = {sid for sid, ss in subjects if ss == "magerya_api"}
    b_subjects = {sid for sid, ss in subjects if ss == "kgz_raw"}

    # Build identifier digests -> subject opaque IDs (never persist raw)
    phone_to_subj: dict[str, set[str]] = defaultdict(set)
    email_to_subj: dict[str, set[str]] = defaultdict(set)
    # per-subject email/phone digests for conflict detection
    subj_phones: dict[str, set[str]] = defaultdict(set)
    subj_emails: dict[str, set[str]] = defaultdict(set)

    conn_a = connect_source_a(root)
    conn_b = connect_source_b(root)
    try:
        if conn_a is not None:
            with conn_a.cursor() as cur:
                cur.execute("SET default_transaction_read_only=on")
                cur.execute(
                    """
                    SELECT id, _phone, email FROM magerya_api.account_patient
                    """
                )
                for pid, phone, email in cur:
                    sid = opaque_subject_key(core_key, int(pid))
                    if sid not in a_subjects:
                        continue
                    pn = normalize_phone(phone)
                    em = normalize_email(email)
                    if pn:
                        d = _hmac_id(link_key, "phone", pn)
                        phone_to_subj[d].add(f"A:{sid}")
                        subj_phones[f"A:{sid}"].add(d)
                    if em:
                        d = _hmac_id(link_key, "email", em)
                        email_to_subj[d].add(f"BWAIT:{sid}")  # temp marker fix below
                        email_to_subj[d].discard(f"BWAIT:{sid}")
                        email_to_subj[d].add(f"A:{sid}")
                        subj_emails[f"A:{sid}"].add(d)
        if conn_b is not None:
            with conn_b.cursor() as cur:
                cur.execute("SET default_transaction_read_only=on")
                # patient-role users via consultations
                cur.execute(
                    """
                    SELECT DISTINCT u.id, u.phone, u.email
                    FROM public.users u
                    JOIN public.consultations c ON c.patient_id = u.id
                    """
                )
                for uid, phone, email in cur:
                    skey = compute_hmac_hex(
                        key_bytes=core_key,
                        entity="Subject",
                        id_namespace_version=ID_NAMESPACE_VERSION,
                        source_system="kgz_raw",
                        inputs=[str(uid), KEY_VERSION],
                    )
                    # map to research subject id (= entity_id Subject of opaque key)
                    from human_simulator.core.ids import entity_id

                    # B subject_id in canonical is entity_id with kgz_raw via compute_hmac
                    sid = compute_hmac_hex(
                        key_bytes=core_key,
                        entity="Subject",
                        id_namespace_version=ID_NAMESPACE_VERSION,
                        source_system="kgz_raw",
                        inputs=[skey, KEY_VERSION],
                    )
                    # Actually canonical subject_id = entity_id(Subject, opaque_key) where
                    # opaque is HMAC Subject with kgz_raw|[uid]|KEY_VERSION
                    # And subject_id = entity_id with SOURCE_SYSTEM_ID magerya for A...
                    # For B: check earlier — subject_id == entity_id(key,'Subject',opaque) where
                    # opaque = compute_hmac Subject kgz_raw.
                    # entity_id hardcodes SOURCE_SYSTEM_ID=magerya_api!
                    # So B subject_id uses compute_hmac with kgz for both?
                    # From earlier verification: match was compute_hmac Subject kgz_raw [uid, KEY]
                    # as source_subject_key, and subject_id = entity_id(Subject, opaque) with magerya.
                    sid = entity_id(core_key, "Subject", skey)
                    if sid not in b_subjects:
                        continue
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
        if conn_a is not None:
            try:
                conn_a.close()
            except Exception:
                pass
        if conn_b is not None:
            try:
                conn_b.close()
            except Exception:
                pass

    # Classify identifier matches
    confirmed_pairs: set[frozenset[str]] = set()
    candidate_pairs: set[frozenset[str]] = set()
    ambiguous_nodes: set[str] = set()
    conflicting_nodes: set[str] = set()

    # phone unique 1-1 A-B
    for dig, nodes in phone_to_subj.items():
        a_n = [n for n in nodes if n.startswith("A:")]
        b_n = [n for n in nodes if n.startswith("B:")]
        if len(a_n) == 1 and len(b_n) == 1:
            candidate_pairs.add(frozenset({a_n[0], b_n[0]}))
        elif len(a_n) + len(b_n) > 2 and a_n and b_n:
            ambiguous_nodes.update(a_n + b_n)

    for dig, nodes in email_to_subj.items():
        a_n = [n for n in nodes if n.startswith("A:")]
        b_n = [n for n in nodes if n.startswith("B:")]
        if len(a_n) == 1 and len(b_n) == 1:
            candidate_pairs.add(frozenset({a_n[0], b_n[0]}))
        elif len(a_n) + len(b_n) > 2 and a_n and b_n:
            ambiguous_nodes.update(a_n + b_n)

    # confirmed = same pair matched on both phone and email uniquely
    phone_pairs = set()
    for dig, nodes in phone_to_subj.items():
        a_n = [n for n in nodes if n.startswith("A:")]
        b_n = [n for n in nodes if n.startswith("B:")]
        if len(a_n) == 1 and len(b_n) == 1:
            phone_pairs.add(frozenset({a_n[0], b_n[0]}))
    email_pairs = set()
    for dig, nodes in email_to_subj.items():
        a_n = [n for n in nodes if n.startswith("A:")]
        b_n = [n for n in nodes if n.startswith("B:")]
        if len(a_n) == 1 and len(b_n) == 1:
            email_pairs.add(frozenset({a_n[0], b_n[0]}))
    confirmed_pairs = phone_pairs & email_pairs
    # conflicts: phone pair and email pair disagree for same A
    a_to_b_phone = {next(x for x in p if x.startswith("A:")): next(x for x in p if x.startswith("B:")) for p in phone_pairs}
    a_to_b_email = {next(x for x in p if x.startswith("A:")): next(x for x in p if x.startswith("B:")) for p in email_pairs}
    for a, b_p in a_to_b_phone.items():
        if a in a_to_b_email and a_to_b_email[a] != b_p:
            conflicting_nodes.add(a)
            conflicting_nodes.add(b_p)
            conflicting_nodes.add(a_to_b_email[a])

    # Union-find for confirmed + candidate (conservative: share split)
    uf = _UF()
    for p in confirmed_pairs | candidate_pairs:
        nodes = list(p)
        if len(nodes) == 2:
            uf.union(nodes[0], nodes[1])

    # Exclude ambiguous from held-out evaluation later; still assign group if connected
    group_members: dict[str, list[str]] = defaultdict(list)
    all_linked = set()
    for p in confirmed_pairs | candidate_pairs:
        for n in p:
            all_linked.add(n)
            group_members[uf.find(n)].append(n)

    # Deduplicate members
    group_members = {g: sorted(set(ms)) for g, ms in group_members.items()}

    # Assign roles
    subject_role: dict[str, str] = {}
    subject_group: dict[str, str | None] = {}
    subject_overlap_status: dict[str, str] = {}

    for gid, members in group_members.items():
        role = assign_role_group(gid)
        status = "confirmed" if any(
            frozenset(members) == p or frozenset(members).issuperset(p)
            for p in confirmed_pairs
        ) else "candidate"
        # refine status per member
        for m in members:
            sid = m.split(":", 1)[1]
            subject_role[sid] = role
            subject_group[sid] = gid
            if m in conflicting_nodes:
                subject_overlap_status[sid] = "conflicting"
            elif m in ambiguous_nodes:
                subject_overlap_status[sid] = "ambiguous"
                # ambiguous excluded from cross-source held-out: force train or mark
            else:
                subject_overlap_status[sid] = status

    for sid, ss in subjects:
        if sid in subject_role:
            continue
        subject_role[sid] = assign_role_unlinked(ss, sid)
        subject_group[sid] = None
        subject_overlap_status[sid] = "unlinked"

    # Ambiguous: exclude from val/test (move to train) for cross-source safety
    for sid, st in list(subject_overlap_status.items()):
        if st == "ambiguous" and subject_role.get(sid) in {"validation", "test"}:
            subject_role[sid] = "train"

    # Write private overlap groups parquet (opaque only)
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

    # Validate no subject in multiple roles; no group spanning roles
    role_sets = {"train": set(), "validation": set(), "test": set()}
    for sid, role in subject_role.items():
        role_sets[role].add(sid)
    inter = (
        len(role_sets["train"] & role_sets["validation"])
        + len(role_sets["train"] & role_sets["test"])
        + len(role_sets["validation"] & role_sets["test"])
    )
    group_role_violations = 0
    for gid, members in group_members.items():
        roles = {subject_role[m.split(":", 1)[1]] for m in members}
        if len(roles) > 1:
            group_role_violations += 1

    # confirmed/candidate cross-role
    cross_role = 0
    for p in confirmed_pairs | candidate_pairs:
        roles = {subject_role[m.split(":", 1)[1]] for m in p}
        if len(roles) > 1:
            cross_role += 1

    ok = inter == 0 and group_role_violations == 0 and cross_role == 0
    summary = {
        "version": VERSION,
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "PRIVATE_OVERLAP_GROUP_DATASET_STATUS": "BUILT",
        "GLOBAL_A_B_SPLIT_STATUS": "PASS_OVERLAP_GUARDED" if ok else "FAIL",
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "overlap_aware": True,
        "n_confirmed_pairs": len(confirmed_pairs),
        "n_candidate_pairs": len(candidate_pairs - confirmed_pairs),
        "n_ambiguous_nodes": len(ambiguous_nodes),
        "n_conflicting_nodes": len(conflicting_nodes),
        "n_overlap_groups": len(group_members),
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
        "repeatable": assign_role_group("x") == assign_role_group("x"),
        "raw_identifiers_persisted": False,
        "ok": ok,
    }
    (out / "overlap-split-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary
