"""Re-classify Source B artifacts from an existing schema profile."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.classify.entities import classify_clinical_entities
from human_simulator.stage02.settings import KgzRestoreSettings

CONTENT_ARTIFACTS: tuple[str, ...] = (
    "schema-profile-kgz.json",
    "entity-candidates-kgz.yaml",
    "relation-graph-kgz.md",
    "unknown-semantics-kgz.md",
)

MANIFEST_ARTIFACTS: tuple[str, ...] = (
    *CONTENT_ARTIFACTS,
    "source-b-audit.json",
)

MANIFEST_NAME = "manifest.sha256"

STAGE02_ARTIFACTS: tuple[str, ...] = (
    *MANIFEST_ARTIFACTS,
    MANIFEST_NAME,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(artifacts_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    lines: list[str] = []
    for name in MANIFEST_ARTIFACTS:
        path = artifacts_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Missing artifact for manifest: {path}")
        digest = _sha256_file(path)
        hashes[name] = digest
        lines.append(f"{digest}  {name}")
    manifest_path = artifacts_dir / MANIFEST_NAME
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashes


def verify_manifest(artifacts_dir: Path) -> tuple[bool, str]:
    manifest_path = artifacts_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return False, f"missing {MANIFEST_NAME}"

    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.strip()
        path = artifacts_dir / name
        if not path.exists():
            return False, f"manifest entry missing file: {name}"
        if _sha256_file(path) != digest:
            return False, f"hash mismatch: {name}"
    return True, f"verified {len(MANIFEST_ARTIFACTS)} entries in {MANIFEST_NAME}"


def _entity_assignments(result: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
    grouped: dict[tuple[str, str], set[str]] = {}
    for entity_type, items in result.get("entity_types", {}).items():
        for item in items:
            key = (item["schema"], item["relation"])
            grouped.setdefault(key, set()).add(entity_type)
    return grouped


def _role_for(result: dict[str, Any], schema: str, relation: str) -> str:
    for item in result.get("table_roles", []):
        if item["schema"] == schema and item["relation"] == relation:
            return item["role"]
    raise KeyError(f"{schema}.{relation}")


def run_classification_regression_checks(result: dict[str, Any]) -> list[dict[str, Any]]:
    assignments = _entity_assignments(result)
    checks: list[dict[str, Any]] = []

    def _check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    consultations_entities = assignments.get(("public", "consultations"), set())
    _check(
        "consultations_not_patients_or_doctors",
        not consultations_entities.intersection({"patients", "doctors"}),
        f"consultations entity types: {sorted(consultations_entities) or 'none'}",
    )
    _check(
        "consultations_is_event_candidate",
        "visits" in consultations_entities or "appointments" in consultations_entities,
        f"consultations entity types: {sorted(consultations_entities) or 'none'}",
    )

    for relation in ("feedback", "questionnaire"):
        doctor_hit = "doctors" in assignments.get(("public", relation), set())
        _check(
            f"{relation}_not_doctors",
            not doctor_hit,
            f"{relation} classified as doctors={doctor_hit}",
        )

    for relation in ("feedback", "questionnaire", "users_rating", "consultation_service_changes"):
        visits_hit = "visits" in assignments.get(("public", relation), set())
        _check(
            f"{relation}_not_visits",
            not visits_hit,
            f"{relation} classified as visits={visits_hit}",
        )

    payment_ops = "operations" in assignments.get(("public", "payment_transactions"), set())
    _check(
        "payment_transactions_not_operations",
        not payment_ops,
        f"payment_transactions classified as operations={payment_ops}",
    )

    persons_docs = "medical_documents" in assignments.get(("public", "persons"), set())
    _check(
        "persons_not_medical_documents",
        not persons_docs,
        f"persons classified as medical_documents={persons_docs}",
    )

    lab_false_positives = (
        "analyses_codes",
        "catalog_labs",
        "lab_addresses",
        "lab_referral",
        "lab_referral_codes",
        "lab_referral_regions",
    )
    for relation in lab_false_positives:
        lab_hit = "laboratory_results" in assignments.get(("quest_digital", relation), set())
        _check(
            f"{relation}_not_laboratory_results",
            not lab_hit,
            f"{relation} classified as laboratory_results={lab_hit}",
        )

    constructor_hit = "laboratory_results" in assignments.get(
        ("quest_digital", "analyses_constructor"), set()
    )
    _check(
        "analyses_constructor_is_laboratory_results_candidate",
        constructor_hit,
        f"analyses_constructor laboratory_results={constructor_hit}",
    )

    profile_hit = "measurements" in assignments.get(("public", "profilaxys_profile"), set())
    _check(
        "profilaxys_profile_is_measurements_candidate",
        profile_hit,
        f"profilaxys_profile measurements={profile_hit}",
    )

    profilaxys_role = _role_for(result, "public", "profilaxys_analyses")
    profilaxys_entities = assignments.get(("public", "profilaxys_analyses"), set())
    _check(
        "profilaxys_analyses_not_laboratory_results",
        "laboratory_results" not in profilaxys_entities,
        f"entity_types={sorted(profilaxys_entities)}",
    )
    _check(
        "profilaxys_analyses_is_measurements_candidate",
        "measurements" in profilaxys_entities,
        f"entity_types={sorted(profilaxys_entities)}",
    )

    pool_role = _role_for(result, "quest_digital", "analyses_pool")
    pool_lab = "laboratory_results" in assignments.get(("quest_digital", "analyses_pool"), set())
    _check(
        "analyses_pool_is_workflow_not_laboratory_results",
        pool_role == "WORKFLOW" and not pool_lab,
        f"role={pool_role}, laboratory_results={pool_lab}",
    )

    constructor = assignments.get(("quest_digital", "analyses_constructor"), set())
    _check(
        "analyses_constructor_observation_value_lab_candidate",
        "laboratory_results" in constructor,
        f"entity_types={sorted(constructor)}",
    )

    lab_result_items = [
        item
        for item in result.get("entity_types", {}).get("laboratory_results", [])
        if item["schema"] == "quest_digital" and item["relation"] == "lab_result"
    ]
    _check(
        "lab_result_payload_with_empty_snapshot_note",
        bool(lab_result_items)
        and lab_result_items[0].get("data_level") == "PAYLOAD"
        and any(ev.get("type") == "snapshot_note" for ev in lab_result_items[0].get("evidence", [])),
        f"lab_result candidate={bool(lab_result_items)}",
    )

    _check(
        "profilaxys_analyses_is_observation_candidate",
        profilaxys_role == "OBSERVATION" and bool(profilaxys_entities),
        f"role={profilaxys_role}, entity_types={sorted(profilaxys_entities)}",
    )

    infra_names = {(item["schema"], item["relation"]) for item in result.get("infrastructure_inventory", [])}
    _check(
        "spatial_ref_sys_in_infrastructure",
        ("public", "spatial_ref_sys") in infra_names,
        f"spatial_ref_sys in infrastructure={('public', 'spatial_ref_sys') in infra_names}",
    )

    unknown_with_reference = [
        item for item in result.get("unknown_relations", []) if item.get("role") != "UNCLASSIFIED"
    ]
    _check(
        "unknown_relations_are_unclassified",
        not unknown_with_reference,
        f"non-UNCLASSIFIED in unknown: {[item['relation'] for item in unknown_with_reference[:5]]}",
    )

    no_confirmed = all(
        item.get("status") != "CONFIRMED"
        for items in result.get("entity_types", {}).values()
        for item in items
    )
    _check(
        "no_confirmed_from_heuristics",
        no_confirmed,
        "all entity candidates must be CANDIDATE or lower",
    )

    infra_count = len(result.get("infrastructure_inventory", []))
    _check(
        "infrastructure_separated",
        infra_count >= 30,
        f"infrastructure_inventory relations={infra_count}",
    )

    return checks


def build_source_b_audit(
    repo_root: Path,
    classify_result: dict[str, Any],
    *,
    profile_path: Path,
) -> dict[str, Any]:
    kgz = KgzRestoreSettings.from_repo(repo_root)
    artifacts_dir = repo_root / "artifacts" / "stage-02"
    regression_checks = run_classification_regression_checks(classify_result)

    artifact_hashes: dict[str, str] = {}
    for name in CONTENT_ARTIFACTS:
        path = artifacts_dir / name
        if path.exists():
            artifact_hashes[name] = _sha256_file(path)

    checks: list[dict[str, Any]] = [
        {
            "name": "readonly_user",
            "status": "PASS" if kgz.audit_user == "kgz_audit_ro" else "FAIL",
            "detail": f"connection_user={kgz.audit_user}",
        },
        {
            "name": "schema_profile_present",
            "status": "PASS" if profile_path.exists() else "FAIL",
            "detail": str(profile_path),
        },
        *regression_checks,
        {
            "name": "artifact_hashes",
            "status": "PASS" if len(artifact_hashes) == len(CONTENT_ARTIFACTS) else "FAIL",
            "detail": f"hashed {len(artifact_hashes)}/{len(CONTENT_ARTIFACTS)} content artifacts",
        },
        {
            "name": "audit_not_self_hashed",
            "status": "PASS",
            "detail": "source-b-audit.json excluded from artifact_hashes; see manifest.sha256",
        },
    ]

    failed = [check for check in checks if check["status"] == "FAIL"]
    status = "PASS" if not failed else "FAIL"

    return {
        "profiled_at": classify_result.get("profiled_at"),
        "classified_at": classify_result.get("classified_at"),
        "source_id": "kgz",
        "status": status,
        "dump_path": str(kgz.dump_absolute),
        "database": kgz.pg_database,
        "connection_user": kgz.audit_user,
        "redacted_url": kgz.audit_redacted_url,
        "readonly_user_only": True,
        "application_schemas": classify_result.get("application_schemas", []),
        "checks": checks,
        "artifact_hashes": artifact_hashes,
        "manifest": MANIFEST_NAME,
        "summary": {
            "entity_candidates": sum(len(v) for v in classify_result.get("entity_types", {}).values()),
            "unknown_relations": len(classify_result.get("unknown_relations", [])),
            "infrastructure_relations": len(classify_result.get("infrastructure_inventory", [])),
            "table_roles": len(classify_result.get("table_roles", [])),
        },
    }


def _rename_stage02_artifacts(artifacts_dir: Path) -> None:
    mapping = {
        "entity-candidates.yaml": "entity-candidates-kgz.yaml",
        "relation-graph.md": "relation-graph-kgz.md",
        "unknown-semantics.md": "unknown-semantics-kgz.md",
    }
    for src_name, dst_name in mapping.items():
        src = artifacts_dir / src_name
        dst = artifacts_dir / dst_name
        if src.exists():
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))


def finalize_source_b_audit(repo_root: Path, source_audit: dict[str, Any]) -> dict[str, Any]:
    artifacts_dir = repo_root / "artifacts" / "stage-02"
    audit_path = artifacts_dir / "source-b-audit.json"
    audit_path.write_text(json.dumps(source_audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_manifest(artifacts_dir)

    manifest_ok, manifest_detail = verify_manifest(artifacts_dir)
    source_audit["checks"].append(
        {
            "name": "manifest_sha256",
            "status": "PASS" if manifest_ok else "FAIL",
            "detail": manifest_detail,
        }
    )
    source_audit["status"] = (
        "PASS"
        if all(check["status"] == "PASS" for check in source_audit["checks"])
        else "FAIL"
    )

    audit_path.write_text(json.dumps(source_audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_manifest(artifacts_dir)
    return source_audit


def reclassify_second_source(repo_root: Path) -> dict[str, Any]:
    artifacts_dir = repo_root / "artifacts" / "stage-02"
    profile_path = artifacts_dir / "schema-profile-kgz.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"Missing schema profile: {profile_path}")

    with profile_path.open(encoding="utf-8") as handle:
        schema_profile = json.load(handle)

    classify_result = classify_clinical_entities(schema_profile, artifacts_dir)
    _rename_stage02_artifacts(artifacts_dir)

    profiled_at = schema_profile.get("profiled_at")
    classify_result["profiled_at"] = profiled_at

    source_audit = build_source_b_audit(
        repo_root,
        classify_result,
        profile_path=profile_path,
    )
    if not source_audit.get("profiled_at"):
        source_audit["profiled_at"] = datetime.now(UTC).isoformat()

    source_audit = finalize_source_b_audit(repo_root, source_audit)

    return {
        "source_id": "kgz",
        "status": source_audit["status"],
        "classified_at": classify_result["classified_at"],
        "entity_candidates": source_audit["summary"]["entity_candidates"],
        "checks_passed": sum(1 for check in source_audit["checks"] if check["status"] == "PASS"),
        "checks_total": len(source_audit["checks"]),
        "artifacts": [str(artifacts_dir / name) for name in STAGE02_ARTIFACTS],
    }
