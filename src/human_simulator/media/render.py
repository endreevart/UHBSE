"""Render Remotion compositions from the safe summary."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from human_simulator.media.catalog import EPISODES, fill_caption
from human_simulator.media.paths import media_package, out_dir, summary_path
from human_simulator.media.summarize import write_summary


class MediaRenderError(RuntimeError):
    pass


def _node_cmd(package: Path) -> list[str]:
    binary = package / "node_modules" / ".bin" / "remotion"
    if binary.is_file():
        return [str(binary.resolve())]
    raise MediaRenderError(
        f"Remotion CLI missing. Run npm install in {package}"
    )


def render_media(root: Path, *, stills_only: bool = False) -> dict[str, Any]:
    root = root.resolve()
    summary_file = write_summary(root).resolve()
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    package = media_package(root).resolve()
    dest = out_dir(root).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if not (package / "package.json").is_file():
        raise MediaRenderError(f"missing Remotion package: {package}")
    if not (package / "node_modules").is_dir():
        raise MediaRenderError(
            f"run npm install in {package} before rendering (node_modules missing)"
        )

    env = os.environ.copy()
    env["UHBSE_MEDIA_SUMMARY"] = str(summary_file)
    produced: list[str] = []
    remotion = _node_cmd(package)

    for episode in EPISODES:
        eid = episode["id"]
        episode_dir = dest / eid.lower()
        episode_dir.mkdir(parents=True, exist_ok=True)
        still = episode_dir / "still.png"
        video = episode_dir / "reel.mp4"
        caption = fill_caption(episode["caption"], summary)
        (episode_dir / "caption.txt").write_text(caption + "\n", encoding="utf-8")
        (episode_dir / "title.txt").write_text(episode["title"] + "\n", encoding="utf-8")

        still_cmd = [
            *remotion,
            "still",
            eid,
            str(still),
            f"--props={summary_file}",
            "--frame=120",
        ]
        _run(still_cmd, cwd=package, env=env)
        produced.append(str(still.relative_to(dest)))

        if not stills_only:
            video_cmd = [
                *remotion,
                "render",
                eid,
                str(video),
                f"--props={summary_file}",
                "--codec=h264",
                "--overwrite",
            ]
            _run(video_cmd, cwd=package, env=env)
            produced.append(str(video.relative_to(dest)))

    return {
        "summary": str(summary_file),
        "out_dir": str(dest),
        "episodes": [e["id"] for e in EPISODES],
        "produced": produced,
        "stills_only": stills_only,
        "ffmpeg": shutil.which("ffmpeg") or "bundled-by-remotion",
    }


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(cmd, cwd=str(cwd.resolve()), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-4000:]
        raise MediaRenderError(f"command failed ({result.returncode}): {' '.join(cmd)}\n{tail}")
