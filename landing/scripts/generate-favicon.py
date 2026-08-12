#!/usr/bin/env python3
"""Generate raster favicon assets from the trajectory-fan mark."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

BG = (27, 27, 27, 255)
TRUNK_A = (98, 138, 209, 255)
TRUNK_B = (168, 195, 238, 255)
BRANCHES = [
    ((127, 163, 222, 255), 10.0, 2.4),
    ((168, 195, 238, 235), 18.0, 2.0),
    ((121, 168, 156, 255), 33.0, 2.1),
    ((201, 146, 111, 242), 46.0, 1.9),
]
FORK = (22 / 64, 22.5 / 64)
TRUNK_TOP = (13 / 64, 27.5 / 64)
TRUNK_BOTTOM = (13 / 64, 49 / 64)
FORK_XY = (22 / 64, 22.5 / 64)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 24,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def to_px(points: list[tuple[float, float]], size: int) -> list[tuple[float, float]]:
    return [(x * size, y * size) for x, y in points]


def draw_branch(
    draw: ImageDraw.ImageDraw,
    size: int,
    end_y: float,
    color: tuple[int, int, int, int],
    width: float,
) -> None:
    p0 = FORK_XY
    p3 = (51 / 64, end_y / 64)
    p1 = (lerp(p0[0], p3[0], 0.42), lerp(p0[1], p3[1], 0.18))
    p2 = (lerp(p0[0], p3[0], 0.72), lerp(p0[1], p3[1], 0.72))
    pts = to_px(cubic_bezier(p0, p1, p2, p3), size)
    draw.line(pts, fill=color, width=max(1, round(size * width / 64)), joint="curve")


def draw_mark(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = max(2, round(size * 0.172))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=BG)

    glow_r = size * 0.24
    glow_box = (
        size * 0.12,
        size * 0.08,
        size * 0.12 + glow_r * 2,
        size * 0.08 + glow_r * 2,
    )
    draw.ellipse(glow_box, fill=(127, 163, 222, 42))

    tick = max(1, round(size * 0.017))
    draw.line((size * 0.14, size * 0.14, size * 0.14, size * 0.11), fill=(255, 255, 255, 46), width=tick)
    draw.line((size * 0.14, size * 0.11, size * 0.11, size * 0.11), fill=(255, 255, 255, 46), width=tick)
    draw.line((size * 0.86, size * 0.86, size * 0.86, size * 0.89), fill=(255, 255, 255, 46), width=tick)
    draw.line((size * 0.86, size * 0.89, size * 0.89, size * 0.89), fill=(255, 255, 255, 46), width=tick)

    trunk_w = max(2, round(size * 0.047))
    trunk_pts = to_px([TRUNK_BOTTOM, (13 / 64, 27.5 / 64), FORK_XY], size)
    draw.line(trunk_pts[:2], fill=TRUNK_A, width=trunk_w, joint="curve")
    draw.line(trunk_pts[1:], fill=TRUNK_B, width=trunk_w, joint="curve")

    fork_x, fork_y = FORK_XY[0] * size, FORK_XY[1] * size
    draw.ellipse(
        (fork_x - size * 0.05, fork_y - size * 0.05, fork_x + size * 0.05, fork_y + size * 0.05),
        fill=(127, 163, 222, 56),
    )
    dot = max(1, round(size * 0.023))
    draw.ellipse((fork_x - dot, fork_y - dot, fork_x + dot, fork_y + dot), fill=(211, 231, 255, 255))

    for color, end_y, width in BRANCHES:
        draw_branch(draw, size, end_y, color, width)
        end_x = 51 / 64 * size
        end_py = end_y / 64 * size
        r = max(1, round(size * 0.021))
        draw.ellipse((end_x - r, end_py - r, end_x + r, end_py + r), fill=color)

    return img


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)

    for name, size in {"favicon-32.png": 32, "apple-touch-icon.png": 180}.items():
        draw_mark(size).save(PUBLIC / name)

    ico_sizes = [16, 32, 48]
    ico_images = [draw_mark(s) for s in ico_sizes]
    ico_images[0].save(
        PUBLIC / "favicon.ico",
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=ico_images[1:],
    )


if __name__ == "__main__":
    main()
