"""Evaluation logic on synthetic rows whose correct answers are known."""

from __future__ import annotations

import math

import numpy as np
import pytest

from week4.constants import LANDMARK_NAMES
from week5 import evaluate
from week5.refinement import combine_views, fit_sigma_scales, orientation_ratio
from week5.stats import paired_bootstrap
from week5.uncertainty import ReviewPolicy


def row(i: int, truth: str, pred: str, p_own: float, p_severe: float = 0.0, fold: int = 1, valid: bool = True) -> dict:
    probabilities = {"I": 0.0, "II": 0.0, "III/IV": 0.0}
    probabilities[pred] = p_own
    probabilities["III/IV"] = max(probabilities["III/IV"], p_severe)
    return {
        "id": i, "fold": fold, "image": f"img{i // 2}.jpg", "valid": valid,
        "truth_stage": truth, "pred_stage": pred if valid else None,
        "truth_pbl": 10.0, "pred_pbl": 12.0 if valid else None,
        "p_stage": probabilities if valid else None,
        "sigma": [2.0] * 5, "radial": [3.0] * 5, "along": [2.0] * 5, "ci": [5.0, 20.0] if valid else None,
    }


def test_policy_flags_low_support_severe_risk_invalid_and_orientation():
    rows = [
        row(0, "I", "I", 0.99),
        row(1, "II", "II", 0.70),                    # uncertain stage
        row(2, "III/IV", "II", 0.95, p_severe=0.2),  # possible severe miss
        row(3, "I", "I", 0.99, valid=False),         # no automatic measurement
        {**row(4, "I", "I", 0.99), "orientation_switched": True},
    ]
    flags = evaluate.policy_flags(rows, ReviewPolicy(0.9, 0.1))
    assert flags.tolist() == [False, True, True, True, True]
    point = evaluate.operating_point(rows, flags)
    assert point["review_rate"] == pytest.approx(0.8)
    assert point["accepted_stage_accuracy"] == 1.0
    assert point["severe_miss_recall"] == 1.0


def test_fit_policy_meets_targets_with_least_review():
    rows = [row(i, "I", "I", 0.99) for i in range(200)]
    rows += [row(200 + i, "II", "I", 0.6) for i in range(20)]           # errors have low support
    rows += [row(300 + i, "III/IV", "II", 0.97, p_severe=0.08) for i in range(5)]  # confident severe misses
    rows += [row(400 + i, "III/IV", "III/IV", 0.99) for i in range(100)]
    policy, feasible = evaluate.fit_policy(rows)
    assert feasible
    flags = evaluate.policy_flags(rows, policy)
    point = evaluate.operating_point(rows, flags)
    assert point["accepted_stage_accuracy"] >= evaluate.ACCEPTED_ACCURACY_TARGET
    assert point["accepted_severe_misses"] <= evaluate.SEVERE_MISS_TARGET * point["severe_n"]
    # Exactly the 25 wrong teeth need review; nothing correct is referred.
    assert flags.sum() == 25


def test_margin_and_crossing_rules_follow_week4_definitions():
    near = {**row(0, "II", "II", 0.9), "pred_pbl": 16.0, "ci": [10.0, 22.0]}  # 1 pp from 15%, half-width 6
    far = {**row(1, "II", "II", 0.9), "pred_pbl": 24.0, "ci": [20.0, 28.0]}
    assert evaluate.margin_flags([near, far], 0.45).tolist() == [True, False]
    assert evaluate.crossing_flags([near, far]).tolist() == [True, False]


def test_auroc_and_spearman_reference_values():
    assert evaluate._auroc(np.asarray([0.1, 0.2, 0.8, 0.9]), np.asarray([False, False, True, True])) == 1.0
    assert evaluate._auroc(np.asarray([1.0, 1.0, 1.0, 1.0]), np.asarray([False, True, False, True])) == 0.5
    assert evaluate._auroc(np.asarray([1.0, 2.0]), np.asarray([True, True])) is None
    assert evaluate._spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)


