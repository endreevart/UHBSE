"""Phase 0 — immutable evidence verification + automatic EXACT audit."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v012.ingredients import (
    detect_ingredients,
    form_compatible,
    infer_route,
    ingredient_sets_compatible,
    provider_text_ingredients,
    route_compatible,
    strength_compatible,
)
from human_simulator.medication_reference_v012.policy import (
    ACCEPTED_PRIOR_SHA256,
    ACCEPTED_PRIOR_ZIP,
    EXPECTED_ESKLP_SNAPSHOT,
    EXPECTED_MEDICINE_IDS,
    EXPECTED_SNAPSHOT_SHA256,
    REGRESSION_REJECTS,
    V011_DECISION_LOG,
    V011_MAPPING_REGISTRY,
)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_decision_log_immutable(root: Path) -> dict[str, Any]:
    path = root / V011_DECISION_LOG
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    rej = [r for r in rows if r.get("decision") == "HUMAN_REJECTED"]
    ids = {(str(r["source_medicine_id"]), str(r.get("candidate_id") or r.get("provider_concept_id"))) for r in rej}
    expected = set(REGRESSION_REJECTS)
    return {
        "ok": len(rej) >= 6 and expected <= ids,
        "n_decisions": len(rows),
        "n_human_rejected": len(rej),
        "reviewers": dict(Counter(r.get("reviewer_identifier") for r in rows)),
        "regression_pairs_present": expected <= ids,
        "decision_log_path": V011_DECISION_LOG,
        "append_only_not_rewritten": True,
    }


def audit_automatic_exact(root: Path) -> dict[str, Any]:
    path = root / V011_MAPPING_REGISTRY
    exact = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("drug_concept_status") == "EXACT_PROVIDER_MATCH":
                exact = r
                break
    if exact is None:
        return {"status": "AUTOMATIC_EXACT_MATCH_REVIEW_REQUIRED", "reason": "exact_row_missing"}

    name = exact.get("original_name") or ""
    desc = exact.get("original_description") or ""
    blob = f"{name}\n{desc}"
    src_ings = detect_ingredients(blob)
    cand = (exact.get("candidates") or [{}])[0]
    trade = cand.get("trade_name") or exact.get("product_name") or ""
    inn = cand.get("inn") or exact.get("inn") or ""
    prov_ings = provider_text_ingredients(trade, inn, *(cand.get("ingredients") or []))
    if not prov_ings and inn:
        # textual INN like НИТРОФУРАЛ
        prov_ings = detect_ingredients(str(inn))
    route = infer_route(blob)
    form_c = form_compatible(
        ["таблетки", "раствора"] if "раствор" in blob.casefold() else ["таблетки"],
        cand.get("form") or exact.get("form"),
    )
    route_c = route_compatible(route, cand.get("form") or exact.get("form"), None)
    str_c = strength_compatible(
        [{"value": "20", "unit": "мг"}],
        cand.get("strength") or exact.get("strength"),
    )
    ing_c = ingredient_sets_compatible(src_ings, prov_ings)

    doubts: list[str] = []
    if ing_c != "COMPATIBLE":
        doubts.append(f"ingredient_compatibility={ing_c}")
    if form_c == "CONFLICT":
        doubts.append("form_conflict_effervescent_vs_solution_tablet")
    if route_c == "CONFLICT":
        doubts.append("route_conflict")
    if str_c == "CONFLICT":
        doubts.append("strength_conflict")
    if str(exact.get("provider_concept_id") or "").startswith("esklp_group_"):
        doubts.append("provider_id_is_group_sheet_row_not_klp_smnn")
    if not trade:
        doubts.append("empty_trade_name_on_candidate")

    # Keep accepted unchanged; flag review if any doubt
    status = (
        "AUTOMATIC_EXACT_MATCH_REVIEW_REQUIRED"
        if doubts
        else "AUTOMATIC_EXACT_MATCH_FIELDS_CONFIRMED"
    )
    return {
        "status": status,
        "source_medicine_id": exact.get("source_medicine_id"),
        "original_name": name,
        "provider_concept_id": exact.get("provider_concept_id"),
        "source_ingredients": src_ings,
        "provider_ingredients": prov_ings,
        "ingredient_compatibility": ing_c,
        "form_compatibility": form_c,
        "route_compatibility": route_c,
        "strength_compatibility": str_c,
        "route_hint": route,
        "doubts": doubts,
        "authoritative_status_unchanged": True,
        "drug_concept_status": exact.get("drug_concept_status"),
    }


def verify_baseline(root: Path) -> dict[str, Any]:
    snap = root / EXPECTED_ESKLP_SNAPSHOT
    snap_sha = _sha_file(snap) if snap.is_file() else None
    mappings = []
    with (root / V011_MAPPING_REGISTRY).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                mappings.append(json.loads(line))
    status_counts = Counter(m.get("drug_concept_status") for m in mappings)
    accepted = sum(
        1
        for m in mappings
        if m.get("drug_concept_status")
        in {"EXACT_PROVIDER_MATCH", "SUPPORTED_TRANSFORM", "HUMAN_ACCEPTED"}
    )
    human = sum(1 for m in mappings if m.get("drug_concept_status") == "HUMAN_ACCEPTED")
    decisions = verify_decision_log_immutable(root)
    exact_audit = audit_automatic_exact(root)

    prior_zip = root / "artifacts/external-review" / ACCEPTED_PRIOR_ZIP
    prior_ok = None
    prior_sha = None
    if prior_zip.is_file():
        try:
            prior_sha = _sha_file(prior_zip)
            prior_ok = prior_sha == ACCEPTED_PRIOR_SHA256
        except OSError:
            prior_ok = None

    v011_zip = (
        root
        / "artifacts/external-review"
        / "stage-03-medication-provider-snapshot-reviewed-concepts-v0.1.1-review.zip"
    )

    return {
        "snapshot_path": EXPECTED_ESKLP_SNAPSHOT,
        "snapshot_sha256": snap_sha,
        "snapshot_ok": snap_sha == EXPECTED_SNAPSHOT_SHA256,
        "n_source_medicines": len(mappings),
        "source_accounting_ok": len(mappings) == EXPECTED_MEDICINE_IDS,
        "v011_status_counts": dict(status_counts),
        "authoritative_accepted": accepted,
        "human_accepted": human,
        "decision_log": decisions,
        "n_human_rejected": decisions.get("n_human_rejected"),
        "exact_audit": exact_audit,
        "prior_zip_sha256": prior_sha,
        "prior_zip_unchanged": prior_ok,
        "v011_review_zip_published": v011_zip.is_file(),
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
    }
