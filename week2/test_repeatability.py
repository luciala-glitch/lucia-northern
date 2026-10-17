"""Tests for saving and comparing repeatability measurements."""

import pytest

from week2.repeatability import (
    POINT_NAMES,
    make_measurement_row,
    read_measurements,
    save_measurement,
    summarize_repeatability,
)


POINTS = {name: (100, 100 + i * 10) for i, name in enumerate(POINT_NAMES)}


def _row(round_name, pbl, stage, points=POINTS, mesial=None, tooth_id="11"):
    return make_measurement_row(
        observer="Lucia",
        round_name=round_name,
        image_id="xray-1",
        tooth_id=tooth_id,
        image_size=(2041, 1024),
        points=points,
        mesial_pbl=pbl - 1 if mesial is None else mesial,
        distal_pbl=pbl,
        worst_side="Distal",
        worst_pbl=pbl,
        stage=stage,
    )


def test_save_preserves_same_round_measurement_history(tmp_path):
    path = tmp_path / "measurements.csv"
    save_measurement(path, _row("Round 1", 20, "Stage II"))
    save_measurement(path, _row("Round 1", 22, "Stage II"))

    rows = read_measurements(path)
    assert len(rows) == 2
    assert float(rows[-1]["worst_pbl"]) == pytest.approx(22.0)
    assert rows[-1]["supersedes_timestamp_utc"] == rows[0]["timestamp_utc"]
    assert rows[-1]["image_width"] == "2041"


def test_row_keeps_points_in_original_pixels():
    points = dict(POINTS, mesial_cej=(1500.6, 812.2))
    row = _row("Round 1", 20, "Stage II", points=points)
    assert row["mesial_cej_x"] == "1501"
    assert row["mesial_cej_y"] == "812"


def test_row_records_processing_and_version_metadata():
    row = make_measurement_row(
        observer="Lucia", round_name="Round 1", image_id="xray-1",
        tooth_id="11", image_size=(10, 10), points=POINTS,
        mesial_pbl=1, distal_pbl=2, worst_side="Distal", worst_pbl=2,
        stage="Stage I", clahe_enabled=True, app_version="abc1234",
    )

    assert row["clahe_enabled"] == "true"
    assert row["app_version"] == "abc1234"


def test_row_needs_all_points():
    points = dict(POINTS)
    del points["distal_root_tip"]
    with pytest.raises(ValueError, match="distal_root_tip"):
        _row("Round 1", 20, "Stage II", points=points)


@pytest.mark.parametrize("field", ["observer", "tooth_id"])
def test_row_needs_observer_and_tooth(field):
    kwargs = dict(
        observer="Lucia", round_name="Round 1", image_id="xray-1",
        tooth_id="11", image_size=(10, 10), points=POINTS,
        mesial_pbl=1, distal_pbl=2, worst_side="Distal", worst_pbl=2,
        stage="Stage I",
    )
    kwargs[field] = "  "
    with pytest.raises(ValueError, match="required"):
        make_measurement_row(**kwargs)


def test_repeatability_summary_reports_pbl_and_stage_change():
    moved = dict(POINTS, mesial_root_tip=(103, 124))  # 3-4-5 shift
    summary = summarize_repeatability([
        _row("Round 1", 32, "Stage II", mesial=30),
        _row("Round 2", 35, "Stage III/IV", points=moved, mesial=28),
    ])

    assert summary["pair_count"] == 1
    assert summary["mean_absolute_pbl_change"] == pytest.approx(3.0)
    assert summary["max_absolute_pbl_change"] == pytest.approx(3.0)
    assert summary["mean_absolute_mesial_change"] == pytest.approx(2.0)
    assert summary["mean_absolute_distal_change"] == pytest.approx(3.0)
    assert summary["stage_change_count"] == 1
    assert summary["stage_agreement_percent"] == pytest.approx(0.0)
    assert summary["mean_landmark_shift_px"]["mesial_root_tip"] == pytest.approx(5.0)
    assert summary["mean_landmark_shift_px"]["mesial_cej"] == pytest.approx(0.0)


def test_repeatability_summary_reports_bias_limits_and_coefficient():
    summary = summarize_repeatability([
        _row("Round 1", 20, "Stage II", tooth_id="11"),
        _row("Round 2", 22, "Stage II", tooth_id="11"),
        _row("Round 1", 30, "Stage II", tooth_id="12"),
        _row("Round 2", 26, "Stage II", tooth_id="12"),
    ])

    assert summary["mean_signed_pbl_change"] == pytest.approx(-1.0)
    assert summary["pbl_difference_sd"] == pytest.approx(4.242640687)
    assert summary["loa_lower"] == pytest.approx(-9.315575746)
    assert summary["loa_upper"] == pytest.approx(7.315575746)
    assert summary["within_subject_sd"] == pytest.approx(5 ** 0.5)
    assert summary["repeatability_coefficient"] == pytest.approx(2.77 * 5 ** 0.5)


def test_summary_uses_latest_version_of_a_repeated_reading():
    summary = summarize_repeatability([
        _row("Round 1", 20, "Stage II"),
        _row("Round 1", 22, "Stage II"),
        _row("Round 2", 25, "Stage II"),
    ])

    assert summary["pair_count"] == 1
    assert summary["mean_signed_pbl_change"] == pytest.approx(3.0)


def test_unpaired_teeth_are_ignored():
    summary = summarize_repeatability([_row("Round 1", 20, "Stage II")])
    assert summary["pair_count"] == 0
    assert summary["stage_agreement_percent"] == 0.0
