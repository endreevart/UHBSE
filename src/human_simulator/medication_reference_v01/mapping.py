"""Candidate generation and decision rules for 487 source medicines."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v01.policy import (
    ACCEPTED_STATUSES,
    EXPECTED_MEDICINE_IDS,
    PRIOR_CONCEPT_REGISTRY,
    RUNTIME_DIR,
    SOURCE_A,
    VERSION,
)
from human_simulator.medication_reference_v01.providers import RxNormClient

_RE_STRENGTH = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>мг|mg|мкг|mcg|г|g|мл|ml|%|МЕ|IU)\b",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return " ".join(str(s).strip().split()).casefold()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_source_records(root: Path) -> list[dict[str, Any]]:
    path = root / PRIOR_CONCEPT_REGISTRY
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def prioritize_queue(
    records: list[dict[str, Any]],
    coverage: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple:
        mid = str(r["source_medicine_id"])
        cov = coverage.get(mid) or {}
        return (
            -int(cov.get("n_episodes") or 0),
            -int(cov.get("n_subjects") or 0),
            -int(cov.get("n_outcomes") or 0),
            int(mid) if mid.isdigit() else mid,
        )

    return sorted(records, key=key)


def _extract_rxcuis(resp: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not resp:
        return []
    out = []
    # rxcui.json shape: idGroup.rxnormId
    id_group = (resp.get("idGroup") or {}) if isinstance(resp, dict) else {}
    for rid in id_group.get("rxnormId") or []:
        out.append({"rxcui": str(rid), "source": "rxcui_by_name"})
    # approximateTerm shape
    approx = (resp.get("approximateGroup") or {}) if isinstance(resp, dict) else {}
    for cand in approx.get("candidate") or []:
        out.append(
            {
                "rxcui": str(cand.get("rxcui")),
                "score": cand.get("score"),
                "rank": cand.get("rank"),
                "source": "approximateTerm",
                "name": cand.get("name") or cand.get("candidate"),
            }
        )
    # dedupe by rxcui
    seen = set()
    uniq = []
    for c in out:
        if not c.get("rxcui") or c["rxcui"] in seen:
            continue
        seen.add(c["rxcui"])
        uniq.append(c)
    return uniq


def decide_mapping(
    *,
    record: dict[str, Any],
    rxcui_exact: dict[str, Any],
    rxcui_approx: dict[str, Any],
    human_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply acceptance rules. LLM cannot auto-accept."""
    name = record.get("original_name") or ""
    norm = record.get("normalized_source_name") or _norm(name)
    mid = str(record["source_medicine_id"])

    if human_decision:
        d = human_decision.get("decision")
        if d == "HUMAN_ACCEPTED":
            return {
                "source_medicine_id": mid,
                "drug_concept_status": "HUMAN_ACCEPTED",
                "provider": human_decision.get("provider"),
                "provider_concept_id": human_decision.get("provider_concept_id"),
                "provider_evidence_hash": human_decision.get("provider_evidence_hash"),
                "human_decision_hash": human_decision.get("entry_hash"),
                "domain_review_required": False,
            }
        if d == "HUMAN_REJECTED":
            return {
                "source_medicine_id": mid,
                "drug_concept_status": "HUMAN_REJECTED",
                "domain_review_required": True,
                "human_decision_hash": human_decision.get("entry_hash"),
            }
        if d == "AMBIGUOUS":
            return {
                "source_medicine_id": mid,
                "drug_concept_status": "AMBIGUOUS",
                "domain_review_required": True,
                "human_decision_hash": human_decision.get("entry_hash"),
            }

    exact_hits = _extract_rxcuis((rxcui_exact or {}).get("response"))
    approx_hits = _extract_rxcuis((rxcui_approx or {}).get("response"))

    # Exact provider match: exactly one concept from exact name API + exact normalized equality
    # to a returned name if present; strength/form must not conflict.
    status = "NO_MATCH"
    ambiguity: list[str] = []
    conflict: list[str] = []
    chosen = None
    confidence = "none"
    evidence_hash = (rxcui_exact or {}).get("response_sha256") or (
        rxcui_approx or {}
    ).get("response_sha256")

    if len(exact_hits) == 1 and (rxcui_exact or {}).get("retrieval_status") == "VERIFIED":
        # RxNorm name lookup returned single RXCUI — still require name identity discipline.
        # For non-Latin source names, exact English RxNorm hit is rare; treat as CANDIDATE
        # unless returned name normalizes equal to source (almost never for Russian).
        hit = exact_hits[0]
        provider_name = _norm(str(hit.get("name") or ""))
        if provider_name and provider_name == norm:
            # Check strength candidates vs nothing on provider → ok if source has no strength
            status = "EXACT_PROVIDER_MATCH"
            chosen = hit
            confidence = "high"
        else:
            status = "CANDIDATE"
            chosen = hit
            confidence = "medium"
            ambiguity.append("single_rxcui_but_name_not_exact_normalized_equal")
    elif len(exact_hits) > 1:
        status = "AMBIGUOUS"
        ambiguity.append(f"n_exact_rxcui={len(exact_hits)}")
        confidence = "low"
    elif approx_hits:
        # Fuzzy/approximate → never EXACT
        if len(approx_hits) == 1:
            status = "CANDIDATE"
            chosen = approx_hits[0]
            confidence = "low"
            ambiguity.append("approximateTerm_single_hit")
        else:
            status = "AMBIGUOUS"
            ambiguity.append(f"n_approx={len(approx_hits)}")
            confidence = "low"
    else:
        status = "NO_MATCH"

    strengths = [
        m.groupdict()
        for m in _RE_STRENGTH.finditer(
            f"{name}\n{record.get('original_description') or ''}"
        )
    ]

    return {
        "source_system": SOURCE_A,
        "source_medicine_id": mid,
        "source_text_hash": record.get("source_text_hash") or _sha(name),
        "normalized_source_name_hash": _sha(norm) if norm else None,
        "drug_concept_status": status,
        "mapping_confidence": confidence,
        "ambiguity": ambiguity,
        "conflict": conflict,
        "provider": "RxNorm" if chosen else None,
        "provider_concept_id": (chosen or {}).get("rxcui"),
        "provider_evidence_hash": evidence_hash,
        "candidate_rxcuis": [
            c.get("rxcui") for c in (exact_hits + approx_hits)[:10] if c.get("rxcui")
        ],
        "candidate_strength_count": len(strengths),
        "llm_candidate_only": False,
        "domain_review_required": status not in ACCEPTED_STATUSES,
        "provenance": {
            "rxcui_exact_request_sha": (rxcui_exact or {}).get("request_sha256"),
            "rxcui_approx_request_sha": (rxcui_approx or {}).get("request_sha256"),
            "transformation_id": "medication_reference_mapping_v0.1",
            "transformation_version": VERSION,
        },
    }