def test_sigma_scaling_reaches_nominal_95_percent_coverage():
    rng = np.random.default_rng(0)
    teeth, predictions = [], []
    for i in range(4000):
        truth = {n: (100.0, 100.0) for n in LANDMARK_NAMES}
        # True SD is 3 px but the model reports 1.5 px: under-confident by 2x.
        points = {n: tuple((np.asarray(truth[n]) + rng.normal(0, 3.0, 2)).tolist()) for n in LANDMARK_NAMES}
        teeth.append({"truth": truth})
        predictions.append((points, {n: 1.5 for n in LANDMARK_NAMES}))
    scales = fit_sigma_scales(teeth, predictions)
    assert all(s == pytest.approx(2.0, rel=0.08) for s in scales.values())
    rows = [
        {"radial": [math.dist(p[0][n], t["truth"][n]) for n in LANDMARK_NAMES], "sigma": [1.5 * scales[n] for n in LANDMARK_NAMES]}
        for t, p in zip(teeth, predictions)
    ]
    coverage = evaluate.radial_coverage(rows)["all"]
    for nominal in ("0.50", "0.68", "0.90", "0.95"):
        assert coverage[nominal] == pytest.approx(float(nominal), abs=0.03)


def test_combined_views_add_between_view_variance():
    a = ({n: (0.0, 0.0) for n in LANDMARK_NAMES}, {n: 1.0 for n in LANDMARK_NAMES})
    b = ({n: (2.0, 0.0) for n in LANDMARK_NAMES}, {n: 1.0 for n in LANDMARK_NAMES})
    points, sigma = combine_views([a, b])
    assert points["apex"] == (1.0, 0.0)
    assert sigma["apex"] == pytest.approx(math.sqrt(1.0 + 1.0 / 2))  # var_x = 1, isotropic /2
    assert combine_views([a]) == (a[0], a[1])
    assert orientation_ratio({n: 10.0 for n in LANDMARK_NAMES}, {n: 2.0 for n in LANDMARK_NAMES}) == 5.0


def test_paired_bootstrap_detects_a_real_improvement_and_not_a_null_one():
    rng = np.random.default_rng(1)
    base, better, same = [], [], []
    for i in range(300):
        error = rng.uniform(5, 20, 5)
        common = {"id": i, "image": f"img{i // 3}", "valid": True, "truth_pbl": 20.0, "pred_pbl": 22.0,
                  "truth_stage": "II", "pred_stage": "II", "along": error.tolist()}
        base.append({**common, "radial": error.tolist()})
        better.append({**common, "radial": (error - 1.0).tolist()})
        same.append({**common, "radial": (error + rng.normal(0, 0.01, 5)).tolist()})
    improved = paired_bootstrap(base, better, {"mre_px": evaluate_mre}, replicates=300)["mre_px"]
    assert improved["delta"] == pytest.approx(-1.0) and improved["ci95"][1] < 0
    null = paired_bootstrap(base, same, {"mre_px": evaluate_mre}, replicates=300)["mre_px"]
    assert null["ci95"][0] < 0 < null["ci95"][1] or abs(null["delta"]) < 0.01


def evaluate_mre(rows):
    return float(np.mean([v for r in rows for v in r["radial"]]))


