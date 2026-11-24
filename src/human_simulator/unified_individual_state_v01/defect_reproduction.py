"""Reproduce accepted v0.3.1 evidence defects (do not rewrite v0.3.1 ZIP)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_individual_state_v01.policy import (
    ACCEPTED_V031_ARTIFACT_DIR,
    VERSION,
)


def reproduce_v031_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ACCEPTED_V031_ARTIFACT_DIR
    acc = json.loads((art / "exact-multi-domain-accounting.json").read_text(encoding="utf-8"))
    split = json.loads(
        (art / "cross-source-overlap-and-split.json").read_text(encoding="utf-8")
    )
    mat = json.loads((art / "materialization-status.json").read_text(encoding="utf-8"))
    stage_report = (art / "stage-report.md").read_text(encoding="utf-8")
    tests = art / "tests.json"
    tests_doc = json.loads(tests.read_text(encoding="utf-8")) if tests.is_file() else {}

    grains = acc.get("grains") or {}
    rec = grains.get("recommendation_patient_events") or {}
    docs = grains.get("document_references_b") or {}
    proc = grains.get("procedures_a") or {}
    events = grains.get("events") or {}

    incomplete_accounting = {
        "confirmed": rec.get("eligible") is None
        and docs.get("eligible") is None
        and proc.get("eligible") == proc.get("materialized")
        and events.get("eligible") == events.get("materialized"),
        "recommendation_eligible": rec.get("eligible"),
        "document_eligible": docs.get("eligible"),
        "procedure_tautological": proc.get("eligible") == proc.get("materialized"),
        "events_tautological": events.get("eligible") == events.get("materialized"),
        "unaccounted_zero_does_not_prove_full_coverage": acc.get("UNACCOUNTED_COUNT") == 0,
        "identity_equation_excludes_these_domains": True,
    }

    # Document gap — note live recount required in accounting module
    docs_mat = (mat.get("datasets") or {}).get("research_document_reference", {}).get("rows")
    document_gap = {
        "confirmed": docs_mat is not None and docs.get("eligible") is None,
        "v031_materialized_documents": docs_mat,
        "eligible_was_null": docs.get("eligible") is None,
        "note": "Live public.documents COUNT(*) must be recomputed; gap decomposed in v0.1 accounting",
    }

    # Provenance subject linkage
    proof = json.loads((art / "domain-materialization-proof.json").read_text(encoding="utf-8"))
    # Check private parquet if present
    prov_path = root / "private/unified-research-layer-v031/materialized/research_provenance.parquet"
    null_subjects = None
    if prov_path.is_file():
        import pyarrow.parquet as pq

        t = pq.read_table(prov_path, columns=["source_scoped_subject_id"])
        vals = t["source_scoped_subject_id"].to_pylist()
        null_subjects = sum(1 for v in vals if v is None)
    provenance_gap = {
        "confirmed": null_subjects is not None
        and null_subjects > 0
        and null_subjects == len(vals),
        "null_source_scoped_subject_id_count": null_subjects,
        "cannot_treat_as_individual_state_features": True,
    }

    overlap = split.get("overlap_groups_summary") or {}
    overlap_gap = {
        "confirmed": split.get("overlap_aware") is False
        and overlap.get("pair_lists_materialized_private") is False,
        "overlap_aware": split.get("overlap_aware"),
        "pair_lists_materialized_private": overlap.get("pair_lists_materialized_private"),
        "independent_source_assignment_risk": True,
    }

    # stage-report.md JSON-encoded
    report_defect = stage_report.lstrip().startswith('"') and "\\n" in stage_report[:200]
    # tests: clean extraction had skip
    out_tail = str(tests_doc.get("output_tail") or "")
    pub_tests = {
        "confirmed": report_defect
        or ("skipped" in out_tail.lower())
        or ("1 skipped" in out_tail),
        "stage_report_json_encoded_string": report_defect,
        "stage_report_prefix": stage_report[:60],
        "tests_output_mentions_skip": "skipped" in out_tail.lower() or "1 skipped" in out_tail,
        "note": "Clean extraction: private parquet contract skipped; not equal to 14 passed",
    }

    defects = {
        "1_incomplete_exact_accounting": incomplete_accounting,
        "2_document_gap_eligible_null": document_gap,
        "3_provenance_subject_linkage_gap": provenance_gap,
        "4_overlap_split_gap": overlap_gap,
        "5_publication_report_defects": pub_tests,
    }
    all_ok = all(d.get("confirmed") for d in defects.values())
    return {
        "version": VERSION,
        "baseline_zip": "stage-03-unified-a-b-materialized-research-layer-v0.3.1-review.zip",
        "V031_EVIDENCE_DEFECT_REPRODUCTION_STATUS": "PASS" if all_ok else "FAIL",
        "defects": defects,
        "all_defects_confirmed": all_ok,
        "ok": all_ok,
        "do_not_rewrite_v031_zip": True,
    }
