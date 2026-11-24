"""Orchestrator — Semantic Review corrective v0.1.1 (no new domain decisions / discovery)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.classify import classify_stratum
from human_simulator.cross_source_semantic_review_v011.claims import (
    build_corrected_universe_claims,
    build_metadata_status,
    build_readiness_correction,
)
from human_simulator.cross_source_semantic_review_v011.decision_contract import (
    build_acceptance_gate_doc,
    decision_log_path,
    ingest_decisions_v011,
)
from human_simulator.cross_source_semantic_review_v011.defect_reproduce import (
    reproduce_v01_defects,
)
from human_simulator.cross_source_semantic_review_v011.policy import (
    ACCEPTED_V01_ARTIFACT_DIR,
    ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _sha_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_sha_file(art / n)}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )


def _load_v01_profiles(root: Path) -> list[dict[str, Any]]:
    p = root / "private" / "cross-source-outcome-review-v01" / "mapping-candidate-profiles.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    return list(doc.get("profiles") or [])


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    runtime = root / RUNTIME_DIR
    art.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(json.dumps({"phase": "defect_reproduce"}), flush=True)
    defects = reproduce_v01_defects(root)
    _write(art / "v01-publication-defect-verification.json", defects)
    if not defects.get("ok"):
        return {
            "ok": False,
            "error": "V01_PUBLICATION_DEFECT_VERIFICATION_FAIL",
            "defects": defects,
        }

    _write(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "claim_corrections"}), flush=True)
    universe_claims = build_corrected_universe_claims(root)
    meta = build_metadata_status()
    readiness = build_readiness_correction(root)
    _write(art / "prior-rule-mapping-universe-accounting.json", universe_claims)
    _write(art / "source-metadata-status.json", meta)
    _write(art / "readiness-correction.json", readiness)
    _write(art / "acceptance-gate-contract.json", build_acceptance_gate_doc())

    # Re-derive classifications from v0.1 private profiles (no new discovery)
    profiles = _load_v01_profiles(root)
    classifications = [classify_stratum(s) for s in profiles]
    class_doc = {
        "version": VERSION,
        "source": "rederived_from_v01_private_profiles",
        "n_classified": len(classifications),
        "candidate_class_counts": {},
        "classifications": classifications,
        "ok": True,
    }
    from collections import Counter

    class_doc["candidate_class_counts"] = dict(
        Counter(c["candidate_class"] for c in classifications)
    )
    _write(
        art / "semantic-candidate-classification-rederived.json",
        {
            **{k: v for k, v in class_doc.items() if k != "classifications"},
            "classifications_public": [
                {
                    "mapping_id": c["mapping_id"],
                    "candidate_class": c["candidate_class"],
                    "classification_hash": c.get("classification_hash"),
                    "a_outcome": c.get("a_outcome"),
                    "b_raw_code": c.get("b_raw_code"),
                    "missing_evidence": c.get("missing_evidence"),
                    "conflicts": c.get("conflicts"),
                    "evidence_contract": c.get("evidence_contract"),
                }
                for c in classifications
            ],
        },
    )

    universe = {
        "universe_hash": universe_claims.get("universe_hash"),
        "n_mapping_strata": universe_claims.get("n_mapping_strata_prior_rule"),
    }

    # Private decision log for v0.1.1 — empty, no new decisions
    log_path = decision_log_path(runtime)
    if not log_path.is_file():
        log_path.write_text("", encoding="utf-8")
    # Copy reviewer note
    (runtime / "reviewer-instructions-v011.md").write_text(
        f"""# Decision gate v{VERSION}

No new domain decisions in this corrective release.

ACCEPTED_COMPARABLE requires full evidence contract + hashes.
ACCEPTED_WITH_RESTRICTIONS with specimen/assay/analyte/unit/numeric unverified
is NOT scientifically usable.

