"""Balanced two-round agreement estimators; undefined coefficients return None."""

from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from numpy.typing import ArrayLike


@dataclass(frozen=True)
class Agreement:
    n: int
    icc_2_1: float | None
    weighted_kappa: float | None
    bias: float
    difference_sd: float
    loa_lower: float
    loa_upper: float
    bias_se: float
    difference_mean_slope: float | None
    outside_indices: tuple[int, ...]
    icc_ci_lower: float | None = None
    icc_ci_upper: float | None = None


def paired_array(first: ArrayLike, second: ArrayLike) -> np.ndarray:
    a, b = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if a.ndim != 1 or b.shape != a.shape or len(a) < 2:
        raise ValueError(
            "At least two aligned pairs of one-dimensional readings required"
        )
    values = np.column_stack((a, b))
    if not np.isfinite(values).all():
        raise ValueError("Readings must be finite")
    return values


def _mean_squares(values: ArrayLike) -> tuple[int, int, float, float, float]:
    """Balanced two-way ANOVA: n, k, MS_subject, MS_round, MS_error."""
    x = np.asarray(values, dtype=float)
    if x.ndim != 2 or min(x.shape) < 2 or not np.isfinite(x).all():
        raise ValueError("A finite balanced subjects-by-rounds matrix is required")
    n, k = x.shape
    grand = x.mean()
    subject, rater = x.mean(axis=1), x.mean(axis=0)
    ms_subject = k * np.square(subject - grand).sum() / (n - 1)
    ms_rater = n * np.square(rater - grand).sum() / (k - 1)
    residual = x - subject[:, None] - rater[None, :] + grand
    ms_error = np.square(residual).sum() / ((n - 1) * (k - 1))
    return n, k, float(ms_subject), float(ms_rater), float(ms_error)


def icc_2_1(values: ArrayLike) -> float | None:
    """Shrout-Fleiss ICC(2,1): two-way, single measure, absolute agreement.

    (MS_subject - MS_error) / (MS_subject + (k-1)*MS_error
                              + k*(MS_round-MS_error)/n).
    McGraw & Wong's ICC(A,1) has this same estimate (and interval) whether rounds
    are modelled as random or fixed, so it also serves the two-way mixed model
    Koo & Li recommend for one reader's repeated readings.
    Negative estimates are retained rather than clipped.
    """
    n, k, ms_subject, ms_rater, ms_error = _mean_squares(values)
    denominator = ms_subject + (k - 1) * ms_error + k * (ms_rater - ms_error) / n
    return (
        None
        if abs(denominator) < 1e-12
        else float((ms_subject - ms_error) / denominator)
    )


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 500):
        for numerator in (
            m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
            -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1)),
        ):
            d = 1.0 + numerator * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + numerator / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1.0) < 1e-14:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1) / (a + b + 2):
        return math.exp(log_front) * _betacf(a, b, x) / a
    return 1.0 - math.exp(log_front) * _betacf(b, a, 1 - x) / b


def f_ppf(q: float, d1: float, d2: float) -> float:
    """Quantile of the F(d1, d2) distribution by bisection on its CDF."""
    if not (0 < q < 1 and d1 > 0 and d2 > 0):
        raise ValueError("Need 0 < q < 1 and positive degrees of freedom")

    def cdf(f: float) -> float:
        return _betainc(d1 / 2, d2 / 2, d1 * f / (d1 * f + d2))

    low, high = 0.0, 1.0
    while cdf(high) < q:
        high *= 2
    for _ in range(200):
        mid = (low + high) / 2
        low, high = (mid, high) if cdf(mid) < q else (low, mid)
    return (low + high) / 2


def icc_2_1_ci(
    values: ArrayLike, confidence: float = 0.95
) -> tuple[float, float] | None:
    """McGraw & Wong (1996) confidence interval for ICC(A,1).

    Uses a Satterthwaite degrees-of-freedom approximation, as in standard
    software (e.g. pingouin's ICC2). Returns None when the estimate is undefined
    or perfect, where the interval formula divides by zero.
    """
    icc = icc_2_1(values)
    n, k, msr, msc, mse = _mean_squares(values)
    if icc is None or icc >= 1:
        return None
    a = k * icc / (n * (1 - icc))
    b = 1 + k * icc * (n - 1) / (n * (1 - icc))
    spread = (a * msc) ** 2 / (k - 1) + (b * mse) ** 2 / ((n - 1) * (k - 1))
    if spread <= 0:
        return None
    v = (a * msc + b * mse) ** 2 / spread
    tail = 1 - (1 - confidence) / 2
    fl, fu = f_ppf(tail, n - 1, v), f_ppf(tail, v, n - 1)
    shared = k * msc + (k * n - k - n) * mse
    lower = n * (msr - fl * mse) / (fl * shared + n * msr)
    upper = n * (fu * msr - mse) / (shared + n * fu * msr)
    return float(lower), float(upper)


def quadratic_kappa(first: ArrayLike, second: ArrayLike) -> float | None:
    values = paired_array(first, second)
    if not np.isin(values, [0, 1, 2]).all():
        raise ValueError("Stages must be encoded as 0, 1, 2 (I, II, III/IV)")
    observed = np.zeros((3, 3))
    for a, b in values.astype(int):
        observed[a, b] += 1
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / len(values)
    weights = np.square(np.arange(3)[:, None] - np.arange(3)[None, :]) / 4
    denominator = (weights * expected).sum()
    return (
        None
        if denominator == 0
        else float(1 - (weights * observed).sum() / denominator)
    )


def agreement(
    first: ArrayLike,
    second: ArrayLike,
    stages_first: ArrayLike,
    stages_second: ArrayLike,
) -> Agreement:
    values = paired_array(first, second)
    if len(stages_first) != len(values) or len(stages_second) != len(values):
        raise ValueError("Stages must align with the PBL reading pairs")
    diff = values[:, 1] - values[:, 0]
    means = values.mean(axis=1)
    bias, sd = float(diff.mean()), float(diff.std(ddof=1))
    lower, upper = bias - 1.96 * sd, bias + 1.96 * sd
    # Descriptive trend only; surfaces in the same tooth are correlated.
    centered = means - means.mean()
    denominator = np.square(centered).sum()
    slope = (
        float((centered * (diff - bias)).sum() / denominator)
        if denominator > 1e-12
        else None
    )
    interval = icc_2_1_ci(values)
    return Agreement(
        len(values),
        icc_2_1(values),
        quadratic_kappa(stages_first, stages_second),
        bias,
        sd,
        lower,
        upper,
        sd / np.sqrt(len(diff)),
        slope,
        tuple(int(i) for i in np.flatnonzero((diff < lower) | (diff > upper))),
        interval[0] if interval else None,
        interval[1] if interval else None,
    )
