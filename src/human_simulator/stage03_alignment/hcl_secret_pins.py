"""Comment-aware Vault Agent HCL secret version-pin validation."""

from __future__ import annotations

import re
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"

HMAC_PIN = 'with secret "uhbse/data/canonical/hmac-subject-key?version=1"'
LOADER_PIN = 'with secret "uhbse/data/canonical/loader-credential?version=1"'


def strip_hcl_and_template_comments(text: str) -> str:
    """Remove HCL and consul-template comments so comment-only pins cannot PASS."""
    # Block comments /* ... */ including template {{- /* ... */ -}}
    text = re.sub(r"\{\{-\s*/\*.*?\*/\s*-\}\}", " ", text, flags=re.DOTALL)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    # Line comments // and #
    lines: list[str] = []
    for line in text.splitlines():
        if "//" in line:
            line = line.split("//", 1)[0]
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def validate_version_pins(hcl_text: str) -> dict[str, str]:
    active = strip_hcl_and_template_comments(hcl_text)
    # Collapse whitespace for matching with secret expressions
    compact = re.sub(r"\s+", " ", active)

    checks: dict[str, str] = {}
    checks["hmac_version_pin_active"] = PASS if HMAC_PIN in compact else FAIL
    checks["loader_version_pin_active"] = PASS if LOADER_PIN in compact else FAIL

    # Forbidden forms in active (non-comment) text
    if re.search(
        r'with secret "uhbse/data/canonical/hmac-subject-key\?(version=latest|version=current)"',
        compact,
    ):
        checks["hmac_forbidden_version"] = FAIL
    else:
        checks["hmac_forbidden_version"] = PASS

    if re.search(
        r'with secret "uhbse/data/canonical/loader-credential\?(version=latest|version=current)"',
        compact,
    ):
        checks["loader_forbidden_version"] = FAIL
    else:
        checks["loader_forbidden_version"] = PASS

    # Unpinned path present without ?version=1
    if re.search(
        r'with secret "uhbse/data/canonical/hmac-subject-key"', compact
    ) and HMAC_PIN not in compact:
        checks["hmac_unpinned_forbidden"] = FAIL
    else:
        checks["hmac_unpinned_forbidden"] = PASS

    if re.search(
        r'with secret "uhbse/data/canonical/loader-credential"', compact
    ) and LOADER_PIN not in compact:
        checks["loader_unpinned_forbidden"] = FAIL
    else:
        checks["loader_unpinned_forbidden"] = PASS

    overall = PASS if all(v == PASS for v in checks.values()) else FAIL
    checks["overall"] = overall
    return checks


def validate_agent_hcl_file(path: Path, *, display_path: str | None = None) -> dict[str, object]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    checks = validate_version_pins(text)
    overall = checks.pop("overall")
    rel = display_path or "ops/vault/runtime/vault-agent.hcl"
    return {
        "kind": "STATIC",
        "path": rel.replace("\\", "/"),
        "checks": checks,
        "overall_status": overall,
        "note": "Comments and documentation strings are ignored; only active template expressions count",
    }
