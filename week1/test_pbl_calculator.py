"""Tests for the periodontal bone loss calculator."""

import math

import pytest

from week1.pbl_calculator import calculate_pbl, classify_pbl, distance


def test_healthy_tooth_has_zero_percent_pbl():
    cej = (0, 10)
    bone_crest = (0, 10)
    root_tip = (0, 0)

    pbl = calculate_pbl(cej, bone_crest, root_tip)

    assert pbl == pytest.approx(0.0)
    assert classify_pbl(pbl) == "Mild"


def test_severe_bone_loss():
    pbl = calculate_pbl((0, 10), (0, 5), (0, 0))

    assert pbl == pytest.approx(50.0)
    assert classify_pbl(pbl) == "Severe"


def test_tilted_tooth_uses_euclidean_distance():
    # The CEJ and bone crest have the same Y coordinate, so a Y-only
    # calculation would incorrectly return 0%. Their Euclidean distance is 6.
    cej = (0, 0)
    bone_crest = (6, 0)
    root_tip = (6, 8)  # Euclidean root length is 10.

    assert distance(cej, root_tip) == pytest.approx(10.0)
    assert calculate_pbl(cej, bone_crest, root_tip) == pytest.approx(60.0)


@pytest.mark.parametrize(
    "pbl, expected",
    [
        (0.0, "Mild"),
        (14.9, "Mild"),
        (15.0, "Moderate"),
        (32.9, "Moderate"),
        (33.0, "Severe"),
        (100.0, "Severe"),
    ],
)
def test_classification_boundaries(pbl, expected):
    assert classify_pbl(pbl) == expected


def test_exactly_15_percent_from_coordinates_is_moderate():
    pbl = calculate_pbl((0, 100), (0, 85), (0, 0))

    assert pbl == pytest.approx(15.0)
    assert classify_pbl(pbl) == "Moderate"


def test_exactly_33_percent_from_coordinates_is_severe():
    pbl = calculate_pbl((0, 100), (0, 67), (0, 0))

    assert pbl == pytest.approx(33.0)
    assert classify_pbl(pbl) == "Severe"


@pytest.mark.parametrize("angle_degrees", [0, 20, 45, -30, 90])
def test_rotated_tooth_gives_same_pbl(angle_degrees):
    angle = math.radians(angle_degrees)

    def rotate(point):
        x, y = point
        return (
            x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle),
        )

    cej = (0, 10)
    bone_crest = (0, 7)
    root_tip = (0, 0)

    assert calculate_pbl(
        rotate(cej), rotate(bone_crest), rotate(root_tip)
    ) == pytest.approx(30.0)


def test_cej_and_root_tip_cannot_be_the_same_point():
    with pytest.raises(ValueError, match="different locations"):
        calculate_pbl((2, 3), (4, 5), (2, 3))


def test_bone_crest_above_cej_is_invalid():
    with pytest.raises(ValueError, match="above the CEJ"):
        calculate_pbl((0, 4), (0, 6), (0, -6))


def test_bone_crest_beyond_root_tip_is_invalid():
    with pytest.raises(ValueError, match="beyond the root tip"):
        calculate_pbl((0, 4), (0, -10), (0, -6))


def test_bone_crest_at_root_tip_is_100_percent():
    pbl = calculate_pbl((2.7, -7.9), (-1.6, 9.6), (-1.6, 9.6))

    assert pbl == pytest.approx(100.0)
