"""Generate a synthetic multi-view image set for a real COLMAP SfM smoke test.

Projects a textured 3D point cloud from several camera poses around the
object. No GPU, no network, deterministic seed — safe to run in CI/dev.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def build_points(rng: np.random.Generator) -> np.ndarray:
    pts: list[np.ndarray] = []
    grid = np.linspace(-1, 1, 9)
    for u in grid:
        for v in grid:
            jitter = rng.normal(0, 0.012, 3)
            for base in ([u, v, 1], [u, v, -1], [u, 1, v],
                         [u, -1, v], [1, u, v], [-1, u, v]):
                pts.append((np.array(base) + jitter).tolist())
    return np.array(pts, dtype=float)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/colmap_poc/images")
    ap.add_argument("--views", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    pts = build_points(rng)
    K = np.array([[500, 0, 320], [0, 500, 240], [0, 0, 1]], dtype=float)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for i, ang in enumerate(np.linspace(0, 2 * np.pi, args.views, endpoint=False)):
        cam = np.array([3.2 * np.cos(ang), 0.6, 3.2 * np.sin(ang)])
        forward = -cam / np.linalg.norm(cam)
        right = np.cross(forward, [0, 1, 0])
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        R = np.vstack([right, up, forward])
        t = (-R @ cam).reshape(3, 1)
        proj = (R @ pts.T + t).T
        z = proj[:, 2]
        uv = (K @ proj.T).T
        uv = uv[:, :2] / z[:, None]
        img = np.full((480, 640, 3), 250, np.uint8)
        for k, (x, y) in enumerate(uv):
            if z[k] > 0 and 8 < x < 632 and 8 < y < 472:
                # Small checkerboard patches give SIFT strong, repeatable
                # corners from every viewpoint (unlike flat colored dots).
                cx, cy = int(x), int(y)
                tone = int(rng.integers(0, 2)) * 255
                cv2.rectangle(img, (cx - 5, cy - 5), (cx + 5, cy + 5),
                              (tone, tone, tone), -1)
                cv2.rectangle(img, (cx - 5, cy - 5), (cx, cy),
                              (255 - tone, 255 - tone, 255 - tone), -1)
                cv2.rectangle(img, (cx, cy), (cx + 5, cy + 5),
                              (255 - tone, 255 - tone, 255 - tone), -1)
                cv2.rectangle(img, (cx - 6, cy - 6), (cx + 6, cy + 6),
                              (0, 0, 0), 1)
        cv2.imwrite(str(out / f"im_{i:02d}.jpg"), img)
    print(f"generated {args.views} views in {out}")


if __name__ == "__main__":
    main()
