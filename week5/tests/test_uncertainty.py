from __future__ import annotations

import math

import pytest

from week4.constants import LANDMARK_NAMES
from week4.errors import EmptyPredictionError
from week4.uncertainty import pbl_confidence_interval
from week5.uncertainty import STAGES, ReviewPolicy, StageAnalysis, stage_analysis
from week4.uncertainty import PBLInterval

# A vertical tooth: CEJ at y=100, root 200 px, crest depth chosen per test.
def tooth(crest_px: float) -> dict[str, tuple[float, float]]:
    return {
        "mesial_cej": (100.0, 100.0),
        "distal_cej": (160.0, 100.0),
        "mesial_bc": (100.0, 100.0 + crest_px),
        "distal_bc": (160.0, 100.0 + crest_px / 2),
        "apex": (130.0, 300.0),
    }


def sigma(value: float) -> dict[str, float]:
    return {name: value for name in LANDMARK_NAMES}


def test_interval_matches_week4_monte_carlo_exactly():
    points = tooth(40)
    analysis = stage_analysis(points, sigma(6.0), seed=11)
    week4 = pbl_confidence_interval(points, sigma(6.0), seed=11)
    assert analysis.interval == week4
    assert sum(analysis.probabilities.values()) == pytest.approx(1.0)
    assert set(analysis.probabilities) == set(STAGES)


def test_probabilities_concentrate_when_uncertainty_is_small():
    analysis = stage_analysis(tooth(10), sigma(0.01))  # 5% PBL: firmly Stage I
    assert analysis.probability("I") == pytest.approx(1.0)


def test_boundary_tooth_spreads_probability_across_stages():
    # 66 px of 200 px root ~= 33%: exactly on the II / III-IV boundary.
    analysis = stage_analysis(tooth(66), sigma(8.0))
    assert 0.2 < analysis.probability("III/IV") < 0.8
    assert 0.2 < analysis.probability("II") < 0.8


@pytest.mark.parametrize(
    "points, scales, error",
    [
        (tooth(40), {**sigma(1.0), "apex": -1.0}, ValueError),
        (tooth(40), {**sigma(1.0), "apex": math.nan}, ValueError),
        ({**tooth(40), "apex": (math.inf, 3.0)}, sigma(1.0), ValueError),
        (tooth(40), {k: 1.0 for k in LANDMARK_NAMES[:4]}, EmptyPredictionError),
    ],
)
def test_invalid_inputs_are_rejected(points, scales, error):
    with pytest.raises(error):
        stage_analysis(points, scales)


def test_too_few_draws_are_rejected():
    with pytest.raises(ValueError, match="100 draws"):
        stage_analysis(tooth(40), sigma(1.0), draws=50)


def test_impossible_geometry_fails_instead_of_inventing_an_interval():
    # Apex above the CEJ: every draw fails the Week 3 guardrails.
    points = {**tooth(40), "apex": (130.0, 20.0)}
    with pytest.raises(EmptyPredictionError, match="guardrails"):
        stage_analysis(points, sigma(0.5))


def analysis(**probabilities: float) -> StageAnalysis:
    return StageAnalysis(PBLInterval(10, 20, 1000, 1000), {"I": 0.0, "II": 0.0, "III/IV": 0.0, **probabilities})


def test_policy_flags_uncertain_stage():
    flagged, reasons = ReviewPolicy(0.9, None).review("II", analysis(II=0.7, I=0.3), sigma(3))
    assert flagged and "70%" in reasons[0]
    assert ReviewPolicy(0.9, None).review("II", analysis(II=0.95, I=0.05), sigma(3)) == (False, ())


def test_severe_guard_catches_possible_missed_stage_iii_iv_only_for_lower_stages():
    policy = ReviewPolicy(0.5, 0.1)
    flagged, reasons = policy.review("II", analysis(II=0.85, **{"III/IV": 0.15}), sigma(3))
    assert flagged and "missed Stage III/IV" in reasons[0]
    # An automatic III/IV is never 'missed' by this rule.
    assert policy.review("III/IV", analysis(**{"III/IV": 0.95, "II": 0.05}), sigma(3)) == (False, ())


def test_optional_sigma_limit_and_json_round_trip():
    policy = ReviewPolicy(0.6, None, max_sigma_px=10.0)
    flagged, reasons = policy.review("I", analysis(I=1.0), {**sigma(3), "apex": 12.0})
    assert flagged and "12.0px" in reasons[0]
    assert ReviewPolicy.from_json(policy.to_json()) == policy


def test_widened_interval_stretches_each_side_and_stays_in_range():
    from week5.uncertainty import widen_interval

    wide = widen_interval(PBLInterval(10.0, 30.0, 990, 1000), 18.0, 1.5)
    assert (wide.lower, wide.upper) == (pytest.approx(6.0), pytest.approx(36.0))
    assert widen_interval(PBLInterval(1.0, 99.0, 1000, 1000), 50.0, 3.0).pair == (0.0, 100.0)
    with pytest.raises(ValueError):
        widen_interval(PBLInterval(1.0, 2.0, 1000, 1000), 1.5, 0.0)


def test_conformal_factor_reaches_the_requested_coverage():
    import numpy as np

    from week5.uncertainty import conformal_factor, widen_interval

    rng = np.random.default_rng(4)
    # Intervals of half-width 5 around the point, but true errors have SD 4: under-covering.
    rows = [(50.0, 45.0, 55.0, 50.0 + rng.normal(0, 4.0)) for _ in range(2000)]
    factor = conformal_factor(rows)
    covered = np.mean([
        widen_interval(PBLInterval(lo, hi, 1000, 1000), p, factor).lower <= t <= widen_interval(PBLInterval(lo, hi, 1000, 1000), p, factor).upper
        for p, lo, hi, t in rows
    ])
    assert covered == pytest.approx(0.95, abs=0.01)
    assert factor == pytest.approx(1.96 * 4 / 5, rel=0.1)
    # Already over-covering intervals are never narrowed.
    assert conformal_factor([(50.0, 0.0, 100.0, 51.0)] * 50) == 1.0
