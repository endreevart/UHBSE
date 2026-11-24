"""CLI — medication-reference v0.1.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.esklp_ingest import ingest_esklp_snapshot
from human_simulator.medication_reference_v011.orchestrator import run_full
from human_simulator.medication_reference_v011.policy import ARTIFACT_DIR
from human_simulator.medication_reference_v011.publish import publish
from human_simulator.medication_reference_v011.review import (
    append_decision,
    review_export,
    review_list,
    review_show,
    verify_decision_log,
)


def dispatch_medication_reference_v011(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()

    if command == "plan-review-v0.1.1":
        from human_simulator.medication_reference_v011.review_planner import (
            run_domain_review_planner,
        )

        result = run_domain_review_planner(root)
        # Avoid dumping private medication strings
        printable = {
            "ok": result.get("ok"),
            "statuses": result.get("statuses"),
            "auth_before": result.get("auth_before"),
            "auth_after": result.get("auth_after"),
            "n_impacts": result.get("n_impacts"),
            "packet": result.get("packet"),
            "plan_summary": {
                "minimum_for_first_ready_n": (
                    (result.get("plan") or {}).get("minimum_for_first_ready") or {}
                ).get("n_review_decisions"),
                "no_candidate_can_pass_readiness": (result.get("plan") or {}).get(
                    "no_candidate_can_pass_readiness"
                ),
                "n_concepts_capable_of_first_ready": (result.get("plan") or {}).get(
                    "n_concepts_capable_of_first_ready"
                ),
                "three_promising_n_decisions": [
                    s.get("n_review_decisions")
                    for s in (
                        (result.get("plan") or {}).get(
                            "three_most_promising_for_first_ready"
                        )
                        or []
                    )
                ],
            },
        }
        print(json.dumps(printable, indent=2, default=str, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if command == "verify-v0.1.1":
        path = root / ARTIFACT_DIR / "status-contract.json"
        if not path.is_file():
            print(json.dumps({"error": "status-contract.json missing"}, indent=2))
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0

    if command == "publish-v0.1.1":
        out = publish(root)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1

    if command == "import-esklp":
        snap = Path(args.snapshot) if getattr(args, "snapshot", None) else None
        out = ingest_esklp_snapshot(root, snap)
        # strip in-memory index from stdout
        printable = {k: v for k, v in out.items() if k != "index"}
        print(json.dumps(printable, indent=2, default=str, ensure_ascii=False))
        return 0 if out.get("ok") else 1

    if command == "review":
        sub = args.review_command
        if sub == "list":
            top = getattr(args, "top", None)
            rows = review_list(root, top=top)
            print(json.dumps({"n": len(rows), "queue": rows}, indent=2, ensure_ascii=False))
            return 0
        if sub == "show":
            print(json.dumps(review_show(root, args.medicine_id), indent=2, ensure_ascii=False))
            return 0
        if sub == "accept":
            try:
                entry = append_decision(
                    root,
                    source_medicine_id=args.medicine_id,
                    decision="HUMAN_ACCEPTED",
                    reviewer_id=getattr(args, "reviewer", None),
                    reason=getattr(args, "reason", None),
                    provider=getattr(args, "provider", None),
                    provider_concept_id=getattr(args, "candidate", None)
                    or getattr(args, "provider_concept_id", None),
                )
            except ValueError as exc:
                print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
                return 1
            print(json.dumps(entry, indent=2, ensure_ascii=False))
            return 0
        if sub == "reject":
            try:
                entry = append_decision(
                    root,
                    source_medicine_id=args.medicine_id,
                    decision="HUMAN_REJECTED",
                    reviewer_id=getattr(args, "reviewer", None),
                    reason=getattr(args, "reason", None),
                    provider=getattr(args, "provider", None),
                    candidate_id=getattr(args, "candidate", None)
                    or getattr(args, "candidate_id", None),
                )
            except ValueError as exc:
                print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
                return 1
            print(json.dumps(entry, indent=2, ensure_ascii=False))
            return 0
        if sub == "ambiguous":
            try:
                entry = append_decision(
                    root,
                    source_medicine_id=args.medicine_id,
                    decision="AMBIGUOUS",
                    reviewer_id=getattr(args, "reviewer", None),
                    reason=getattr(args, "reason", None),
                    provider=getattr(args, "provider", None),
                )
            except ValueError as exc:
                print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
                return 1
            print(json.dumps(entry, indent=2, ensure_ascii=False))
            return 0
        if sub == "decide":
            from human_simulator.medication_reference_v013.cli import dispatch_review_decide

            return dispatch_review_decide(root, args)
        if sub == "verify-log":
            print(json.dumps(verify_decision_log(root), indent=2))
            return 0
        if sub == "export":
            print(json.dumps(review_export(root), indent=2))
            return 0
        return 2

    return 2
