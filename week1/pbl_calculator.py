"""Functions for calculating periodontal bone loss."""

import math
import numbers


def _check_point(point):
    """Check that a point contains two valid numbers."""
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

    return x, y


def distance(point1, point2):
    """Return the Euclidean distance between two 2D points."""
    x1, y1 = _check_point(point1)
    x2, y2 = _check_point(point2)

    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def calculate_pbl(cej, bone_crest, root_tip):
    """Calculate periodontal bone loss as a percentage of root length."""
    root_length = distance(cej, root_tip)
    if root_length == 0:
        raise ValueError("CEJ and root tip must be at different locations")

    bone_loss_distance = distance(cej, bone_crest)

    # Check the bone crest's position along the long axis of the tooth.
    axis_x = root_tip[0] - cej[0]
    axis_y = root_tip[1] - cej[1]
    bone_x = bone_crest[0] - cej[0]
    bone_y = bone_crest[1] - cej[1]
    position = (axis_x * bone_x + axis_y * bone_y) / (
        axis_x**2 + axis_y**2
    )

    if position < 0:
        raise ValueError("Bone crest is above the CEJ")
    if position > 1:
        raise ValueError("Bone crest is beyond the root tip")

    return bone_loss_distance / root_length * 100


def classify_pbl(pbl_percentage):
    """Classify a PBL percentage as Mild, Moderate, or Severe."""
    if not isinstance(pbl_percentage, numbers.Real) or isinstance(
        pbl_percentage, bool
    ):
        raise ValueError("PBL percentage must be a number")
    if not math.isfinite(pbl_percentage) or pbl_percentage < 0:
        raise ValueError("PBL percentage must be a non-negative finite number")

    if pbl_percentage < 15:
        return "Mild"
    if pbl_percentage < 33:
        return "Moderate"
    return "Severe"
