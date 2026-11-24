"""Drug-concept harmonization registry for Source A medicines."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from human_simulator.medication_concept_v01.accounting import (
    apply_concept_counts_to_accounting,
    compute_source_accounting,
)
from human_simulator.medication_concept_v01.policy import (
    ACCEPTED_CONCEPT_STATUSES,
    EXPECTED_MEDICINE_IDS,
    RUNTIME_DIR,
    SOURCE_A,
    VERSION,
)

_RE_STRENGTH = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>мг|mg|мкг|mcg|г|g|мл|ml|%|МЕ|IU)\b",
    re.IGNORECASE,
)
_RE_COMBO = re.compile(r"\s*[+/&]\s*|\s+и\s+", re.IGNORECASE)


def _text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _normalize_name(name: str) -> str:
    return " ".join(str(name).strip().split()).casefold()


def _load_provider_index(provider_manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    """Load verified provider snapshots into a name→records index if present."""
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in provider_manifest.get("providers") or []:
        if p.get("retrieval_status") != "VERIFIED":
            continue
        snap = p.get("source_url_or_local_snapshot")
        if not snap or not str(snap).endswith((".json", ".jsonl")):
            continue
        path = root / snap if not Path(snap).is_absolute() else Path(snap)
        if not path.is_file():
            continue
        if path.suffix == ".jsonl":
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw if isinstance(raw, list) else raw.get("records") or []
        for row in rows:
            key = _normalize_name(str(row.get("name") or row.get("normalized_name") or ""))
            if key:
                index[key].append(
                    {
                        **row,
                        "_provider": p.get("provider_name"),
                        "_snapshot_hash": p.get("content_hash"),
                        "_provider_version": p.get("dataset_api_version_or_retrieval_date"),
                    }
                )
    return {"by_normalized_name": dict(index)}


def _map_one(
    *,
    mid: str,
    name: str,
    description: str,
    provider_index: dict[str, Any],
) -> dict[str, Any]:
    name_s = name or ""
    desc_s = description or ""
    norm = _normalize_name(name_s) if name_s else None
    strengths = [
        {
            "value_raw": m.group("value"),
            "unit_raw": m.group("unit"),
            "status": "CANDIDATE",
            "method": "regex_source_text",
        }
        for m in _RE_STRENGTH.finditer(f"{name_s}\n{desc_s}")
    ]
    parts = [p.strip() for p in _RE_COMBO.split(name_s) if p.strip()]
    combo = None
    if len(parts) >= 2 and len(name_s) < 200:
        combo = {
            "components": parts,
            "status": "CANDIDATE",
            "method": "name_separator_split",
            "note": "Separator split is not accepted ingredient identity",
        }

    matches = []
    if norm:
        matches = list((provider_index.get("by_normalized_name") or {}).get(norm) or [])

    # Acceptance rules: exact name alone insufficient when multiple strengths/forms;
    # fuzzy/transliteration never EXACT; need provider record + snapshot hash.
    status = "NO_MATCH"
    ambiguity = []
    conflict = []
    confidence = "none"
    provider = None
    provider_version = None
    snapshot_hash = None
    ingredient_id = None
    brand = name_s if name_s else None
    active_ingredient = None
    atc = None
    rxcui = None
    dose_form = None
    route = None
    strength_value = strengths[0]["value_raw"] if strengths else None
    strength_unit = strengths[0]["unit_raw"] if strengths else None

    if len(matches) == 1:
        m = matches[0]
        # Still not EXACT without disambiguating strength/form when source has multiple cues
        provider = m.get("_provider")
        provider_version = m.get("_provider_version")
        snapshot_hash = m.get("_snapshot_hash")
        ingredient_id = m.get("ingredient_id") or m.get("RXCUI") or m.get("esklp_id")
        active_ingredient = m.get("active_ingredient")
        atc = m.get("atc")
        rxcui = m.get("RXCUI")
        dose_form = m.get("dose_form")
        route = m.get("route")
        if m.get("strength_value") and strength_value and str(m["strength_value"]) != str(
            strength_value
        ):
            status = "AMBIGUOUS"
            ambiguity.append("strength_mismatch_vs_provider")
            confidence = "low"
        elif snapshot_hash and provider and m.get("accept_exact") is True:
            status = "EXACT"
            confidence = "high"
        else:
            status = "CANDIDATE"
            confidence = "medium"
            ambiguity.append("single_provider_hit_requires_domain_review")
    elif len(matches) > 1:
        status = "AMBIGUOUS"
        ambiguity.append(f"n_provider_hits={len(matches)}")
        confidence = "low"
        provider = matches[0].get("_provider")
        snapshot_hash = matches[0].get("_snapshot_hash")
    else:
        status = "NO_MATCH" if name_s else "NO_MATCH"
        confidence = "none"

    # Never invent accepted ingredient/route
    if status not in ACCEPTED_CONCEPT_STATUSES:
        # Keep candidate parses separate from accepted fields
        pass

    domain_review = status != "EXACT"

    return {
        "source_system": SOURCE_A,
        "source_medicine_id": mid,
        "normalized_source_name": norm,
        "original_name": name_s,
        "original_description": desc_s,
        "source_text_hash": _text_hash(name_s + "\n" + desc_s),
        "brand_name": brand,
        "active_ingredient": active_ingredient if status in ACCEPTED_CONCEPT_STATUSES else None,
        "ingredient_identifier": ingredient_id if status in ACCEPTED_CONCEPT_STATUSES else None,
        "strength_value": strength_value if status in ACCEPTED_CONCEPT_STATUSES else None,
        "strength_unit": strength_unit if status in ACCEPTED_CONCEPT_STATUSES else None,
        "dose_form": dose_form if status in ACCEPTED_CONCEPT_STATUSES else None,
        "route": route if status in ACCEPTED_CONCEPT_STATUSES else None,
        "atc": atc if status in ACCEPTED_CONCEPT_STATUSES else None,
        "rxcui": rxcui if status in ACCEPTED_CONCEPT_STATUSES else None,
        "candidate_strength_value": strength_value,
        "candidate_strength_unit": strength_unit,
        "candidate_combination": combo,
        "provider": provider,
        "provider_version": provider_version,
        "snapshot_hash": snapshot_hash,
        "evidence": {
            "n_provider_hits": len(matches),
            "llm_candidate": False,
            "llm_status": None,
        },
        "mapping_confidence": confidence,
        "ambiguity": ambiguity,
        "conflict": conflict,
        "drug_concept_status": status,
        "domain_review_required": domain_review,
        "provenance": {
            "record_origin": "OBSERVED",
            "transformation_id": "medication_concept_harmonization_v0.1",
            "transformation_version": VERSION,
        },
    }


def build_concept_registry(
    conn_a: Any,
    root: Path,
    *,
    provider_manifest: dict[str, Any],
    episode_coverage: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with conn_a.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ma.medicine_id
            FROM magerya_api.diagnosis_medicineappointments ma
            WHERE ma.medicine_id IS NOT NULL
            ORDER BY 1
            """
        )
        med_ids = [int(r[0]) for r in cur.fetchall()]
        cur.execute(
            """
            SELECT m.id, m.name, m.description,
                   m.unit_of_measurement_id, m.form_id, m.reception_frequency_id
            FROM magerya_api.diagnosis_medicines m
            WHERE m.id = ANY(%s)
            ORDER BY m.id
            """,
            (med_ids,),
        )
        rows = {int(r[0]): r for r in cur.fetchall()}
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE unit_of_measurement_id IS NOT NULL),
              COUNT(*) FILTER (WHERE form_id IS NOT NULL),
              COUNT(*) FILTER (WHERE reception_frequency_id IS NOT NULL)
            FROM magerya_api.diagnosis_medicines m
            WHERE EXISTS (
              SELECT 1 FROM magerya_api.diagnosis_medicineappointments ma
              WHERE ma.medicine_id = m.id
            )
            """
        )
        u, f, fr = (int(x) for x in cur.fetchone())

    accounting = compute_source_accounting(
        med_ids,
        joined_ids=set(rows.keys()),
        expected=EXPECTED_MEDICINE_IDS,
    )
    accounting["fk_usable_nonnull"] = {
        "unit": u,
        "form": f,
        "frequency": fr,
    }

    provider_index = _load_provider_index(provider_manifest, root)
    records = []
    status_counts: dict[str, int] = defaultdict(int)
    for mid in med_ids:
        row = rows.get(mid)
        if row is None:
            rec = {
                "source_system": SOURCE_A,
                "source_medicine_id": str(mid),
                "drug_concept_status": "NO_MATCH",
                "domain_review_required": True,
                "mapping_confidence": "none",
                "ambiguity": ["missing_diagnosis_medicines_row"],
                "conflict": [],
            }
        else:
            _, name, desc, *_rest = row
            rec = _map_one(
                mid=str(mid),
                name="" if name is None else str(name),
                description="" if desc is None else str(desc),
                provider_index=provider_index,
            )
        cov = (episode_coverage or {}).get(str(mid)) or {}
        rec["episode_coverage"] = cov
        status_counts[rec["drug_concept_status"]] += 1
        records.append(rec)

    accounting = apply_concept_counts_to_accounting(
        accounting, by_concept_status=dict(status_counts)
    )

    private_dir = root / RUNTIME_DIR / "registry"
    private_dir.mkdir(parents=True, exist_ok=True)
    private_path = private_dir / "medication-concept-registry.private.jsonl"
    with private_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    sanitized = []
    for r in records:
        sanitized.append(
            {
                "source_medicine_id_hash": hashlib.sha256(
                    str(r["source_medicine_id"]).encode()
                ).hexdigest()[:16],
                "source_text_hash": r.get("source_text_hash"),
                "drug_concept_status": r["drug_concept_status"],
                "mapping_confidence": r.get("mapping_confidence"),
                "ambiguity": r.get("ambiguity") or [],
                "conflict": r.get("conflict") or [],
                "provider": r.get("provider"),
                "snapshot_hash": r.get("snapshot_hash"),
                "domain_review_required": r.get("domain_review_required", True),
                "has_candidate_strength": bool(r.get("candidate_strength_value")),
                "has_candidate_combination": bool(r.get("candidate_combination")),
                "accepted_ingredient": r.get("active_ingredient") is not None,
                "accepted_route": r.get("route") is not None,
                "episode_n": (r.get("episode_coverage") or {}).get("n_episodes", 0),
                "subject_n": (r.get("episode_coverage") or {}).get("n_subjects", 0),
            }
        )

    # Domain review queue prioritized by coverage, not test performance
    review = sorted(
        [
            {
                "source_medicine_id_hash": s["source_medicine_id_hash"],
                "drug_concept_status": s["drug_concept_status"],
                "ambiguity": s["ambiguity"],
                "n_episodes": s["episode_n"],
                "n_subjects": s["subject_n"],
                "n_outcomes": (episode_coverage or {})
                .get(
                    next(
                        (
                            r["source_medicine_id"]
                            for r in records
                            if hashlib.sha256(str(r["source_medicine_id"]).encode()).hexdigest()[
                                :16
                            ]
                            == s["source_medicine_id_hash"]
                        ),
                        "",
                    ),
                    {},
                )
                .get("n_outcomes", 0),
                "splits_present": (episode_coverage or {}).get(
                    next(
                        (
                            r["source_medicine_id"]
                            for r in records
                            if hashlib.sha256(str(r["source_medicine_id"]).encode()).hexdigest()[
                                :16
                            ]
                            == s["source_medicine_id_hash"]
                        ),
                        "",
                    ),
                    {},
                ).get("splits", []),
                "ambiguity_severity": len(s["ambiguity"]),
            }
            for s in sanitized
            if s["domain_review_required"]
        ],
        key=lambda x: (
            -int(x["n_episodes"] or 0),
            -int(x["n_subjects"] or 0),
            -int(x["ambiguity_severity"] or 0),
        ),
    )

    # Top unresolved / ambiguous groups (sanitized)
    ambiguous_groups = [x for x in review if x["drug_concept_status"] == "AMBIGUOUS"][:20]
    unresolved_top = [x for x in review if x["drug_concept_status"] in ("NO_MATCH", "CANDIDATE")][
        :20
    ]

    return {
        "accounting": accounting,
        "records": records,
        "sanitized_records": sanitized,
        "domain_review_queue": review,
        "top_ambiguous": ambiguous_groups,
        "top_unresolved": unresolved_top,
        "private_registry_path": str(private_path.relative_to(root)),
        "status_counts": dict(status_counts),
        "n_accepted": accounting.get("DRUG_CONCEPT_ACCEPTED_COUNT", 0),
        "n_unresolved": accounting.get("DRUG_CONCEPT_UNRESOLVED_COUNT", 0),
    }
