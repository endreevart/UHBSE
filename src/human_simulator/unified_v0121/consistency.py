"""Cross-artifact status consistency checks."""

from __future__ import annotations

from typing import Any


CONFLICT_PAIRS = (
    ("INSUFFICIENT_DATA", "BUILT"),
    ("PENDING_PUBLISH", "PASS"),
)


def _collect_status_values(doc: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in doc.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if k.endswith("_status") or k in (
            "status",
            "clinical_validation_status",
            "production_readiness",
            "security_stage_status",
        ):
            if isinstance(v, str):
                out[key] = v
        elif isinstance(v, dict):
            out.update(_collect_status_values(v, key))
    return out


def detect_insufficient_vs_built(statuses: dict[str, str]) -> list[str]:
    """Flag same conceptual field claiming both INSUFFICIENT_DATA and BUILT."""
    conflicts = []
    # Direct contradictions across report surfaces for pair construction / catalog
    vals = set(statuses.values())
    if "INSUFFICIENT_DATA" in vals and "BUILT" in vals:
        # Only conflict if both appear for the same logical key family
        built_keys = {k for k, v in statuses.items() if v == "BUILT"}
        insuff_keys = {k for k, v in statuses.items() if v == "INSUFFICIENT_DATA"}
        for bk in built_keys:
            stem = bk.rsplit(".", 1)[-1]
            for ik in insuff_keys:
                if ik.rsplit(".", 1)[-1] == stem:
                    conflicts.append(f"{stem}: INSUFFICIENT_DATA vs BUILT")
    return conflicts


def detect_pending_publish_in_final(verification: dict[str, Any]) -> bool:
    """After publish updates, PENDING_PUBLISH must not remain."""
    blob = str(verification)
    return "PENDING_PUBLISH" in blob


def assert_report_consistency(
    *,
    report_md_statuses: dict[str, str],
    report_json: dict[str, Any],
    verification: dict[str, Any],
    release_verification: dict[str, Any],
    published: bool = False,
) -> dict[str, Any]:
    """Assert key statuses agree across report.md / report.json / verification surfaces."""
    rj = _collect_status_values(report_json)
    ver = _collect_status_values(verification)
    rel = _collect_status_values(release_verification)

    keys = set(report_md_statuses) | set(rj) | set(ver)
    mismatches: list[str] = []
    for k in sorted(keys):
        vals = set()
        if k in report_md_statuses:
            vals.add(report_md_statuses[k])
        if k in rj:
            vals.add(rj[k])
        if k in ver:
            vals.add(ver[k])
        if len(vals) > 1:
            mismatches.append(f"{k}: {sorted(vals)}")

    insuff_conflicts = detect_insufficient_vs_built({**rj, **ver, **report_md_statuses})
    pending = detect_pending_publish_in_final(verification) if published else False
    # Also check release
    if published and detect_pending_publish_in_final(release_verification):
        pending = True

    ok = not mismatches and not insuff_conflicts and not pending
    return {
        "ok": ok,
        "mismatches": mismatches,
        "insufficient_vs_built_conflicts": insuff_conflicts,
        "pending_publish_in_final": pending,
        "release_keys_checked": sorted(rel.keys())[:20],
    }


def statuses_from_verification(verification: dict[str, Any]) -> dict[str, str]:
    return {
        k: str(v)
        for k, v in verification.items()
        if isinstance(v, str) and (k.endswith("_status") or k in ("production_readiness",))
    }
