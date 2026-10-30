"""Shared, ordered landmark and staging constants."""

from typing import Final

LANDMARK_NAMES: Final[tuple[str, ...]] = (
    "mesial_cej",
    "distal_cej",
    "mesial_bc",
    "distal_bc",
    "apex",
)

STAGE_BOUNDARIES: Final[tuple[float, float]] = (15.0, 33.0)
SEED: Final[int] = 20261027
