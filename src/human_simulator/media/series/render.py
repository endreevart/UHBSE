"""Render series episodes through the existing Remotion CLI. No second pipeline."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from human_simulator.media.render import MediaRenderError, _node_cmd, _run
from human_simulator.media.paths import media_package
from human_simulator.media.series.constants import (
    EPISODES,
    FPS,
    PROXY_HEIGHT,
    PROXY_WIDTH,
    PUBLIC_MEDIA_DIR,
)


def _ffmpeg_spec(root: Path) -> tuple[str, Path | None]:
    found = shutil.which("ffmpeg")
    if found:
        return found, None
    bundled = media_package(root) / "node_modules" / "@remotion" / "compositor-darwin-arm64" / "ffmpeg"
    if bundled.is_file():
        return str(bundled.resolve()), bundled.parent.resolve()
    raise MediaRenderError("ffmpeg is required for contact sheets and proxies")


def _ff(cmd: list[str], *, cwd: Path | None) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-3000:]
        raise MediaRenderError(f"ffmpeg failed ({result.returncode}): {' '.join(cmd)}\n{tail}")


def generate_voiceover(
    root: Path,
    episode_dir: Path,
    lang: str,
    *,
    ffmpeg: str,
    ffmpeg_cwd: Path | None,
) -> Path | None:
    script = (episode_dir / f"voiceover.{lang}.txt").read_text(encoding="utf-8").strip()
    say = shutil.which("say")
    if not say:
        return None
    wav = episode_dir / f"voiceover.{lang}.wav"
    voice = "Samantha" if lang == "en" else "Milena"
    voices = subprocess.run([say, "-v", "?"], capture_output=True, text=True)
    available = voices.stdout or ""
    if lang == "ru" and "Milena" not in available:
        for candidate in ("Yuri", "Katya"):
            if candidate in available:
                voice = candidate
                break
        else:
            return None
    if lang == "en" and "Samantha" not in available:
        voice = "Alex" if "Alex" in available else "Samantha"
    result = subprocess.run(
        [say, "-v", voice, "-r", "165", "-o", str(wav), "--data-format=LEI16@22050", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not wav.is_file():
        return None
    return wav


def _mux(video: Path, audio: Path, dest: Path, *, ffmpeg: str, ffmpeg_cwd: Path | None) -> None:
    _ff(
        [ffmpeg, "-y", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-shortest", str(dest)],
        cwd=ffmpeg_cwd,
    )


def _write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
    )


def _unfilter_png_row(filter_type: int, row: bytes, prev: bytes, bpp: int) -> bytes:
    out = bytearray(len(row))
    for i, value in enumerate(row):
        left = out[i - bpp] if i >= bpp else 0
        up = prev[i] if prev else 0
        corner = out[i - bpp] if prev and i >= bpp else 0
        if filter_type == 1:
            value = (value + left) & 255
        elif filter_type == 2:
            value = (value + up) & 255
        elif filter_type == 3:
            value = (value + ((left + up) // 2)) & 255
        elif filter_type == 4:
            estimate = left + up - corner
            pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
            nearest = left if pa <= pb and pa <= pc else up if pb <= pc else corner
            value = (value + nearest) & 255
        out[i] = value
    return bytes(out)


def _read_png_rgb(path: Path) -> tuple[int, int, bytes]:
    import struct
    import zlib

    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MediaRenderError(f"not a png: {path.name}")
    pos = 8
    width = height = 0
    color_type = 2
    idat = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, _bit, color_type, *_rest = struct.unpack(">IIBBBBB", chunk)
        elif tag == b"IDAT":
            idat += chunk
        elif tag == b"IEND":
            break
    raw = zlib.decompress(idat)
    bpp = 4 if color_type == 6 else 3
    stride = width * bpp
    rgb = bytearray()
    prev = b""
    i = 0
    for _y in range(height):
        filt = raw[i]
        row = _unfilter_png_row(filt, raw[i + 1 : i + 1 + stride], prev, bpp)
        prev = row
        i += 1 + stride
        if color_type == 6:
            rgb.extend(b"".join(row[p : p + 3] for p in range(0, stride, 4)))
        else:
            rgb.extend(row)
    return width, height, bytes(rgb)


def _contact_sheet(video: Path, dest: Path, *, ffmpeg: str, ffmpeg_cwd: Path | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.parent / f".{dest.stem}-frames"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    _ff(
        [ffmpeg, "-y", "-i", str(video), "-vf", "scale=135:240", "-r", "1", str(work / "f_%03d.png")],
        cwd=ffmpeg_cwd,
    )
    frames = sorted(work.glob("f_*.png"))
    if not frames:
        raise MediaRenderError(f"no contact frames from {video.name}")
    cols = 8
    width, height, first = _read_png_rgb(frames[0])
    rows = max(1, (len(frames) + cols - 1) // cols)
    canvas = bytearray(width * cols * height * rows * 3)
    for index, frame in enumerate(frames):
        _w, _h, rgb = _read_png_rgb(frame)
        col = index % cols
        row = index // cols
        for y in range(height):
            src = y * width * 3
            dst = ((row * height + y) * (width * cols) + col * width) * 3
            canvas[dst : dst + width * 3] = rgb[src : src + width * 3]
    _write_png(dest, width * cols, height * rows, bytes(canvas))
    shutil.rmtree(work, ignore_errors=True)


def _proxy(video: Path, dest: Path, *, ffmpeg: str, ffmpeg_cwd: Path | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _ff(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video),
            "-vf",
            f"scale={PROXY_WIDTH}:{PROXY_HEIGHT}",
            "-c:v",
            "libx264",
            "-crf",
            "28",
            "-preset",
            "veryfast",
            "-an",
            str(dest),
        ],
        cwd=ffmpeg_cwd,
    )


def render_series(root: Path, fixture: dict[str, Any], *, stills_only: bool = False) -> dict[str, Any]:
    root = root.resolve()
    package = media_package(root).resolve()
    dest = (root / PUBLIC_MEDIA_DIR).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    props = dest / "fixture.json"
    props.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    remotion = _node_cmd(package)
    env = os.environ.copy()
    ffmpeg, ffmpeg_cwd = _ffmpeg_spec(root)
    produced: list[str] = []
    frames: dict[str, Any] = {}
    by_id = {episode["id"]: episode for episode in fixture["episodes"]}

    for spec in EPISODES:
        eid = str(spec["id"])
        episode = by_id[eid]
        slug = str(episode["slug"])
        episode_dir = dest / slug
        episode_dir.mkdir(parents=True, exist_ok=True)
        cover = episode_dir / "cover.png"
        master = episode_dir / str(spec["filename"])
        still_cmd = [
            *remotion,
            "still",
            eid,
            str(cover),
            f"--props={props}",
            "--frame=42",
        ]
        _run(still_cmd, cwd=package, env=env)
        produced.append(str(cover.relative_to(dest)))
        duration = int(episode["duration_frames"])
        frames[eid] = {
            "duration_frames": duration,
            "duration_seconds": round(duration / FPS, 3),
            "cover_frame": 42,
        }
        if stills_only:
            continue
        silent = episode_dir / "silent.mp4"
        video_cmd = [
            *remotion,
            "render",
            eid,
            str(silent),
            f"--props={props}",
            "--codec=h264",
            "--overwrite",
        ]
        _run(video_cmd, cwd=package, env=env)
        silent.replace(master)
        produced.append(str(master.relative_to(dest)))
        sheet = dest / "contact-sheets" / f"{slug}.png"
        _contact_sheet(master, sheet, ffmpeg=ffmpeg, ffmpeg_cwd=ffmpeg_cwd)
        produced.append(str(sheet.relative_to(dest)))
        proxy = dest / "proxies" / f"{slug}-720x1280.mp4"
        _proxy(master, proxy, ffmpeg=ffmpeg, ffmpeg_cwd=ffmpeg_cwd)
        produced.append(str(proxy.relative_to(dest)))

    manifest = {
        "out_dir": str(dest),
        "produced": produced,
        "stills_only": stills_only,
        "ffmpeg": ffmpeg,
        "frames": frames,
    }
    (dest / "render-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
