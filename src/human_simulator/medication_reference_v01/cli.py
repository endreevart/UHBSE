"""CLI — medication-reference acquisition + review workbench."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v01.orchestrator import run_full
from human_simulator.medication_reference_v01.policy import ARTIFACT_DIR
from human_simulator.medication_reference_v01.publish import publish
from human_simulator.medication_reference_v01.providers import import_esklp_snapshot
from human_simulator.medication_reference_v01.review import (
    append_decision,
    review_export,
    review_list,
    review_show,
)


def dispatch_medication_reference(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()

    if command == "run-v0.1":
        result = run_full(
            root,
            no_publish=bool(getattr(args, "no_publish", True)),
            allow_network=not bool(getattr(args, "offline", False)),
        )
        print(
            json.dumps(
                {k: v for k, v in result.items() if k != "verification"},
                indent=2,
                default=str,
            )
        )
        return 0 if result.get("ok") else 1

    if command == "verify-v0.1":
        path = root / ARTIFACT_DIR / "verification.json"
        if not path.is_file():
            print(json.dumps({"error": "verification.json missing"}, indent=2))
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0

    if command == "publish-v0.1":
        out = publish(root)
        print(json.dumps(out, indent=2))
        return 0

    if command == "import-esklp":
        out = import_esklp_snapshot(root, Path(args.snapshot))
        print(json.dumps(out, indent=2))
        return 0 if out.get("ESKLP_PROVIDER_STATUS") == "VERIFIED" else 1

    # review workbench
    if command == "review":
        sub = args.review_command
        if sub == "list":
            rows = review_list(root, [])
            print(json.dumps({"n": len(rows), "queue": rows[:100]}, indent=2, ensure_ascii=False))
            return 0
        if sub == "show":
            print(json.dumps(review_show(root, args.medicine_id), indent=2, ensure_ascii=False))
            return 0
        if sub == "accept":
            shown = review_show(root, args.medicine_id)
            entry = append_decision(
                root,
                source_medicine_id=args.medicine_id,
                decision="HUMAN_ACCEPTED",
                source_medication_hash=shown.get("source_text_hash") or "",
                provider_concept_id=args.provider_concept_id,
                provider_evidence_hash=shown.get("provider_evidence_hash"),
                reviewer_id=getattr(args, "reviewer", None) or "local-reviewer",
                reason=getattr(args, "reason", None),
            )
            print(json.dumps(entry, indent=2))
            return 0
        if sub == "reject":
            shown = review_show(root, args.medicine_id)
            entry = append_decision(
                root,
                source_medicine_id=args.medicine_id,
                decision="HUMAN_REJECTED",
                source_medication_hash=shown.get("source_text_hash") or "",
                provider_concept_id=None,
                provider_evidence_hash=shown.get("provider_evidence_hash"),
                reviewer_id=getattr(args, "reviewer", None) or "local-reviewer",
                candidate_id=args.candidate_id,
                reason=getattr(args, "reason", None),
            )
            print(json.dumps(entry, indent=2))
            return 0
        if sub == "ambiguous":
            shown = review_show(root, args.medicine_id)
            entry = append_decision(
                root,
                source_medicine_id=args.medicine_id,
                decision="AMBIGUOUS",
                source_medication_hash=shown.get("source_text_hash") or "",
                provider_concept_id=shown.get("provider_concept_id"),
                provider_evidence_hash=shown.get("provider_evidence_hash"),
                reviewer_id=getattr(args, "reviewer", None) or "local-reviewer",
            )
            print(json.dumps(entry, indent=2))
            return 0
        if sub == "export":
            print(json.dumps(review_export(root), indent=2))
            return 0
        return 2

    return 2
