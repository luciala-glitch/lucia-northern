"""Paired, radiograph-clustered bootstrap for model-versus-model comparisons."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Sequence

import numpy as np

from week3.statistics import icc_2_1, quadratic_kappa
from week4.constants import SEED
from week4.metrics import STAGE_CODE

Rows = list[dict[str, Any]]


def mre(rows: Rows) -> float:
    return float(np.mean([v for r in rows if "radial" in r for v in r["radial"]]))


def sdr(threshold: float) -> Callable[[Rows], float]:
    def statistic(rows: Rows) -> float:
        return float(np.mean([v <= threshold for r in rows if "radial" in r for v in r["radial"]]))

    return statistic


def along(rows: Rows) -> float:
    return float(np.mean([v for r in rows if "along" in r for v in r["along"]]))


# Point estimates only (no analytic CI), so a 1,000-replicate bootstrap stays fast.
def icc(rows: Rows) -> float:
    valid = [r for r in rows if r["valid"]]
    return float(icc_2_1(np.column_stack(([r["truth_pbl"] for r in valid], [r["pred_pbl"] for r in valid]))))


def kappa(rows: Rows) -> float:
    valid = [r for r in rows if r["valid"]]
    return float(quadratic_kappa(
        [STAGE_CODE[r["truth_stage"]] for r in valid], [STAGE_CODE[r["pred_stage"]] for r in valid]
    ))


def stage_accuracy(rows: Rows) -> float:
    valid = [r for r in rows if r["valid"]]
    return float(np.mean([r["pred_stage"] == r["truth_stage"] for r in valid]))


STATISTICS: dict[str, Callable[[Rows], float]] = {
    "mre_px": mre,
    "sdr_2px": sdr(2),
    "sdr_5px": sdr(5),
    "sdr_10px": sdr(10),
    "along_mae_px": along,
    "icc_2_1": icc,
    "weighted_kappa": kappa,
    "stage_accuracy": stage_accuracy,
}


def paired_bootstrap(
    baseline: Sequence[dict[str, Any]],
    candidate: Sequence[dict[str, Any]],
    statistics: dict[str, Callable[[Rows], float]] = STATISTICS,
    *,
    replicates: int = 1000,
    seed: int = SEED,
) -> dict[str, dict[str, float]]:
    """Candidate minus baseline on teeth valid under both, resampling whole radiographs.

    Both models are scored on the same resampled radiographs in every
    replicate, so between-image difficulty cancels and the interval reflects
    only the model difference.
    """
    by_id = {int(r["id"]): r for r in candidate}
    pairs = [
        (a, by_id[int(a["id"])])
        for a in baseline
        if int(a["id"]) in by_id and a["valid"] and by_id[int(a["id"])]["valid"]
    ]
    groups: dict[str, list[int]] = defaultdict(list)
    for index, (a, _) in enumerate(pairs):
        groups[a["image"]].append(index)
    keys = sorted(groups)
    rng = np.random.default_rng(seed)
    samples = [
        [i for key in rng.choice(keys, len(keys)) for i in groups[key]] for _ in range(replicates)
    ]
    out: dict[str, dict[str, float]] = {}
    for name, statistic in statistics.items():
        point_a = statistic([a for a, _ in pairs])
        point_b = statistic([b for _, b in pairs])
        deltas = []
        for sample in samples:
            try:
                deltas.append(statistic([pairs[i][1] for i in sample]) - statistic([pairs[i][0] for i in sample]))
            except (ValueError, ZeroDivisionError, FloatingPointError):
                continue
        low, high = np.percentile(deltas, [2.5, 97.5])
        out[name] = {
            "n_pairs": len(pairs),
            "baseline": point_a,
            "candidate": point_b,
            "delta": point_b - point_a,
            "ci95": [float(low), float(high)],
        }
    return out
