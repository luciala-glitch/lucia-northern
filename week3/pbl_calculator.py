"""Typed, signed long-axis geometry. Coordinates and lengths use image pixels."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Literal
import warnings

Point = tuple[float, float]
Stage = Literal["I", "II", "III/IV"]
EPS = 1e-9


class PBLValidationError(ValueError):
    """Invalid input or anatomically inconsistent geometry."""


class CoordinateError(PBLValidationError):
    """Coordinates must be finite two-dimensional numeric points."""


class DegenerateGeometryError(PBLValidationError):
    """A required axis or projected root/crown length is zero."""


class BoneCrestBoundsError(PBLValidationError):
    """The crest's signed axial position lies outside CEJ to apex."""


class AnatomicalPlausibilityWarning(UserWarning):
    """Optional crown measurement suggests an implausible root/crown ratio."""


def point(value: object) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CoordinateError("Expected an (x, y) pair")
    if any(isinstance(v, bool) or not isinstance(v, Real) for v in value):
        raise CoordinateError("Coordinates must be real numbers")
    if not all(math.isfinite(v) for v in value):
        raise CoordinateError("Coordinates must be finite")
    return float(value[0]), float(value[1])


def sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


@dataclass(frozen=True)
class SideLandmarks:
    cej: Point
    bc: Point

    def __post_init__(self) -> None:
        object.__setattr__(self, "cej", point(self.cej))
        object.__setattr__(self, "bc", point(self.bc))


@dataclass(frozen=True)
class ToothLandmarks:
    mesial: SideLandmarks
    distal: SideLandmarks
    apex: Point
    crown: Point | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mesial, SideLandmarks) or not isinstance(
            self.distal, SideLandmarks
        ):
            raise PBLValidationError("Both sides must be SideLandmarks")
        object.__setattr__(self, "apex", point(self.apex))
        if self.crown is not None:
            object.__setattr__(self, "crown", point(self.crown))

    @property
    def mid_cej(self) -> Point:
        return (
            (self.mesial.cej[0] + self.distal.cej[0]) / 2,
            (self.mesial.cej[1] + self.distal.cej[1]) / 2,
        )


@dataclass(frozen=True)
class SideResult:
    defect_px: float
    root_px: float
    pbl_pct: float


@dataclass(frozen=True)
class ToothResult:
    long_axis_vector: Point
    mesial: SideResult
    distal: SideResult
    pbl_max_pct: float
    stage: Stage
    review_complexity: bool
    root_to_crown_ratio: float | None
    warnings: tuple[str, ...]


def stage_pbl(value: float) -> Stage:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or not 0 <= value <= 100
    ):
        raise PBLValidationError("PBL must be finite and between 0 and 100")
    # Projection on a tilted axis can turn an exact 15% into 14.999999999999996.
    value = round(float(value), 9)
    if value < 15:
        return "I"
    if value <= 33:
        return "II"
    return "III/IV"


def long_axis(landmarks: ToothLandmarks) -> Point:
    delta = sub(landmarks.apex, landmarks.mid_cej)
    length = math.hypot(*delta)
    if length <= EPS:
        raise DegenerateGeometryError(
            "Apex overlaps the CEJ midpoint: undefined long axis"
        )
    return delta[0] / length, delta[1] / length


def _side(side: SideLandmarks, apex: Point, axis: Point) -> SideResult:
    root = dot(sub(apex, side.cej), axis)
    if root <= EPS:
        raise DegenerateGeometryError(
            "Projected root length must be positive on both sides"
        )
    defect = dot(sub(side.bc, side.cej), axis)
    # Check signed distances BEFORE absolute values, which would hide invalid clicks.
    if defect < -EPS or defect > root + EPS:
        raise BoneCrestBoundsError(
            "Bone crest must project between its CEJ and the apex"
        )
    defect = min(root, max(0.0, defect))
    return SideResult(defect, root, defect / root * 100)


def calculate_tooth_pbl(landmarks: ToothLandmarks) -> ToothResult:
    axis = long_axis(landmarks)
    mesial = _side(landmarks.mesial, landmarks.apex, axis)
    distal = _side(landmarks.distal, landmarks.apex, axis)
    worst = max(mesial.pbl_pct, distal.pbl_pct)
    stage = stage_pbl(worst)
    ratio = None
    messages: list[str] = []
    if landmarks.crown is not None:
        crown_length = -dot(sub(landmarks.crown, landmarks.mid_cej), axis)
        if crown_length <= EPS:
            raise DegenerateGeometryError(
                "Crown must project coronally from the CEJ midpoint"
            )
        ratio = dot(sub(landmarks.apex, landmarks.mid_cej), axis) / crown_length
        if ratio < 1.0 or ratio > 2.5:
            message = (
                f"Root-to-crown ratio {ratio:.3f} outside assignment bounds [1.0, 2.5]"
            )
            warnings.warn(message, AnatomicalPlausibilityWarning, stacklevel=2)
            messages.append(message)
    return ToothResult(
        axis, mesial, distal, worst, stage, stage == "III/IV", ratio, tuple(messages)
    )
