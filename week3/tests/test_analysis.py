import numpy as np
import pytest
from PIL import Image
from week3.statistics import icc_2_1, quadratic_kappa, agreement, paired_array
from week3.image_processing import preprocess, coordinate_rmsd, crest_profile
from week3.sensitivity import sensitivity
from week3.tests.test_engine import tooth


def test_icc_independent_anova_reference():
    # Hand-derived MS_subject=4.5, MS_round=6, MS_error=.5.
    assert icc_2_1([[1, 2], [2, 4], [3, 6]]) == pytest.approx(6 / 13)
    assert icc_2_1([[1, 1], [2, 2], [3, 3]]) == pytest.approx(1)
    assert icc_2_1([[1, 1], [1, 1]]) is None
    assert icc_2_1([[1, 3], [2, 2], [3, 1]]) < 0


def test_kappa_hand_reference():
    # Observed weighted disagreement=1/4; expected=5/4 => kappa=.8.
    assert quadratic_kappa([0, 1, 2], [0, 2, 2]) == pytest.approx(0.8)
    assert quadratic_kappa([0, 1, 2], [0, 1, 2]) == 1
    assert quadratic_kappa([2, 2], [2, 2]) is None
    assert quadratic_kappa([0, 0], [2, 2]) == 0
    with pytest.raises(ValueError):
        quadratic_kappa([0, 3], [0, 1])


def test_bland_altman_difference_sign_and_sample_sd():
    result = agreement([10, 20, 30], [11, 23, 35], [0, 1, 1], [0, 1, 2])
    assert result.bias == 3
    assert result.difference_sd == 2
    assert result.loa_lower == pytest.approx(3 - 1.96 * 2)
    assert result.loa_upper == pytest.approx(3 + 1.96 * 2)
    assert result.difference_mean_slope == pytest.approx(2 / 11)
    assert not result.outside_indices
    out = agreement([1] * 19 + [1], [1] * 19 + [100], [0] * 20, [0] * 20)
    assert out.outside_indices == (19,)
    assert agreement([1, 1], [2, 2], [0, 0], [0, 0]).difference_mean_slope is None


@pytest.mark.parametrize(
    "a,b", [([1], [2]), ([1, 2], [2]), ([1, np.nan], [2, 3]), ([[1, 2]], [[1, 2]])]
)
def test_bad_pairs(a, b):
    with pytest.raises(ValueError):
        paired_array(a, b)


@pytest.mark.parametrize(
    "values", [[[1, 2]], [[1], [2]], [[1, np.nan], [2, 3]], [1, 2]]
)
def test_bad_icc(values):
    with pytest.raises(ValueError):
        icc_2_1(values)


def test_stage_alignment():
    with pytest.raises(ValueError):
        agreement([1, 2], [2, 3], [0], [0, 1])


def test_contrast_preserves_shape_and_raw_pixels():
    pixels = np.arange(400, dtype=np.uint8).reshape(20, 20)
    image = Image.fromarray(pixels)
    for condition in ("raw", "he", "clahe"):
        result = preprocess(image, condition)
        assert result.size == image.size
        assert result.mode == "L"
    np.testing.assert_array_equal(np.asarray(preprocess(image, "raw")), pixels)
    with pytest.raises(ValueError):
        preprocess(image, "invalid")


def test_rmsd_and_normal_crest_profile():
    assert coordinate_rmsd([[0, 0], [1, 1]], [[3, 4], [4, 5]]) == 5
    pixels = np.tile(np.arange(40, dtype=np.uint8)[:, None], (1, 40))
    offset, intensity, gradient = crest_profile(
        Image.fromarray(pixels), (20, 20), (1, 0), 5
    )
    np.testing.assert_allclose(intensity, 20 + offset)
    np.testing.assert_allclose(gradient, 1)
    for a, b in [([], []), ([[1, 2]], [[1, 2], [3, 4]]), ([[np.nan, 1]], [[1, 1]])]:
        with pytest.raises(ValueError):
            coordinate_rmsd(a, b)
    for center, tangent, radius in [
        ((20, 20), (0, 0), 5),
        ((0, 0), (1, 0), 5),
        ((20, 20), (1, 0), 0),
    ]:
        with pytest.raises(ValueError):
            crest_profile(Image.fromarray(pixels), center, tangent, radius)


def test_perturbation_recomputes_axis_and_retains_invalid_rows():
    rows = sensitivity(tooth(mbc=(40, 20)))
    assert len(rows) == 60
    assert any(r["status"] != "valid" for r in rows)
    normal_bc = [
        r for r in rows if r["landmark"] == "distal.bc" and r["direction"] == "normal"
    ]
    assert all(r["distal_change_pp"] == pytest.approx(0) for r in normal_bc)
    normal_apex = [
        r for r in rows if r["landmark"] == "apex" and r["direction"] == "normal"
    ]
    assert any(abs(r["max_change_pp"]) > 0 for r in normal_apex)


