"""CLI — medication acceptance semantics v0.1.3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dispatch_medication_reference_v013(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1.3":
        from human_simulator.medication_reference_v013.orchestrator import (
            run_acceptance_semantics_v013,
        )

        result = run_acceptance_semantics_v013(root)
        print(json.dumps(result["public"], indent=2, ensure_ascii=False, default=str))
        return 0
    if command == "verify-v0.1.3":
        path = (
            root
            / "artifacts/stage-03-medication-acceptance-semantics-v0.1.3"
            / "acceptance-semantics-summary.json"
        )
        if not path.is_file():
            print(json.dumps({"ok": False, "reason": "summary_missing"}))
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0
    print(json.dumps({"ok": False, "reason": f"unknown_command:{command}"}))
    return 2


def dispatch_review_decide(root: Path, args: Any) -> int:
    from human_simulator.medication_reference_v013.review_decide import append_typed_decision

    def _tri(val: Any) -> bool | None:
        if val is None:
            return None
        if val in (True, False):
            return bool(val)
        if str(val).lower() == "true":
            return True
        if str(val).lower() == "false":
            return False
        return None

    try:
        entry = append_typed_decision(
            root,
            source_medicine_id=args.medicine_id,
            decision=args.decision,
            reviewer_id=args.reviewer,
            reason=args.reason,
            evidence_hash=args.evidence_hash,
            candidate_id=getattr(args, "candidate", None),
            provider_neutral_concept_id=getattr(args, "concept", None),
            llm_generated=bool(getattr(args, "llm_generated", False)),
            product_evidence=_tri(getattr(args, "product_evidence", None)),
            ingredient_evidence=_tri(getattr(args, "ingredient_evidence", None)),
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "entry": entry}, indent=2, ensure_ascii=False, default=str))
    return 0
