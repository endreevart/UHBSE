"""CLI handlers for ``audit media …``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.media.render import MediaRenderError, render_media
from human_simulator.media.series.baseline import SeriesBaselineError
from human_simulator.media.series.pipeline import run_series
from human_simulator.media.series.publish import SeriesPublishError
from human_simulator.media.summarize import MediaSummarizeError, write_summary
from human_simulator.media.verify import verify_media


def _print(doc: Any) -> None:
    print(json.dumps(doc, indent=2, default=str))


def dispatch_media(root: Path, media_command: str, args: Any) -> int:
    try:
        if media_command == "summarize":
            path = write_summary(root)
            _print({"summary": str(path)})
            return 0
        if media_command == "render":
            result = render_media(root, stills_only=bool(getattr(args, "stills_only", False)))
            scan = verify_media(root)
            result["verify"] = scan
            _print(result)
            return 0 if scan["ok"] else 1
        if media_command == "verify":
            scan = verify_media(root)
            _print(scan)
            return 0 if scan["ok"] else 1
        if media_command == "all":
            write_summary(root)
            result = render_media(root, stills_only=bool(getattr(args, "stills_only", False)))
            scan = verify_media(root)
            result["verify"] = scan
            _print(result)
            return 0 if scan["ok"] else 1
        if media_command == "series":
            result = run_series(
                root,
                stills_only=bool(getattr(args, "stills_only", False)),
                skip_render=bool(getattr(args, "skip_render", False)),
                skip_publish=bool(getattr(args, "skip_publish", False)),
            )
            _print(result)
            return 0 if result["verification"]["ok"] else 1
    except (MediaSummarizeError, MediaRenderError, SeriesBaselineError, SeriesPublishError) as exc:
        _print({"error": str(exc)})
        return 1
    _print({"error": f"unknown media command: {media_command}"})
    return 2