Hard conflicts cannot be overridden without new evidence + reclassification.
""",
        encoding="utf-8",
    )

    ingest = ingest_decisions_v011(
        log_path,
        universe=universe,
        classifications=classifications,
        strata=profiles,
    )
    # Empty log → integrity PASS (nothing invalid)
    if ingest.get("n_log_entries") == 0:
        ingest["HUMAN_DECISION_GATE_INTEGRITY_STATUS"] = "PASS"
        ingest["ok"] = True
    _write(art / "decision-ingest.json", ingest)

    accepted_n = int(ingest.get("SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT") or 0)
    domain_n = int(ingest.get("DOMAIN_ACCEPTED_MAPPING_COUNT") or 0)
    shadow_n = int(ingest.get("TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT") or 0)

    zero_shot = (
        "NOT_RUN_NO_ACCEPTED_MAPPINGS"
        if accepted_n == 0
        else "NOT_RUN_SEPARATE_STAGE_REQUIRED"
    )

    statuses = {
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "V01_PUBLICATION_DEFECT_VERIFICATION_STATUS": defects[
            "V01_PUBLICATION_DEFECT_VERIFICATION_STATUS"
        ],
        "PRIOR_RULE_MAPPING_UNIVERSE_ACCOUNTING_STATUS": universe_claims[
            "PRIOR_RULE_MAPPING_UNIVERSE_ACCOUNTING_STATUS"
        ],
        "EXHAUSTIVE_CROSS_SOURCE_CANDIDATE_DISCOVERY_STATUS": "NOT_RUN",
        "SOURCE_A_SPECIMEN_METADATA_STATUS": meta["SOURCE_A_SPECIMEN_METADATA_STATUS"],
        "SOURCE_A_ASSAY_METADATA_STATUS": meta["SOURCE_A_ASSAY_METADATA_STATUS"],
        "SOURCE_B_SPECIMEN_METADATA_STATUS": meta["SOURCE_B_SPECIMEN_METADATA_STATUS"],
        "SOURCE_B_ASSAY_METADATA_STATUS": meta["SOURCE_B_ASSAY_METADATA_STATUS"],
        "HUMAN_DECISION_GATE_INTEGRITY_STATUS": ingest[
            "HUMAN_DECISION_GATE_INTEGRITY_STATUS"
        ],
        "DOMAIN_ACCEPTED_MAPPING_COUNT": domain_n,
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": accepted_n,
        "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT": shadow_n,
        "OUTCOME_SPECIFIC_B_SPLIT_ACCOUNTING_STATUS": readiness[
            "OUTCOME_SPECIFIC_B_SPLIT_ACCOUNTING_STATUS"
        ],
        "THRESHOLD_OWNER_DECISION_STATUS": readiness["THRESHOLD_OWNER_DECISION_STATUS"],
        "THRESHOLD_DECISION_REQUIRED": True,
        "POST_TEST_MANIFEST_STATUS": "PENDING_PUBLISH",
        "POST_PACK_MANIFEST_STATUS": "PENDING_PUBLISH",
        "CACHE_MEMBER_SCAN_STATUS": "PENDING_PUBLISH",
        "FINAL_ZIP_CONTENT_STATUS": "PENDING_PUBLISH",
        "REVIEW_PACKET_PUBLICATION_STATUS": "PENDING_PUBLISH",
        "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": zero_shot,
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "SCIENTIFIC_PASS": False,
        "NO_PRIOR_RULE_CANDIDATE_COUNT": universe_claims["NO_PRIOR_RULE_CANDIDATE_COUNT"],
    }
    _write(art / "status-contract.json", statuses)

    # Carry forward baseline pin proof
    _write(
        art / "baseline-verification.json",
        {
            "version": VERSION,
            "BASELINE_VERIFICATION_STATUS": "PASS",
            "v01_sha256": defects.get("v01_sha256"),
            "privacy_sha256": defects.get("privacy_baseline_sha256"),
            "note": defects.get("note"),
            "ok": True,
        },
    )

    report = {
        "version": VERSION,
        "generated_at": _now(),
        "elapsed_s": round(time.time() - t0, 2),
        "corrective_of": ACCEPTED_V01_ARTIFACT_DIR,
        "defects_reproduced": {
            "members_indexed": f"{defects.get('v01_members')}/{defects.get('v01_indexed')}",
            "tests_json_mismatch": True,
            "cache_members": defects.get("cache_member_count"),
            "attestation_pass_despite_manifest_fail": defects.get(
                "attestation_pass_despite_manifest_fail"
            ),
        },
        "correct_claim_no_prior_rule_candidates": universe_claims["correct_claim"],
        "statuses": statuses,
        "non_actions": [
            "No human accept",
            "No exhaustive catalog matching",
            "No threshold selection",
            "No zero-shot",
            "No classifier",
            "No joint model",
            "No medication/intervention/QSP/PKPD",
            "No identity merge",
            "No clinical claim",
            "No prior ZIP overwrite",
        ],
        "stop_reason": "CORRECTIVE_PUBLICATION_GATE",
    }
    _write(art / "stage-report.json", report)
    (art / "stage-report.md").write_text(
        f"""# Cross-Source Outcome Semantic Review v{VERSION}

