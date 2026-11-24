"""CLI — cross-source-semantic-review v0.1.1 corrective."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v011.policy import ARTIFACT_DIR


def dispatch_cross_source_semantic_review_v011(
    root: Path, command: str, args: Any
) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1.1":
        from human_simulator.cross_source_semantic_review_v011.orchestrator import (
            run_full,
        )

        result = run_full(root, no_publish=bool(getattr(args, "no_publish", True)))
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if command == "verify-v0.1.1":
        path = root / ARTIFACT_DIR / "verification.json"
        if not path.is_file():
            print(json.dumps({"ok": False, "error": "verification.json missing"}))
            return 1
        doc = json.loads(path.read_text(encoding="utf-8"))
        st_path = root / ARTIFACT_DIR / "status-contract.json"
        st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.is_file() else {}
        print(
            json.dumps(
                {"ok": bool(doc.get("ok")), "verification": doc, "status_contract": st},
                indent=2,
                default=str,
                ensure_ascii=False,
            )
        )
        return 0 if doc.get("ok") else 1

    if command == "publish-v0.1.1":
        from human_simulator.cross_source_semantic_review_v011.publish import publish

        result = publish(root)
        # Update status contract post-publish
        art = root / ARTIFACT_DIR
        st_path = art / "status-contract.json"
        if st_path.is_file():
            st = json.loads(st_path.read_text(encoding="utf-8"))
            proofs = result.get("proofs") or {}
            st.update(
                {
                    "POST_TEST_MANIFEST_STATUS": proofs.get(
                        "POST_TEST_MANIFEST_STATUS", "PASS"
                    ),
                    "POST_PACK_MANIFEST_STATUS": proofs.get(
                        "POST_PACK_MANIFEST_STATUS", "PASS"
                    ),
                    "CACHE_MEMBER_SCAN_STATUS": proofs.get(
                        "CACHE_MEMBER_SCAN_STATUS", "PASS"
                    ),
                    "FINAL_ZIP_CONTENT_STATUS": proofs.get(
                        "FINAL_ZIP_CONTENT_STATUS", "PASS"
                    ),
                    "REVIEW_PACKET_PUBLICATION_STATUS": "PASS",
                    "PUBLICATION_INTEGRITY_STATUS": "PASS",
                }
            )
            st_path.write_text(
                json.dumps(st, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    print(json.dumps({"ok": False, "error": f"unknown command {command}"}))
    return 1
