"""Run discovery v0.2. Does not write the v0.1 baseline or a review ZIP."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.baseline import verify_baseline
from human_simulator.exposure_source_discovery_v02.db import QueryLog, connect_a, connect_b, schema_fingerprint
from human_simulator.exposure_source_discovery_v02.decisions import (
    decision_schema,
    questions_markdown,
    response_template,
    semantics_status,
)
from human_simulator.exposure_source_discovery_v02.limitations import reproduce
from human_simulator.exposure_source_discovery_v02.mutations import run_negative_controls
from human_simulator.exposure_source_discovery_v02.policy import (
    ARTIFACT_DIR,
    REQUIRED_ARTIFACTS,
    SCIENTIFIC_CEILING,
    VERSION,
    policy_snapshot,
)
from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v02.source_a import localize, structured_linkage
from human_simulator.exposure_source_discovery_v02.source_b import (
    identity_audit,
    schema_contract,
    sentinel_profile,
    temporal_audit,
)
from human_simulator.exposure_source_discovery_v02.textutil import CatalogMatcher

A_TABLES = [
    ("magerya_api", "document_recommendation"),
    ("magerya_api", "document_medicalreport"),
    ("magerya_api", "diagnosis_medicineappointments"),
    ("magerya_api", "diagnosis_medicines"),
    ("magerya_api", "appointment_appointment"),
]
B_TABLES = [
    ("public", "feedback"),
    ("public", "consultations"),
    ("public", "questionnaire"),
    ("quest_digital", "recommendations_user"),
    ("quest_digital", "recommendations_list"),
    ("quest_digital", "recommendations_category"),
]


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _chain(identity: dict[str, Any], temporal: dict[str, Any], localization: dict[str, Any]) -> dict[str, Any]:
    route = temporal["routes"]["candidate_between_unverified_prior_recommendation_and_linked_consultation"]
    return {
        "candidate_tier": "PATIENT_REPORTED_INTAKE_CANDIDATE",
        "accepted": False,
        "equals_prescription": False,
        "equals_dispense": False,
        "equals_administration": False,
        "equals_verified_ingestion": False,
        "equals_treatment_effect": False,
        "equals_causal_exposure": False,
        "identity_status": identity["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"],
        "temporal_status": temporal["SOURCE_B_TEMPORAL_SEQUENCE_STATUS"],
        "candidate_route": route,
        "source_a_section_codes_profiled": sorted(localization["document_recommendation"]["by_section_code"]),
        "source_a_catalog_transferred_to_source_b": False,
        **SCIENTIFIC_CEILING,
    }


def _report(status: dict[str, Any], localization: dict[str, Any], linkage: dict[str, Any],
            identity: dict[str, Any], temporal: dict[str, Any], sentinels: dict[str, Any]) -> str:
    scopes = localization["document_recommendation"]["scope_comparison"]
    def frac(scope: str, pattern: str) -> Any:
        return scopes[scope]["pattern_fraction_of_non_empty"].get(pattern)
    lines = [
        "# Exposure source discovery v0.2",
        "",
        "Report status: FINAL",
        "",
        "Technical discovery only. Human field meanings stay pending. This is not Stage 05 Gate 1,",
        "not a readiness upgrade, and not an intervention-response cohort.",
        "",
        f"`TECHNICAL_DISCOVERY_STATUS`={status['TECHNICAL_DISCOVERY_STATUS']}",
        f"`SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS`={identity['SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS']}",
        f"`SOURCE_B_TEMPORAL_SEQUENCE_STATUS`={temporal['SOURCE_B_TEMPORAL_SEQUENCE_STATUS']}",
        f"`OWNER_SEMANTIC_REVIEW_STATUS`={status['OWNER_SEMANTIC_REVIEW_STATUS']}",
        f"`PATIENT_REPORTED_INTAKE_TIER_STATUS`={status['PATIENT_REPORTED_INTAKE_TIER_STATUS']}",
        f"`INTERVENTION_RESPONSE_READINESS_STATUS`={status['INTERVENTION_RESPONSE_READINESS_STATUS']}",
        "",
        "## Source A localization",
        "",
        "Pattern fractions below are of non-empty region texts. History and diagnosis text is a control,",
        "not a recommendation.",
        "",
        f"- whole document dose-like: {frac('whole_document', 'dose_like')}",
        f"- recommendations node dose-like: {frac('recommendations_node', 'dose_like')}",
        f"- recommendation items dose-like: {frac('recommendation_items', 'dose_like')}",
        f"- outside recommendations dose-like: {frac('outside_recommendations', 'dose_like')}",
        f"- section codes profiled: {len(localization['document_recommendation']['by_section_code'])}",
        f"- direct medicine-row foreign key to a recommendation document: {linkage['direct_foreign_key_between_medicine_row_and_recommendation_document']}",
        f"- shared visit key on the medicine row: {linkage['shared_appointment_route']}",
        "",
        "Dose-like fraction by section code. This does not decide which code is a medication instruction.",
        "",
    ]
    for code, slot in sorted(localization["document_recommendation"]["by_section_code"].items()):
        dose = slot["pattern_fraction_of_non_empty"].get("dose_like")
        lines.append(f"- `{code}`: documents {slot['documents']}, sections {slot['sections']}, dose-like {dose}")
    history = localization["document_medicalreport"]["regions"]
    lines.extend([
        "",
        f"- medical-report recommendations dose-like: {history['recommendations']['pattern_fraction_of_non_empty'].get('dose_like')}",
        f"- medical-report drugs dose-like: {history['drugs']['pattern_fraction_of_non_empty'].get('dose_like')}",
        f"- medical-report history and diagnosis dose-like: {history['history_and_diagnosis_control']['pattern_fraction_of_non_empty'].get('dose_like')}",
        f"- medicine rows with no recommendation document on the same calendar day: {linkage['patient_windows']['0_day']['medicine_rows_without_candidate']}",
        f"- medicine rows with no recommendation document within 7 days: {linkage['patient_windows']['7_day']['medicine_rows_without_candidate']}",
        "",
        "## Source B",
        "",
        f"- feedback rows: {identity['feedback_rows']}",
        f"- linked consultation disagreements: {identity['linked_subject_disagreements']}",
        f"- linked consultation agreements are not schema proof.",
        f"- feedback before the linked consultation: {temporal['routes']['feedback_before_linked_consultation']['count']}",
        f"- feedback after the linked consultation: {temporal['routes']['feedback_after_linked_consultation']['count']}",
        f"- change_drugs negative/placeholder/empty/null fraction: {sentinels['fill_explanation']['change_drugs']['null_empty_negative_or_placeholder_fraction']}",
        f"- decline_drugs negative/placeholder/empty/null fraction: {sentinels['fill_explanation']['decline_drugs']['null_empty_negative_or_placeholder_fraction']}",
        "",
        "The candidate route from an earlier drug recommendation through feedback to a later consultation",
        "uses an unverified subject equality when identity is not established. It is not a verified exposure.",
        "",
        "Owner questions are in `owner-questions.md`. No external contact was made.",
        "",
    ])
    return "\n".join(lines)


def run(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    before = verify_baseline(root)
    _dump(art / "baseline-verification.json", before)
    if not before["ok"]:
        return {"ok": False, "BASELINE_VERIFICATION_STATUS": "FAIL", "stopped": True}
    limitations = reproduce(root)
    _dump(art / "v01-method-limitations-reproduction.json", limitations)
    entries: list[dict[str, Any]] = []
    conn = connect_a(root)
    try:
        fingerprint_a = schema_fingerprint(conn, A_TABLES)
        log_a = QueryLog(fingerprint_a)
        names = [row[0] for row in log_a.run(conn, "a_catalog_names", "magerya_api", "SELECT name FROM magerya_api.diagnosis_medicines")]
        matcher = CatalogMatcher(names)
        localization = localize(conn, log_a, matcher)
        linkage = structured_linkage(conn, log_a)
        entries.extend(log_a.entries)
        _dump(art / "source-a-recommendation-localization.json", localization)
        _dump(art / "source-a-structured-linkage.json", linkage)
    finally:
        conn.close()
    conn = connect_b(root)
    try:
        fingerprint_b = schema_fingerprint(conn, B_TABLES)
        log_b = QueryLog(fingerprint_b)
        schema = schema_contract(conn, log_b, fingerprint_b)
        sentinels = sentinel_profile(conn, log_b)
        identity = identity_audit(conn, log_b, schema)
        temporal = temporal_audit(conn, log_b, identity["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"])
        entries.extend(log_b.entries)
    finally:
        conn.close()
    chain = _chain(identity, temporal, localization)
    _dump(art / "source-a-recommendation-localization.json", localization)
    _dump(art / "source-a-structured-linkage.json", linkage)
    _dump(art / "source-b-schema-contract.json", schema)
    _dump(art / "source-b-sentinel-profile.json", sentinels)
    _dump(art / "source-b-identity-linkage-audit.json", identity)
    _dump(art / "source-b-temporal-sequence-audit.json", temporal)
    _dump(art / "candidate-exposure-chain.json", chain)
    (art / "owner-questions.md").write_text(questions_markdown(), encoding="utf-8")
    _dump(art / "owner-response-template.json", response_template())
    _dump(art / "semantic-decision.schema.json", decision_schema())
    _dump(art / "query-log.json", {"version": VERSION, "queries": entries})
    import tempfile
    with tempfile.TemporaryDirectory(prefix="uhbse-v02-nc-") as tmp:
        controls = run_negative_controls(Path(tmp))
    _dump(art / "negative-control-results.json", controls)
    queries_ok = all(item.get("success") for item in entries)
    technical = "PASS" if limitations["ok"] and queries_ok and controls["ok"] else "FAIL"
    status = {
        "version": VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "BASELINE_VERIFICATION_STATUS": before["BASELINE_VERIFICATION_STATUS"],
        "TECHNICAL_DISCOVERY_STATUS": technical,
        "SOURCE_A_RECOMMENDATION_LOCALIZATION_STATUS": "COMPUTED_SEMANTICS_UNKNOWN",
        "SOURCE_A_STRUCTURED_LINKAGE_STATUS": linkage["SOURCE_A_STRUCTURED_LINKAGE_STATUS"],
        "SOURCE_B_FEEDBACK_SCHEMA_STATUS": schema["SOURCE_B_FEEDBACK_SCHEMA_STATUS"],
        "SOURCE_B_FEEDBACK_SENTINEL_ACCOUNTING_STATUS": sentinels["SOURCE_B_FEEDBACK_SENTINEL_ACCOUNTING_STATUS"],
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS": identity["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"],
        "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": temporal["SOURCE_B_TEMPORAL_SEQUENCE_STATUS"],
        "SOURCE_B_FEEDBACK_SEMANTICS_STATUS": semantics_status(None),
        "policy": policy_snapshot(),
        **SCIENTIFIC_CEILING,
    }
    (art / "discovery-report.md").write_text(
        _report(status, localization, linkage, identity, temporal, sentinels), encoding="utf-8"
    )
    _dump(art / "status-contract.json", status)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PENDING_SCAN"
    status["NEGATIVE_CONTROL_STATUS"] = controls["NEGATIVE_CONTROL_STATUS"]
    _dump(art / "status-contract.json", status)
    _dump(art / "verification.json", {"ok": False, "note": "rewritten_after_privacy_scan"})
    _write_manifest(art)
    after = verify_baseline(root)
    scan = scan_public(art)
    _dump(art / "privacy-scan.json", scan)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
    _dump(art / "status-contract.json", status)
    missing = [name for name in REQUIRED_ARTIFACTS if name != "verification.json" and not (art / name).is_file()]
    verification = {
        "ok": bool(
            before["ok"] and after["ok"] and scan["ok"] and controls["ok"] and limitations["ok"]
            and queries_ok and not missing and technical == "PASS"
            and status["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
        ),
        "BASELINE_VERIFICATION_STATUS": after["BASELINE_VERIFICATION_STATUS"],
        "baseline_before": before,
        "baseline_after_matches_before": before["files"] == after["files"],
        "TECHNICAL_DISCOVERY_STATUS": technical,
        "PUBLIC_DATA_MINIMIZATION_STATUS": scan["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "NEGATIVE_CONTROL_STATUS": controls["NEGATIVE_CONTROL_STATUS"],
        "missing_artifacts": missing,
        "external_review_zip_created": False,
        "stage_05_bundle_modified": False,
    }
    _dump(art / "verification.json", verification)
    _write_manifest(art)
    final_scan = scan_public(art)
    if not final_scan["ok"]:
        verification["ok"] = False
        verification["PUBLIC_DATA_MINIMIZATION_STATUS"] = final_scan["PUBLIC_DATA_MINIMIZATION_STATUS"]
        _dump(art / "verification.json", verification)
        _dump(art / "privacy-scan.json", final_scan)
        _write_manifest(art)
    return {"ok": verification["ok"], "TECHNICAL_DISCOVERY_STATUS": technical,
            "PUBLIC_DATA_MINIMIZATION_STATUS": scan["PUBLIC_DATA_MINIMIZATION_STATUS"],
            "identity": identity["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"]}


def _write_manifest(art: Path) -> None:
    lines = []
    for path in sorted(art.rglob("*")):
        if not path.is_file() or path.name == "evidence-manifest.sha256":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(art).as_posix()}")
    (art / "evidence-manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(run(Path("."))))
