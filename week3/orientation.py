"""Dental-midline suggestion and mesial/distal side guidance in image coordinates.

Mesial means "toward the dental midline", so which image side is mesial depends
on where the tooth lies relative to the midline, not on a fixed image direction.
"""

from __future__ import annotations
from typing import Literal
import numpy as np
from PIL import Image
from week2.image_processing import grayscale_8bit

Side = Literal["left", "right"]
# Panoramic films are wide; periapicals/bitewings rarely contain the midline.
PANORAMIC_ASPECT = 1.6


def estimate_midline(
    image: Image.Image, search: tuple[float, float] = (0.35, 0.65), work: int = 320
) -> tuple[int, float]:
    """Suggest the dental midline of a panoramic film by left-right mirror symmetry.

    Each candidate column is scored by the normalized correlation between the image
    strip on its left (mirrored) and the strip on its right. Returns the best column
    in original pixels and its score (-1..1). This is a suggestion for a person to
    confirm, not anatomical detection: asymmetric positioning, missing teeth or
    pathology move the maximum.
    """
    gray = grayscale_8bit(image)
    width, height = gray.size
    if width < 32 or height < 8:
        raise ValueError("Image too small to estimate a midline")
    work = min(work, width)
    small = np.asarray(
        gray.resize((work, max(8, round(height * work / width)))), dtype=float
    )
    small = (small - small.mean()) / (small.std() or 1.0)
    half = work // 4
    best = (-np.inf, work // 2)
    for c in range(int(work * search[0]), int(work * search[1]) + 1):
        k = min(c, work - c, half)
        left = small[:, c - k : c][:, ::-1]
        right = small[:, c : c + k]
        left, right = left - left.mean(), right - right.mean()
        norm = np.sqrt(np.square(left).sum() * np.square(right).sum())
        score = float((left * right).sum() / norm) if norm else -1.0
        if score > best[0]:
            best = (score, c)
    return min(width - 1, round(best[1] * width / work)), best[0]


def is_panoramic(size: tuple[int, int]) -> bool:
    return size[0] >= PANORAMIC_ASPECT * size[1]


def mesial_side(tooth_x: int, midline_x: int | None) -> Side | None:
    """Image side that faces the midline. Off-image midlines use -1 or the width."""
    if midline_x is None or tooth_x == midline_x:
        return None
    return "right" if tooth_x < midline_x else "left"


def swapped_surfaces(
    points: dict[str, tuple[int, int]], side: Side | None
) -> list[str]:
    """Surfaces whose mesial point lies on the distal side of its distal partner.

    A soft check only: strongly tilted or rotated teeth can legitimately fail it.
    """
    if side is None:
        return []
    sign = 1 if side == "right" else -1
    return [
        landmark
        for landmark in ("cej", "bc")
        if f"mesial.{landmark}" in points
        and f"distal.{landmark}" in points
        and sign * (points[f"mesial.{landmark}"][0] - points[f"distal.{landmark}"][0])
        < 0
    ]
