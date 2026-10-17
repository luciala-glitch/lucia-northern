"""Tests for single-side and two-side PBL calculations."""

import math

import pytest

from week2.pbl_calculator import (
    calculate_pbl,
    calculate_tooth_pbl,
    classify_pbl,
    distance,
    stage_pbl,
)


def test_healthy_tooth_has_zero_percent_pbl():
    assert calculate_pbl((0, 10), (0, 10), (0, 0)) == pytest.approx(0.0)


def test_severe_bone_loss():
    assert calculate_pbl((0, 10), (0, 5), (0, 0)) == pytest.approx(50.0)


def test_tilted_tooth_uses_euclidean_distance():
    cej = (0, 0)
    bone_crest = (6, 0)
    root_tip = (6, 8)

    assert distance(cej, root_tip) == pytest.approx(10.0)
    assert calculate_pbl(cej, bone_crest, root_tip) == pytest.approx(60.0)


@pytest.mark.parametrize(
    "pbl, expected",
    [
        (0.0, "Mild"),
        (14.9, "Mild"),
        (15.0, "Moderate"),
        (32.9, "Moderate"),
        (33.0, "Moderate"),
        (33.34, "Severe"),
        (100.0, "Severe"),
    ],
)
def test_classification_boundaries(pbl, expected):
    assert classify_pbl(pbl) == expected


@pytest.mark.parametrize("angle_degrees", [0, 20, 45, -30, 90])
def test_rotated_tooth_gives_same_pbl(angle_degrees):
    angle = math.radians(angle_degrees)

    def rotate(point):
        x, y = point
        return (
            x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle),
        )

    assert calculate_pbl(
        rotate((0, 10)), rotate((0, 7)), rotate((0, 0))
    ) == pytest.approx(30.0)


def test_zero_root_length_has_clear_error():
    with pytest.raises(ValueError, match="Zero root length"):
        calculate_pbl((2, 3), (4, 5), (2, 3))


def test_bone_crest_above_cej_is_clamped_to_zero():
    assert calculate_pbl((0, 4), (0, 6), (0, -6)) == pytest.approx(0.0)


def test_bone_crest_past_root_tip_has_clear_error():
    with pytest.raises(ValueError, match="past the root tip"):
        calculate_pbl((0, 4), (0, -10), (0, -6))


@pytest.mark.parametrize("bone_crest", [(5, 9), (20, 9)])
def test_off_axis_crest_cannot_exceed_root_length(bone_crest):
    with pytest.raises(ValueError, match="farther from the CEJ"):
        calculate_pbl((0, 0), bone_crest, (0, 10))


def test_bone_crest_at_root_tip_is_100_percent():
    pbl = calculate_pbl((2.7, -7.9), (-1.6, 9.6), (-1.6, 9.6))
    assert pbl == pytest.approx(100.0)


def test_tooth_uses_worse_distal_side_for_stage():
    result = calculate_tooth_pbl(
        (0, 100), (0, 90), (0, 0),
        (10, 100), (10, 60), (10, 0),
    )

    assert result.mesial_pbl == pytest.approx(10.0)
    assert result.distal_pbl == pytest.approx(40.0)
    assert result.worst_side == "Distal"
    assert result.worst_pbl == pytest.approx(40.0)
    assert result.stage == "Stage III/IV"


def test_tooth_uses_mesial_side_when_it_is_worse():
    result = calculate_tooth_pbl(
        (0, 100), (0, 70), (0, 0),
        (10, 100), (10, 80), (10, 0),
    )

    assert result.worst_side == "Mesial"
    assert result.stage == "Stage II"


def test_equal_sides_report_mesial():
    result = calculate_tooth_pbl(
        (0, 100), (0, 80), (0, 0),
        (10, 100), (10, 80), (10, 0),
    )
    assert result.mesial_pbl == pytest.approx(result.distal_pbl)
    assert result.worst_side == "Mesial"


@pytest.mark.parametrize(
    "pbl, stage",
    [(0, "Stage I"), (14.99, "Stage I"), (15, "Stage II"),
     (33, "Stage II"), (33.34, "Stage III/IV")],
)
def test_stage_boundaries(pbl, stage):
    assert stage_pbl(pbl) == stage


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "20"])
def test_stage_rejects_bad_percentages(bad):
    with pytest.raises(ValueError):
        stage_pbl(bad)


@pytest.mark.parametrize(
    "point",
    [(1, float("nan")), (True, 2), ("1", 2), (1, 2, 3), None],
)
def test_bad_coordinates_raise(point):
    with pytest.raises(ValueError):
        calculate_pbl(point, (0, 5), (0, 0))