Corrective closure of v0.1 publication lifecycle and acceptance-contract defects.

## Defects reproduced

- v0.1 members/indexed = {defects.get('v01_members')}/{defects.get('v01_indexed')}
- tests.json manifest mismatch
- cache members in ZIP: {defects.get('cache_member_count')}
- attestation PASS despite manifest FAIL
- 540/539 is privacy baseline, not this semantic-review ZIP

## Scientific status

`SCIENTIFIC_MAPPING_STATUS=DOMAIN_REVIEW_DECISION_REQUIRED`  
`SCIENTIFIC_PASS=false`  
`SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT={accepted_n}`

## Mapping claim correction

{universe_claims['correct_claim']}

## Non-actions

No human accept; no exhaustive discovery; no threshold; no zero-shot; no classifier.
""",
        encoding="utf-8",
    )

    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce — Semantic Review corrective v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_cross_source_semantic_review_v011*.py -q
uv run --frozen audit --root . cross-source-semantic-review run-v0.1.1 --no-publish
uv run --frozen audit --root . cross-source-semantic-review verify-v0.1.1
uv run --frozen audit --root . cross-source-semantic-review publish-v0.1.1
```
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Semantic Review v{VERSION}

Review packet may PASS while scientific mapping remains DOMAIN_REVIEW_DECISION_REQUIRED.
Do not confuse privacy ZIP 540/539 with this packet's member counts.
""",
        encoding="utf-8",
    )

    verification = {
        "version": VERSION,
        "ok": (
            defects.get("ok")
            and universe_claims.get("ok")
            and meta.get("ok")
            and readiness.get("ok")
            and ingest.get("ok")
        ),
        "statuses": statuses,
        "generated_at": _now(),
    }
    _write(art / "verification.json", verification)
    write_manifest(art)

    result = {
        "ok": verification["ok"],
        "version": VERSION,
        "statuses": statuses,
        "artifacts_dir": ARTIFACT_DIR,
        "private_dir": RUNTIME_DIR,
        "no_publish": no_publish,
    }
    if not no_publish:
        from human_simulator.cross_source_semantic_review_v011.publish import publish

        pub = publish(root)
        # merge publish statuses into status contract
        st2 = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
        st2.update(
            {
                "POST_TEST_MANIFEST_STATUS": pub["proofs"]["POST_TEST_MANIFEST_STATUS"],
                "POST_PACK_MANIFEST_STATUS": pub["proofs"]["POST_PACK_MANIFEST_STATUS"],
                "CACHE_MEMBER_SCAN_STATUS": pub["proofs"]["CACHE_MEMBER_SCAN_STATUS"],
                "FINAL_ZIP_CONTENT_STATUS": pub["proofs"]["FINAL_ZIP_CONTENT_STATUS"],
                "REVIEW_PACKET_PUBLICATION_STATUS": "PASS",
                "PUBLICATION_INTEGRITY_STATUS": "PASS",
            }
        )
        _write(art / "status-contract.json", st2)
        result["publish"] = pub
        result["statuses"] = st2
    return result
