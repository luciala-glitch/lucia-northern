"""Deterministic image degradations for the prespecified robustness study."""

from __future__ import annotations

from typing import Literal

import numpy as np
from PIL import Image, ImageFilter

from week4.constants import SEED

Degradation = Literal["blur", "noise", "resolution"]


def degrade(
    image: Image.Image,
    kind: Degradation,
    level: float,
    *,
    seed: int = SEED,
) -> Image.Image:
    """Apply a degradation while preserving original dimensions and coordinates."""
    gray = image.convert("L")
    if kind == "blur":
        if level not in {1.0, 2.0, 3.0}:
            raise ValueError("Blur sigma must be 1, 2, or 3")
        return gray.filter(ImageFilter.GaussianBlur(radius=level))
    if kind == "noise":
        if level <= 0:
            raise ValueError("Noise standard deviation must be positive")
        array = np.asarray(gray, dtype=np.float32)
        noise = np.random.default_rng(seed).normal(0, level, size=array.shape)
        return Image.fromarray(np.clip(array + noise, 0, 255).astype(np.uint8))
    if kind == "resolution":
        if level not in {0.75, 0.5}:
            raise ValueError("Resolution scale must be 0.75 or 0.5")
        reduced = gray.resize(
            (max(1, round(gray.width * level)), max(1, round(gray.height * level))),
            Image.Resampling.BILINEAR,
        )
        return reduced.resize(gray.size, Image.Resampling.BILINEAR)
    raise ValueError(f"Unknown degradation: {kind}")


def degradation_grid() -> tuple[tuple[Degradation, float], ...]:
    return (
        ("blur", 1.0),
        ("blur", 2.0),
        ("blur", 3.0),
        ("noise", 10.0),
        ("resolution", 0.75),
        ("resolution", 0.5),
    )
