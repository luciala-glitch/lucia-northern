"""Core calculations for radiographic periodontal bone loss (PBL)."""

from dataclasses import dataclass
import math
import numbers
from typing import Sequence


Point = Sequence[float]


@dataclass(frozen=True)
class ToothPBLResult:
    """PBL results for the two measured surfaces of one tooth."""

    mesial_pbl: float
    distal_pbl: float
    worst_pbl: float
    worst_side: str
    stage: str


def _check_point(point: Point) -> tuple[float, float]:
    """Validate and return one two-dimensional point."""
    if not isinstance(point, (tuple, list)) or len(point) != 2:
        raise ValueError("Each point must be an (x, y) pair")

    x, y = point
    if not all(
        isinstance(value, numbers.Real) and not isinstance(value, bool)
        for value in (x, y)
    ):
        raise ValueError("Point coordinates must be numbers")
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("Point coordinates must be finite numbers")

    return float(x), float(y)


def distance(point1: Point, point2: Point) -> float:
    """Return the Euclidean distance between two 2D points."""
    x1, y1 = _check_point(point1)
    x2, y2 = _check_point(point2)
    return math.hypot(x2 - x1, y2 - y1)


def calculate_pbl(cej: Point, bone_crest: Point, root_tip: Point) -> float:
    """Calculate PBL for one side of a tooth.

    The percentage is the CEJ-to-crest distance divided by root length. A
    crest on the crown side of the CEJ is treated as no radiographic loss and
    returns 0%. A crest whose projection is past the root tip, or whose direct
    distance from the CEJ is longer than the root, is rejected because that
    placement is anatomically invalid and is usually a click error.
    """
    cej_x, cej_y = _check_point(cej)
    crest_x, crest_y = _check_point(bone_crest)
    tip_x, tip_y = _check_point(root_tip)

    axis_x = tip_x - cej_x
    axis_y = tip_y - cej_y
    root_length_squared = axis_x**2 + axis_y**2
    if root_length_squared == 0:
        raise ValueError(
            "Zero root length: CEJ and root tip must be at different locations"
        )

    crest_x_from_cej = crest_x - cej_x
    crest_y_from_cej = crest_y - cej_y
    axial_position = (
        axis_x * crest_x_from_cej + axis_y * crest_y_from_cej
    ) / root_length_squared

    if axial_position <= 0:
        return 0.0
    if axial_position > 1:
        raise ValueError("Bone crest cannot be past the root tip")

    bone_loss_distance = math.hypot(crest_x_from_cej, crest_y_from_cej)
    root_length = math.sqrt(root_length_squared)
    if bone_loss_distance > root_length:
        raise ValueError(
            "Bone crest cannot be farther from the CEJ than the root tip"
        )
    return bone_loss_distance / root_length * 100


def classify_pbl(pbl_percentage: float) -> str:
    """Classify a PBL percentage using the Week 1 project thresholds."""
    if not isinstance(pbl_percentage, numbers.Real) or isinstance(
        pbl_percentage, bool
    ):
        raise ValueError("PBL percentage must be a number")
    if not math.isfinite(pbl_percentage) or pbl_percentage < 0:
        raise ValueError("PBL percentage must be a non-negative finite number")

    if pbl_percentage < 15:
        return "Mild"
    # The AAP/EFP Stage II boundary is the coronal third of the root.
    if pbl_percentage < 100 / 3:
        return "Moderate"
    return "Severe"


def stage_pbl(pbl_percentage: float) -> str:
    """Return the radiographic bone-loss stage supported by PBL alone.

    PBL can separate Stage I, Stage II, and the combined Stage III/IV range.
    Distinguishing Stage III from IV requires complexity and tooth-loss data
    that are outside this point-measurement tool.
    """
    classification = classify_pbl(pbl_percentage)
    return {
        "Mild": "Stage I",
        "Moderate": "Stage II",
        "Severe": "Stage III/IV",
    }[classification]


def calculate_tooth_pbl(
    mesial_cej: Point,
    mesial_bone_crest: Point,
    mesial_root_tip: Point,
    distal_cej: Point,
    distal_bone_crest: Point,
    distal_root_tip: Point,
) -> ToothPBLResult:
    """Calculate both surfaces and stage the tooth from the worse surface."""
    mesial_pbl = calculate_pbl(
        mesial_cej, mesial_bone_crest, mesial_root_tip
    )
    distal_pbl = calculate_pbl(
        distal_cej, distal_bone_crest, distal_root_tip
    )

    # A root tip clicked on the crown side flips that surface's axis, which
    # would otherwise turn a real crest into a silent "above the CEJ" 0%.
    mesial_cej_x, mesial_cej_y = _check_point(mesial_cej)
    mesial_tip_x, mesial_tip_y = _check_point(mesial_root_tip)
    distal_cej_x, distal_cej_y = _check_point(distal_cej)
    distal_tip_x, distal_tip_y = _check_point(distal_root_tip)
    axis_agreement = (
        (mesial_tip_x - mesial_cej_x) * (distal_tip_x - distal_cej_x)
        + (mesial_tip_y - mesial_cej_y) * (distal_tip_y - distal_cej_y)
    )
    if axis_agreement <= 0:
        raise ValueError(
            "Mesial and distal root axes point in opposite directions; "
            "check the root tip placement"
        )

    if mesial_pbl >= distal_pbl:
        worst_pbl = mesial_pbl
        worst_side = "Mesial"
    else:
        worst_pbl = distal_pbl
        worst_side = "Distal"

    return ToothPBLResult(
        mesial_pbl=mesial_pbl,
        distal_pbl=distal_pbl,
        worst_pbl=worst_pbl,
        worst_side=worst_side,
        stage=stage_pbl(worst_pbl),
    )
