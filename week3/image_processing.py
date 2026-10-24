"""Contrast-only transforms and local bone-crest intensity profiles."""

from __future__ import annotations
import cv2
import numpy as np
from PIL import Image
from week3.pbl_calculator import Point, point
from week2.image_processing import grayscale_8bit


def preprocess(image: Image.Image, condition: str) -> Image.Image:
    pixels = np.asarray(grayscale_8bit(image))
    if condition == "raw":
        return Image.fromarray(pixels.copy())
    if condition == "he":
        return Image.fromarray(cv2.equalizeHist(pixels))
    if condition == "clahe":
        return Image.fromarray(
            cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(pixels)
        )
    raise ValueError("Condition must be raw, he, or clahe")


def coordinate_rmsd(reference: np.ndarray, candidate: np.ndarray) -> float:
    """sqrt(mean(dx^2+dy^2)) in original pixels; requires independent placements."""
    a, b = np.asarray(reference, dtype=float), np.asarray(candidate, dtype=float)
    if a.shape != b.shape or a.ndim != 2 or a.shape[1] != 2 or len(a) == 0:
        raise ValueError("Coordinate arrays must be matching nonempty N-by-2 arrays")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Coordinates must be finite")
    return float(np.sqrt(np.square(a - b).sum(axis=1).mean()))


def crest_profile(
    image: Image.Image, crest: Point, tangent: Point, radius: int = 10
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bilinear 1-pixel samples normal to a locally annotated crest tangent.

    Returns signed offsets, intensities and |dI/ds| (gray levels per pixel).
    Profiles crossing image bounds are rejected, never padded silently.
    """
    center = np.asarray(point(crest))
    direction = np.asarray(point(tangent))
    length = np.linalg.norm(direction)
    if length < 1e-9 or not isinstance(radius, int) or radius < 1:
        raise ValueError("Nonzero tangent and positive integer radius required")
    normal = np.array([-direction[1], direction[0]]) / length
    offsets = np.arange(-radius, radius + 1, dtype=float)
    positions = center + offsets[:, None] * normal
    pixels = np.asarray(grayscale_8bit(image), dtype=np.float32)
    if (
        (positions < 0).any()
        or (positions[:, 0] > pixels.shape[1] - 1).any()
        or (positions[:, 1] > pixels.shape[0] - 1).any()
    ):
        raise ValueError("Crest profile crosses image boundary")
    intensity = cv2.remap(
        pixels,
        positions[:, 0].astype(np.float32)[None, :],
        positions[:, 1].astype(np.float32)[None, :],
        cv2.INTER_LINEAR,
    )[0]
    return offsets, intensity, np.abs(np.gradient(intensity))
