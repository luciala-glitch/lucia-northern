from dataclasses import replace
import math
import pytest
from week3.pbl_calculator import (
    SideLandmarks,
    ToothLandmarks,
    calculate_tooth_pbl,
    stage_pbl,
    point,
    CoordinateError,
    PBLValidationError,
    BoneCrestBoundsError,
    DegenerateGeometryError,
    AnatomicalPlausibilityWarning,
)


def tooth(mbc=(40, 40), dbc=(60, 50), apex=(50, 120), crown=None):
    return ToothLandmarks(
        SideLandmarks((40, 20), mbc), SideLandmarks((60, 20), dbc), apex, crown
    )


def test_hand_calculated_projection_and_worse_side():
    result = calculate_tooth_pbl(tooth(mbc=(200, 30)))
    assert result.long_axis_vector == (0, 1)
    assert result.mesial.defect_px == 10
    assert result.mesial.root_px == 100
    assert result.mesial.pbl_pct == 10
    assert result.distal.pbl_pct == 30
    assert result.pbl_max_pct == 30
    assert result.stage == "II"
    assert not result.review_complexity
    assert result.root_to_crown_ratio is None
    assert not result.warnings
    assert calculate_tooth_pbl(tooth(mbc=(40, 60))).review_complexity


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "I"),
        (14.999, "I"),
        (15, "II"),
        (33, "II"),
        (33.00001, "III/IV"),
        (100, "III/IV"),
    ],
)
def test_stage_boundaries(value, expected):
    assert stage_pbl(value) == expected


@pytest.mark.parametrize(
    "value", [-1, 101, float("nan"), float("inf"), "15", None, True]
)
def test_bad_stage(value):
    with pytest.raises(PBLValidationError):
        stage_pbl(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        (1,),
        [1, 2, 3],
        ["1", 2],
        (True, 2),
        (float("nan"), 2),
        (float("inf"), 2),
        [1, complex(1, 1)],
    ],
)
def test_bad_points(value):
    with pytest.raises(CoordinateError):
        point(value)


def test_point_normalization_and_type_check():
    assert point([1, 2]) == (1.0, 2.0)
    with pytest.raises(PBLValidationError):
        ToothLandmarks(None, SideLandmarks((1, 2), (2, 3)), (4, 5))


@pytest.mark.parametrize("bc", [(40, 19), (40, 121)])
def test_signed_crest_bounds(bc):
    with pytest.raises(BoneCrestBoundsError):
        calculate_tooth_pbl(tooth(mbc=bc))


@pytest.mark.parametrize(
    "bc,expected",
    [
        ((40, 20), 0),
        ((40, 120), 100),
        ((400, 20), 0),
        ((40, 20 - 1e-10), 0),
        ((40, 120 + 1e-10), 100),
    ],
)
def test_axial_bounds_and_floating_tolerance(bc, expected):
    assert calculate_tooth_pbl(tooth(mbc=bc)).mesial.pbl_pct == expected


def test_degenerate_axis_and_projected_side_root():
    with pytest.raises(DegenerateGeometryError):
        calculate_tooth_pbl(tooth(apex=(50, 20)))
    # Midpoint->apex axis exists, but one CEJ lies exactly at its apex axial level.
    bad = ToothLandmarks(
        SideLandmarks((0, 10), (0, 10)), SideLandmarks((0, -10), (0, -8)), (0, 10)
    )
    with pytest.raises(DegenerateGeometryError):
        calculate_tooth_pbl(bad)
    bad = replace(bad, apex=(0, 5))
    with pytest.raises(DegenerateGeometryError):
        calculate_tooth_pbl(bad)


@pytest.mark.parametrize(
    "crown,ratio", [((50, -20), 2.5), ((50, -80), 1), ((50, -30), 2)]
)
def test_plausible_crown(crown, ratio):
    result = calculate_tooth_pbl(tooth(crown=crown))
    assert result.root_to_crown_ratio == ratio
    assert result.warnings == ()


@pytest.mark.parametrize("crown", [(50, 0), (50, -200)])
def test_ratio_warning(crown):
    with pytest.warns(AnatomicalPlausibilityWarning):
        result = calculate_tooth_pbl(tooth(crown=crown))
    assert len(result.warnings) == 1


@pytest.mark.parametrize("crown", [(50, 20), (50, 21)])
def test_bad_crown(crown):
    with pytest.raises(DegenerateGeometryError):
        calculate_tooth_pbl(tooth(crown=crown))


def test_rotation_translation_and_uniform_scale_invariance():
    original = tooth()

    def transform(p):
        angle = 0.7
        scale = 2.8
        return (
            scale * (p[0] * math.cos(angle) - p[1] * math.sin(angle)) + 17,
            scale * (p[0] * math.sin(angle) + p[1] * math.cos(angle)) - 31,
        )

    lm = ToothLandmarks(
        SideLandmarks(transform(original.mesial.cej), transform(original.mesial.bc)),
        SideLandmarks(transform(original.distal.cej), transform(original.distal.bc)),
        transform(original.apex),
    )
    assert calculate_tooth_pbl(lm).pbl_max_pct == pytest.approx(30)


def test_collinear_points_are_valid_with_nonzero_root():
    lm = ToothLandmarks(
        SideLandmarks((0, 0), (0, 15)), SideLandmarks((0, 0), (0, 33)), (0, 100)
    )
    assert calculate_tooth_pbl(lm).stage == "II"


def test_tilted_axis_exact_boundary_is_not_lost_to_float_error():
    # Axis (1, 3): exact 15% is computed as 14.999999999999996 before staging.
    lm = ToothLandmarks(
        SideLandmarks((7, 11), (10, 20)), SideLandmarks((13, 9), (13, 9)), (30, 70)
    )
    result = calculate_tooth_pbl(lm)
    assert result.mesial.pbl_pct == pytest.approx(15)
    assert result.stage == "II"
    assert stage_pbl(33.0000000000001) == "II"