def run_provider_mapping(
    root: Path,
    *,
    coverage: dict[str, dict[str, Any]],
    human_decisions: dict[str, dict[str, Any]] | None = None,
    allow_network: bool = True,
    max_records: int | None = None,
) -> dict[str, Any]:
    records = load_source_records(root)
    if len(records) != EXPECTED_MEDICINE_IDS:
        # still process but report
        pass
    queue = prioritize_queue(records, coverage)
    if max_records is not None:
        queue = queue[:max_records]

    client = RxNormClient(root, allow_network=allow_network)
    human_decisions = human_decisions or {}
    mapped = []
    status_counts: dict[str, int] = defaultdict(int)

    for rec in queue:
        mid = str(rec["source_medicine_id"])
        name = rec.get("original_name") or ""
        # Catalog-only queries
        exact = client.get_rxcui_by_name(name) if name.strip() else {
            "retrieval_status": "SKIPPED_EMPTY_NAME",
            "response": None,
        }
        approx = (
            client.approximate_term(name)
            if name.strip() and (exact.get("retrieval_status") != "VERIFIED" or not _extract_rxcuis(exact.get("response")))
            else {"retrieval_status": "SKIPPED", "response": None}
        )
        # Always try approximate if exact empty
        if name.strip() and not _extract_rxcuis((exact or {}).get("response")):
            if approx.get("retrieval_status") == "SKIPPED":
                approx = client.approximate_term(name)

        decision = decide_mapping(
            record=rec,
            rxcui_exact=exact,
            rxcui_approx=approx,
            human_decision=human_decisions.get(mid),
        )
        cov = coverage.get(mid) or {}
        decision["episode_coverage"] = cov
        status_counts[decision["drug_concept_status"]] += 1
        mapped.append(decision)

    accepted = sum(status_counts[s] for s in ACCEPTED_STATUSES)
    unresolved = sum(
        status_counts[s]
        for s in status_counts
        if s not in ACCEPTED_STATUSES and s != "HUMAN_REJECTED"
    )
    # HUMAN_REJECTED counts as resolved-but-not-accepted
    private_dir = root / RUNTIME_DIR / "registry"
    private_dir.mkdir(parents=True, exist_ok=True)
    private_path = private_dir / "medication-reference-mapping.private.jsonl"
    with private_path.open("w", encoding="utf-8") as fh:
        for row in mapped:
            # merge original name only in private file
            src = next(r for r in records if str(r["source_medicine_id"]) == row["source_medicine_id"])
            full = {**row, "original_name": src.get("original_name"), "original_description": src.get("original_description")}
            fh.write(json.dumps(full, ensure_ascii=False, sort_keys=True) + "\n")

    sanitized = [
        {
            "source_medicine_id_hash": hashlib.sha256(
                str(m["source_medicine_id"]).encode()
            ).hexdigest()[:16],
            "drug_concept_status": m["drug_concept_status"],
            "provider": m.get("provider"),
            "provider_concept_id": m.get("provider_concept_id"),
            "provider_evidence_hash": m.get("provider_evidence_hash"),
            "ambiguity": m.get("ambiguity") or [],
            "conflict": m.get("conflict") or [],
            "domain_review_required": m.get("domain_review_required"),
            "n_episodes": (m.get("episode_coverage") or {}).get("n_episodes", 0),
            "n_subjects": (m.get("episode_coverage") or {}).get("n_subjects", 0),
        }
        for m in mapped
    ]

    return {
        "version": VERSION,
        "n_records": len(mapped),
        "expected": EXPECTED_MEDICINE_IDS,
        "status_counts": dict(status_counts),
        "DRUG_CONCEPT_ACCEPTED_COUNT": accepted,
        "DRUG_CONCEPT_UNRESOLVED_COUNT": unresolved,
        "mapped": mapped,
        "sanitized": sanitized,
        "rxnorm_stats": client.stats,
        "rxnorm_verified_n": sum(
            1
            for m in mapped
            if m.get("provider_evidence_hash")
        ),
        "private_path": str(private_path.relative_to(root)),
    }
