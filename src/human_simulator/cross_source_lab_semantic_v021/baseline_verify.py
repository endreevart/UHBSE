"""Baseline verification — immutable lab semantic discovery v0.2."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.policy import (
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_PRIVACY_XS_SHA256,
    ACCEPTED_PRIVACY_XS_ZIP,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ACCEPTED_V011_SHA256,
    ACCEPTED_V011_ZIP,
    ACCEPTED_V02_ARTIFACT_DIR,
    ACCEPTED_V02_MEMBERS,
    ACCEPTED_V02_SHA256,
    ACCEPTED_V02_ZIP,
    VERSION,
)

_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")

# v0.2 accounting pins (reproduced)
V02_ACCOUNTING = {
    "a_grains": 95,
    "b_code_unit_strata": 2426,
    "candidate_records": 1096,
    "a_grains_with_candidate": 56,
    "no_candidate_after_exhaustive_search": 39,
    "semantically_aligned": 0,
    "accepted": 0,
    "technical_shadow_eligible": 0,
    "scientifically_usable": 0,
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    priors = {
        "v02": (ACCEPTED_V02_ZIP, ACCEPTED_V02_SHA256),
        "v011": (ACCEPTED_V011_ZIP, ACCEPTED_V011_SHA256),
        "v01": (ACCEPTED_V01_ZIP, ACCEPTED_V01_SHA256),
        "privacy": (ACCEPTED_PRIVACY_XS_ZIP, ACCEPTED_PRIVACY_XS_SHA256),
        "gs011": (ACCEPTED_GS011_ZIP, ACCEPTED_GS011_SHA256),
    }
    before: dict[str, str] = {}
    for label, (name, exp) in priors.items():
        p = external / name
        dig = _sha(p) if p.is_file() else None
        before[label] = dig or ""
        add(f"{label}_sha", dig == exp, dig)

    z = external / ACCEPTED_V02_ZIP
    members = indexed = cache_n = None
    man_ok = tests_in = False
    accounting_ok = False
    if z.is_file():
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            indexed = members - (
                1 if any(n.endswith("REVIEW_INDEX.md") for n in names) else 0
            )
            cache_n = sum(1 for n in names if _CACHE_RE.search(n))
            art = ACCEPTED_V02_ARTIFACT_DIR
            man = zf.read(f"{art}/evidence-manifest.sha256").decode()
            mism: list[str] = []
            for line in man.splitlines():
                line = line.strip()
                if not line:
                    continue
                digest, _, name = line.partition("  ")
                if not name:
                    digest, _, name = line.partition(" ")
                name = name.strip()
                if name == "tests.json":
                    tests_in = True
                member = f"{art}/{name}"
                data = zf.read(member)
                if hashlib.sha256(data).hexdigest() != digest.strip():
                    mism.append(name)
            man_ok = not mism and tests_in

            # Reproduce v0.2 accounting from published status / graph summary
            st = json.loads(zf.read(f"{art}/status-contract.json").decode())
            graph_sum = json.loads(
                zf.read(f"{art}/cross-source-candidate-graph-public.json").decode()
            )
            accounting = {
                "a_grains": graph_sum.get("A_PROVIDER_GRAINS_EVALUATED")
                or st.get("A_PROVIDER_GRAINS_EVALUATED"),
                "b_code_unit_strata": graph_sum.get("B_OUTCOME_UNIT_STRATA_EVALUATED")
                or st.get("B_OUTCOME_UNIT_STRATA_EVALUATED"),
                "candidate_records": graph_sum.get("n_records_total")
                or graph_sum.get("n_candidate_records"),
                "a_grains_with_candidate": graph_sum.get("n_a_with_ge1_b_candidate"),
                "no_candidate_after_exhaustive_search": graph_sum.get(
                    "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT"
                )
                or st.get("NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT"),
                "semantically_aligned": graph_sum.get(
                    "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT"
                )
                or st.get("SEMANTICALLY_ALIGNED_CANDIDATE_COUNT"),
                "accepted": st.get("DOMAIN_ACCEPTED_MAPPING_COUNT"),
                "technical_shadow_eligible": st.get(
                    "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT"
                ),
                "scientifically_usable": st.get(
                    "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT"
                ),
            }
            accounting_ok = all(
                accounting.get(k) == v for k, v in V02_ACCOUNTING.items()
            )
            add("v02_accounting", accounting_ok, accounting)

        add("members_572", members == ACCEPTED_V02_MEMBERS, members)
        add("indexed_571", indexed == ACCEPTED_V02_MEMBERS - 1, indexed)
        add("cache_zero", cache_n == 0, cache_n)
        add("manifest_ok", man_ok)
        add("tests_json_in_manifest", tests_in)
        side = external / f"{ACCEPTED_V02_ZIP}.sha256"
        add(
            "sidecar",
            side.is_file() and side.read_text().split()[0] == ACCEPTED_V02_SHA256,
        )
        att = external / ACCEPTED_V02_ZIP.replace(".zip", ".attestation.json")
        if att.is_file():
            a = json.loads(att.read_text(encoding="utf-8"))
            add("attestation_pass", a.get("attestation_status") == "PASS")
            add(
                "attestation_sha",
                a.get("sha256") == ACCEPTED_V02_SHA256,
                a.get("sha256"),
            )

    after = {label: _sha(external / name) for label, (name, _) in priors.items()}
    add("prior_before_equals_after", before == after)

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "v02_members": members,
        "v02_indexed": indexed,
        "cache_members": cache_n,
        "v02_accounting_expected": V02_ACCOUNTING,
        "prior_before": before,
        "prior_after": after,
        "checks": checks,
        "ok": ok,
    }
