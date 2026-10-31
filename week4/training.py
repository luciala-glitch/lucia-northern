"""Deterministic heatmap target creation and label-safe image augmentation."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Mapping

import numpy as np
from PIL import Image, ImageEnhance

from week3.image_processing import preprocess
from week4.constants import LANDMARK_NAMES

Point = tuple[float, float]


@dataclass(frozen=True)
class AugmentedSample:
    image: Image.Image
    points: dict[str, Point]


def augment(
    image: Image.Image,
    points: Mapping[str, Point],
    rng: random.Random,
    *,
    rotation_degrees: float = 15.0,
    scale_jitter: float = 0.08,
    clahe_probability: float = 0.35,
) -> AugmentedSample:
    """Rotate, scale, adjust contrast/brightness, and sometimes apply CLAHE.

    Horizontal flips are intentionally absent because they would require
    swapping mesial/distal labels.
    """
    if set(points) != set(LANDMARK_NAMES):
        raise ValueError("All five named landmarks are required for augmentation")
    working = preprocess(image, "clahe" if rng.random() < clahe_probability else "raw")
    working = ImageEnhance.Brightness(working).enhance(rng.uniform(0.85, 1.15))
    working = ImageEnhance.Contrast(working).enhance(rng.uniform(0.85, 1.15))
    angle = rng.uniform(-rotation_degrees, rotation_degrees)
    scale = rng.uniform(1 - scale_jitter, 1 + scale_jitter)
    width, height = working.size
    center = np.asarray([width / 2, height / 2], dtype=float)
    radians = math.radians(-angle)
    rotation = np.asarray(
        [[math.cos(radians), -math.sin(radians)], [math.sin(radians), math.cos(radians)]]
    )
    transformed = {
        name: tuple((center + scale * (rotation @ (np.asarray(point) - center))).tolist())
        for name, point in points.items()
    }
    # PIL uses inverse mapping. Scaling around the center is expressed through
    # a resized canvas followed by centered crop/pad, then rotation.
    scaled_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    scaled = working.resize(scaled_size, Image.Resampling.BILINEAR)
    canvas = Image.new("L", (width, height), color=int(np.asarray(working).mean()))
    offset = ((width - scaled.width) // 2, (height - scaled.height) // 2)
    canvas.paste(scaled, offset)
    rotated = canvas.rotate(angle, resample=Image.Resampling.BILINEAR, expand=False)
    return AugmentedSample(rotated, transformed)


def gaussian_heatmaps(
    points: Mapping[str, Point],
    size: tuple[int, int],
    *,
    sigma: float = 3.0,
) -> np.ndarray:
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    width, height = size
    if width < 1 or height < 1:
        raise ValueError("heatmap dimensions must be positive")
    yy, xx = np.mgrid[:height, :width]
    maps = []
    for name in LANDMARK_NAMES:
        if name not in points:
            raise ValueError(f"Missing landmark {name}")
        x, y = points[name]
        maps.append(np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2)))
    return np.asarray(maps, dtype=np.float32)


INPUT_SIZE: tuple[int, int] = (160, 320)  # (width, height); teeth are tall
BOX_MARGIN = 0.08


@dataclass(frozen=True)
class CanonicalCrop:
    """Tooth-box crop flipped so the apex is at the bottom and mesial on the left.

    A vertical flip never swaps mesial/distal. A horizontal flip does, so it is
    only applied together with the reader's mesial direction, which keeps the
    ``mesial_*`` names attached to the anatomically mesial surface.
    """

    image: Image.Image
    box: tuple[float, float, float, float]
    flip_x: bool
    flip_y: bool

    def to_local(self, point: Point) -> Point:
        left, top, right, bottom = self.box
        u = (point[0] - left) / (right - left)
        v = (point[1] - top) / (bottom - top)
        u, v = (1 - u if self.flip_x else u), (1 - v if self.flip_y else v)
        return u * self.image.width, v * self.image.height

    def to_original(self, point: Point) -> Point:
        left, top, right, bottom = self.box
        u, v = point[0] / self.image.width, point[1] / self.image.height
        u, v = (1 - u if self.flip_x else u), (1 - v if self.flip_y else v)
        return left + u * (right - left), top + v * (bottom - top)

    def scale_px(self) -> tuple[float, float]:
        left, top, right, bottom = self.box
        return (right - left) / self.image.width, (bottom - top) / self.image.height


def canonical_crop(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    *,
    apex_at_bottom: bool,
    mesial_on_left: bool,
    size: tuple[int, int] = INPUT_SIZE,
    margin: float = BOX_MARGIN,
) -> CanonicalCrop:
    """Crop only the reader-supplied tooth box; ground-truth points are never used."""
    left, top, right, bottom = map(float, bbox)
    if right <= left or bottom <= top:
        raise ValueError("Tooth box must have positive width and height")
    pad_x, pad_y = (right - left) * margin, (bottom - top) * margin
    box = (left - pad_x, top - pad_y, right + pad_x, bottom + pad_y)
    crop = image.convert("L").crop(tuple(round(v) for v in box))
    box = tuple(float(round(v)) for v in box)
    crop = crop.resize(size, Image.Resampling.BILINEAR)
    if not mesial_on_left:
        crop = crop.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if not apex_at_bottom:
        crop = crop.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return CanonicalCrop(crop, box, not mesial_on_left, not apex_at_bottom)  # type: ignore[arg-type]
