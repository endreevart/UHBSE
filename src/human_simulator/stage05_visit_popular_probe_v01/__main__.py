"""Run the one-label probe against the stage container."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.stage05_visit_popular_probe_v01.probe import STAGE_SQL, parse_stage_payload

ARTIFACT_DIR = Path("artifacts/stage-05-visit-popular-probe-v0.1")


def _remote_command() -> list[str]:
    host = os.environ.get("STAGE_SSH_HOST", "109.120.181.80")
    user = os.environ.get("STAGE_SSH_USER", "ubuntu")
    container = os.environ.get("STAGE_CONTAINER", "stage-mg-db-1")
    identity = os.environ.get("STAGE_SSH_IDENTITY", str(Path.home() / ".ssh" / "id_ed25519"))
    remote = (
        "sudo -n docker exec -i "
        + container
        + " sh -c 'PGPASSWORD=\"$POSTGRES_PASSWORD\" psql -h 127.0.0.1 "
        + "-U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -v ON_ERROR_STOP=1 -tA'"
    )
    return [
        "ssh",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=40",
        "-i",
        identity,
        f"{user}@{host}",
        remote,
    ]


def run_stage() -> dict:
    completed = subprocess.run(
        _remote_command(),
        input=STAGE_SQL,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return parse_stage_payload(completed.stdout)


def write_artifacts(root: Path, payload: dict) -> None:
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    document = {
        "source": "stage-mg-db-1",
        "definition": "confirmed visit prescription union, most common normalized label",
        **payload,
    }
    (art / "popular-probe.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    label = payload["probe_label"]
    exam = payload["examination"]
    lines = [
        "# Popular prescription probe v0.1",
        "",
        "One normalized label from the confirmed prescription union on the stage container.",
        "The comparison is a change in stored records. It is not an effect. Gate 2 stays closed.",
        "",
        f"Label: {label}",
        f"Visits: {payload['visits']}. Recommendation visits: {payload['recommendation_visits']}. Catalog visits: {payload['catalog_visits']}.",
        f"Labels tied at this visit count: {payload['tie_count']}.",
        f"Consecutive pairs with this label on the previous visit and a doctor questionnaire on the next: {payload['pairs']}.",
        "",
        "Examination text changed:",
    ]
    for code in ("goal", "complaints", "anamnesis", "objective_status", "local_status"):
        row = exam[code]
        lines.append(f"- {code}: {row['text_changed']} changed, {row['same_text']} same text.")
    lines.extend([
        "",
        f"Pairs with the same received analysis on both visits: {payload['shared_lab_pairs']}.",
        f"Stored item values match in {payload['shared_lab_values_unchanged_pairs']} and differ in {payload['shared_lab_values_changed_pairs']}.",
        "Eligible cells stay 0.",
        "",
    ])
    (art / "popular-probe-report.md").write_text("\n".join(lines), encoding="utf-8")
    scan = scan_public(art)
    (art / "privacy-scan.json").write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
    if scan["PUBLIC_DATA_MINIMIZATION_STATUS"] != "PASS_AGGREGATE_ONLY":
        raise SystemExit("privacy scan failed")


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = run_stage()
    write_artifacts(root, payload)
    print(json.dumps({
        "probe_label": payload["probe_label"],
        "visits": payload["visits"],
        "pairs": payload["pairs"],
        "GATE_2_STATUS": "CLOSED",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