def test_displacement_decomposition_identity():
    from week3.errors import decompose_displacements
    from week3.sensitivity import perturb

    baseline = tooth()
    rows = decompose_displacements(
        [
            (baseline, perturb(baseline, "mesial.bc", (0, 2))),
            (baseline, perturb(baseline, "mesial.bc", (0, 4))),
        ]
    )
    mesial = rows[1]
    assert mesial["mean_parallel_shift_px"] == 3
    assert mesial["mean_normal_shift_px"] == 0
    assert mesial["rms_displacement_px"] == pytest.approx(np.sqrt(10))
    assert mesial["centered_residual_rms_px"] == 1
    for row in rows:
        assert row["rms_displacement_px"] ** 2 == pytest.approx(
            row["mean_drift_magnitude_px"] ** 2 + row["centered_residual_rms_px"] ** 2
        )
    with pytest.raises(ValueError):
        decompose_displacements([])


def test_report_formatting_handles_undefined_coefficients():
    from week3.analyze import fmt, kappa_text

    assert fmt(None, ".4f") == "undefined"
    assert fmt(0.12345, ".3f") == "0.123"
    assert kappa_text(None).startswith("undefined")
    assert kappa_text(0.5) == "0.5000"


def test_synthetic_records_cannot_enter_empirical_analysis():
    from week3.analyze import reject_synthetic

    reject_synthetic([{"image_id": "patient.png"}])
    with pytest.raises(ValueError, match="synthetic"):
        reject_synthetic([{"image_id": "SYNTHETIC_geometry_fixture"}])


def test_new_study_cli_end_to_end(tmp_path, monkeypatch, capsys):
    import json
    import sys
    from pathlib import Path
    from week3 import analyze

    fixtures = Path(analyze.ROOT) / "exports" / "synthetic" / "measurements.json"
    argv = ["analyze", "--measurements", str(fixtures), "--output", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError, match="synthetic"):
        analyze.main()
    monkeypatch.setattr(sys, "argv", argv + ["--allow-synthetic"])
    analyze.main()
    comparison = json.loads((tmp_path / "preprocessing_comparison.json").read_text())
    assert comparison["matched_triplets"] == 30
    # Identical coordinates across labels: the fixtures carry no contrast signal.
    assert comparison["conditions"]["he"]["coordinate_rmsd_vs_raw_px"] == 0
    for condition in ("raw", "he", "clahe"):
        stats = json.loads((tmp_path / condition / "statistics.json").read_text())
        assert stats["tooth_pairs"] == 15
        assert (tmp_path / condition / "bland_altman.png").exists()


def test_icc_confidence_interval_and_f_quantiles():
    from week3.statistics import f_ppf, icc_2_1_ci

    # Standard F-table values.
    for q, d1, d2, expected in [
        (0.95, 5, 10, 3.3258),
        (0.975, 9, 9, 4.0260),
        (0.99, 3, 30, 4.5097),
    ]:
        assert f_ppf(q, d1, d2) == pytest.approx(expected, abs=1e-4)
    with pytest.raises(ValueError):
        f_ppf(1, 2, 3)
    values = [[1, 2], [2, 4], [3, 6], [4, 7], [6, 6]]
    lower, upper = icc_2_1_ci(values)
    assert lower < icc_2_1(values) < upper
    assert icc_2_1_ci([[1, 1], [2, 2], [3, 3]]) is None  # perfect agreement
    assert icc_2_1_ci([[1, 1], [1, 1]]) is None


def test_icc_interval_reaches_nominal_coverage():
    from week3.statistics import icc_2_1_ci

    rng = np.random.default_rng(7)
    truth = 9 / (9 + 0.64 + 2.25)
    hits = 0
    for _ in range(400):
        x = (
            rng.normal(0, 3, 20)[:, None]
            + rng.normal(0, 0.8, 2)[None, :]
            + rng.normal(0, 1.5, (20, 2))
        )
        lower, upper = icc_2_1_ci(x)
        hits += lower <= truth <= upper
    assert 0.92 <= hits / 400 <= 0.98


def test_koo_li_bands():
    from week3.analyze import koo_li_band

    assert [koo_li_band(v) for v in (0.4, 0.5, 0.8, 0.9, 0.95)] == [
        "poor",
        "moderate",
        "good",
        "good",
        "excellent",
    ]