def test_correction_simulation_is_exact_without_reader_noise_and_leaves_accepted_teeth_alone():
    teeth = {}
    rows = []
    for i, (truth_stage, pred_stage, flagged) in enumerate([("I", "I", False), ("II", "I", True), ("III/IV", "II", True), ("II", "I", False)]):
        crest = {"I": 10.0, "II": 50.0, "III/IV": 100.0}[truth_stage]
        truth = {"mesial_cej": (100.0, 100.0), "distal_cej": (160.0, 100.0), "mesial_bc": (100.0, 100.0 + crest),
                 "distal_bc": (160.0, 100.0 + crest), "apex": (130.0, 300.0)}
        auto_crest = {"I": 10.0, "II": 50.0, "III/IV": 100.0}[pred_stage]
        points = {**truth, "mesial_bc": (100.0, 100.0 + auto_crest), "distal_bc": (160.0, 100.0 + auto_crest)}
        teeth[i] = {"truth": truth}
        rows.append({
            "id": i, "valid": True, "truth_stage": truth_stage, "pred_stage": pred_stage, "root_px": 200.0,
            "points": {k: list(v) for k, v in points.items()},
            "radial": [math.dist(points[n], truth[n]) for n in LANDMARK_NAMES],
            "sigma": [1.0, 1.0, 5.0, 5.0, 1.0],
            "_flag": flagged,
        })
    flags = np.asarray([r["_flag"] for r in rows])
    pct = {n: 4.0 for n in LANDMARK_NAMES}
    result = evaluate.simulate_corrections(rows, flags, teeth, pct, noise_factor=0.0, seeds=3)["policies"]
    assert result["no review"]["stage_accuracy"]["mean"] == 0.25
    for policy in ("re-place all five", "move visibly wrong", "move two most uncertain"):
        # Both flagged errors are resolved; the unflagged error remains.
        assert result[policy]["stage_accuracy"]["mean"] == 0.75
        assert result[policy]["flagged_errors_resolved"]["mean"] == 1.0
        assert result[policy]["severe_misses"]["mean"] == 0
    assert result["move two most uncertain"]["landmarks_moved_per_reviewed_tooth"]["mean"] == 2.0
    assert result["manual read of every tooth (no AI)"]["stage_accuracy"]["mean"] == 1.0


def test_culprit_attribution_names_the_crest_that_fixes_the_stage():
    truth = {"mesial_cej": (100.0, 100.0), "distal_cej": (160.0, 100.0), "mesial_bc": (100.0, 200.0),
             "distal_bc": (160.0, 110.0), "apex": (130.0, 300.0)}
    points = {**truth, "mesial_bc": (100.0, 110.0)}  # mesial crest placed far too coronal
    r = {"id": 1, "valid": True, "truth_stage": "III/IV", "pred_stage": "I",
         "points": {k: list(v) for k, v in points.items()}, "sigma": [1, 1, 9, 1, 1]}
    out = evaluate.culprits([r], {1: {"truth": truth}})
    assert out["records"][0]["fixed_by"] == ["mesial_bc"]
    assert out["most_uncertain_landmark_is_a_fix"] == 1


def test_comparison_statistics_match_week4_definitions():
    from week4.benchmark import downstream
    from week5.stats import STATISTICS, paired_bootstrap

    rng = np.random.default_rng(2)
    rows = []
    for i in range(120):
        truth = float(rng.uniform(5, 60))
        pred = truth + float(rng.normal(0, 4))
        stage = lambda v: "I" if v < 15 else "II" if v < 33 else "III/IV"  # noqa: E731
        radial = rng.uniform(1, 15, 5).tolist()
        rows.append({"id": i, "image": f"i{i // 4}", "valid": True, "truth_pbl": truth, "pred_pbl": pred,
                     "truth_stage": stage(truth), "pred_stage": stage(pred), "radial": radial, "along": radial})
    reference = downstream(rows)
    assert STATISTICS["icc_2_1"](rows) == pytest.approx(reference["icc_2_1"])
    assert STATISTICS["weighted_kappa"](rows) == pytest.approx(reference["weighted_kappa"])
    assert STATISTICS["stage_accuracy"](rows) == pytest.approx(reference["stage_accuracy"])
    assert STATISTICS["sdr_10px"](rows) == pytest.approx(np.mean([v <= 10 for r in rows for v in r["radial"]]))
    assert STATISTICS["along_mae_px"](rows) == pytest.approx(STATISTICS["mre_px"](rows))
    identical = paired_bootstrap(rows, rows, replicates=50)
    assert all(v["delta"] == 0 and v["ci95"] == [0.0, 0.0] for v in identical.values())
