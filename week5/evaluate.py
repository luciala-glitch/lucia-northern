"""Reproduce every Week 5 table, figure and clinical example from saved predictions.

Inputs (nothing here trains a model or looks at a label it should not):

* ``week4/reports/results/per_tooth_predictions.json`` - Week 4 Raw/CLAHE rows;
* ``week5/reports/results/screening.json`` - fold-1 configuration screen;
* ``week5/reports/results/per_tooth_predictions_<source>.json`` - Week 5 rows
  written by ``python -m week5.experiments predict``.

Protocol, fixed before the external test was scored:

* Each refinement step is added to the system only if it lowers the
  cross-fitted development MRE (development fold k is always scored with
  parameters fitted on the other four folds).
* Blend weight, sigma scales, orientation-switch ratio and the review policy
  are then fitted on all development out-of-fold rows and frozen in
  ``calibration.json``; the 327-tooth external test is scored once.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

from week3.pbl_calculator import PBLValidationError, calculate_tooth_pbl  # noqa: E402
from week4.benchmark import DENPAR, add_image_features, downstream, landmark_table, load, score  # noqa: E402
from week4.constants import LANDMARK_NAMES, SEED, STAGE_BOUNDARIES  # noqa: E402
from week4.errors import EmptyPredictionError  # noqa: E402
from week4.uncertainty import MARGIN_K, PBLInterval, to_tooth_landmarks  # noqa: E402
from week5.experiments import TTA_MARGINS, checkpoint  # noqa: E402
from week5.refinement import (  # noqa: E402
    blend_prediction,
    fit_blend_weights,
    fit_sigma_scales,
    orientation_ratio,
)
from week5.stats import paired_bootstrap  # noqa: E402
from week5.uncertainty import STAGES, ReviewPolicy, conformal_factor, stage_analysis, widen_interval  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
W4_RESULTS = ROOT / "week4" / "reports" / "results"
REPORTS = ROOT / "week5" / "reports"
RESULTS = REPORTS / "results"
CASES = REPORTS / "clinical_examples"

ACCEPTED_ACCURACY_TARGET = 0.95
# Accepted III/IV->I/II misses as a share of all III/IV teeth. Tightened from 1%
# after the first run on clinical grounds (missed severe disease is the costliest
# error); the 1% variant stays in the report as "first-run target".
SEVERE_MISS_TARGET = 0.005
FIRST_RUN_SEVERE_MISS_TARGET = 0.01
ORIENTATION_GRID = (*np.round(np.arange(1.0, 4.01, 0.1), 2), math.inf)
STAGE_GRID = tuple(np.round(np.arange(0.50, 0.995, 0.01), 2))
SEVERE_GRID: tuple[float | None, ...] = (None, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30)
CORRECTION_SEEDS = 200
COLORS = dict(zip(LANDMARK_NAMES, ("#00b4d8", "#0077b6", "#ffb703", "#fb8500", "#9b5de5")))
SHORT = {"mesial_cej": "M-CEJ", "distal_cej": "D-CEJ", "mesial_bc": "M-BC", "distal_bc": "D-BC", "apex": "Apex"}

Prediction = tuple[dict[str, tuple[float, float]], dict[str, float]]
Rows = list[dict[str, Any]]


# ------------------------------------------------------------------ sources


def indexed(rows: Sequence[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(row["id"]): row for row in rows}


def load_sources(selected: str, tta: bool) -> dict[str, dict[str, dict[int, dict[str, Any]]]]:
    week4 = json.loads((W4_RESULTS / "per_tooth_predictions.json").read_text())
    sources = {
        "week4": {
            "raw_dev": indexed(week4["learned_raw_dev"]),
            "raw_ext": indexed(week4["learned_raw_ext"]),
            "clahe_dev": indexed(week4["learned_clahe_dev"]),
            "clahe_ext": indexed(week4["learned_clahe_ext"]),
        }
    }
    names = {"week4_tta" if tta else "week4", f"{selected}_tta" if tta else selected}
    for name in sorted(names):
        path = RESULTS / f"per_tooth_predictions_{name}.json"
        if not path.is_file():
            raise SystemExit(f"Missing {path.relative_to(ROOT)}; run python -m week5.experiments predict first")
        loaded = {key: indexed(rows) for key, rows in json.loads(path.read_text()).items()}
        # The re-scored Week 4 checkpoints replace the Week 4 file only when
        # they add test-time views or the reversed-orientation hypothesis.
        sources["week4_views" if name.startswith("week4") else name] = loaded
    return sources


# ------------------------------------------------------------------ system


@dataclass(frozen=True)
class System:
    label: str
    source: str
    blend: bool = False
    orientation: bool = False


def _hypotheses(
    source: Mapping[str, Mapping[int, dict[str, Any]]], split: str, tooth_id: int, weight: float
) -> tuple[Prediction, Prediction | None]:
    weights = {name: weight for name in LANDMARK_NAMES}
    raw, clahe = source[f"raw_{split}"][tooth_id], source[f"clahe_{split}"][tooth_id]
    given = blend_prediction(raw, clahe, weights)[:2]
    if f"raw_{split}_flipped" not in source:
        return given, None
    flipped = blend_prediction(
        source[f"raw_{split}_flipped"][tooth_id], source[f"clahe_{split}_flipped"][tooth_id], weights
    )[:2]
    return given, flipped


def _choose(given: Prediction, flipped: Prediction | None, threshold: float) -> tuple[Prediction, float | None, bool]:
    if flipped is None:
        return given, None, False
    ratio = orientation_ratio(given[1], flipped[1])
    return (flipped, ratio, True) if ratio >= threshold else (given, ratio, False)


def _mean_error(teeth: Sequence[dict[str, Any]], predictions: Sequence[Prediction]) -> float:
    return float(np.mean([
        np.linalg.norm(np.asarray(p[0][n]) - np.asarray(t["truth"][n]))
        for t, p in zip(teeth, predictions) for n in LANDMARK_NAMES
    ]))


def fit_system(system: System, teeth: Sequence[dict[str, Any]], source: Mapping[str, Any]) -> dict[str, Any]:
    weight = 0.5 if system.blend else 1.0
    pairs = [_hypotheses(source, "dev", int(t["id"]), weight) for t in teeth]
    threshold = math.inf
    if system.orientation:
        scores = {
            t: _mean_error(teeth, [_choose(g, f, t)[0] for g, f in pairs]) for t in ORIENTATION_GRID
        }
        # Lowest training MRE; ties go to the larger ratio (fewer switches).
        threshold = min(ORIENTATION_GRID, key=lambda t: (round(scores[t], 6), -t))
    chosen = [_choose(g, f, threshold)[0] for g, f in pairs]
    return {
        "raw_weight": weight,
        "orientation_switch_ratio": None if math.isinf(threshold) else float(threshold),
        "sigma_scale": fit_sigma_scales(teeth, chosen),
    }


def apply_system(
    parameters: Mapping[str, Any], teeth: Sequence[dict[str, Any]], source: Mapping[str, Any], split: str
) -> tuple[list[Prediction], list[dict[str, Any]]]:
    threshold = parameters["orientation_switch_ratio"]
    threshold = math.inf if threshold is None else threshold
    scales = parameters["sigma_scale"]
    predictions, meta = [], []
    for tooth in teeth:
        given, flipped = _hypotheses(source, split, int(tooth["id"]), parameters["raw_weight"])
        (points, sigma), ratio, switched = _choose(given, flipped, threshold)
        predictions.append((points, {n: sigma[n] * scales[n] for n in LANDMARK_NAMES}))
        meta.append({"orientation_ratio": ratio, "orientation_switched": switched, "sigma_unscaled": [sigma[n] for n in LANDMARK_NAMES]})
    return predictions, meta


def _scored(teeth: Sequence[dict[str, Any]], predictions: Sequence[Prediction], meta: Sequence[dict[str, Any]]) -> Rows:
    rows = score(list(teeth), predictions)
    for row, extra in zip(rows, meta):
        row.update(extra)
    return rows


def evaluate_system(
    system: System, dev: Sequence[dict[str, Any]], ext: Sequence[dict[str, Any]], sources: Mapping[str, Any]
) -> dict[str, Any]:
    source = sources[system.source]
    dev_rows: dict[int, dict[str, Any]] = {}
    folds = []
    for fold in range(1, 6):
        train = [t for t in dev if int(t["fold"]) != fold]
        test = [t for t in dev if int(t["fold"]) == fold]
        parameters = fit_system(system, train, source)
        folds.append({**parameters, "held_out_fold": fold})
        dev_rows.update(indexed(_scored(test, *apply_system(parameters, test, source, "dev"))))
    final = fit_system(system, dev, source)
    return {
        "system": system,
        "dev": [dev_rows[int(t["id"])] for t in dev],
        "ext": _scored(ext, *apply_system(final, ext, source, "ext")),
        "fold_parameters": folds,
        "parameters": final,
    }


def mre(rows: Rows) -> float:
    return float(landmark_table(rows)["all"]["mre_px"])


def summary(rows: Rows) -> dict[str, Any]:
    return {"landmarks": landmark_table(rows), "downstream": downstream(rows)}


# ------------------------------------------------------------- uncertainty


def add_stage_analysis(rows: Rows) -> None:
    """Monte Carlo interval and stage probabilities from the calibrated sigmas."""
    for row in rows:
        row.update(ci=None, p_stage=None, ci_covers_truth=None)
        if not row["valid"]:
            continue
        points = {n: tuple(row["points"][n]) for n in LANDMARK_NAMES}
        sigma = dict(zip(LANDMARK_NAMES, row["sigma"]))
        try:
            analysis = stage_analysis(points, sigma, draws=1000, seed=SEED + int(row["id"]))
        except EmptyPredictionError:
            continue
        lower, upper = analysis.interval.pair
        row.update(
            ci=[lower, upper],
            p_stage=analysis.probabilities,
            ci_covers_truth=bool(lower <= row["truth_pbl"] <= upper),
        )


def _interval_rows(rows: Rows) -> list[tuple[float, float, float, float]]:
    return [(r["pred_pbl"], r["ci"][0], r["ci"][1], r["truth_pbl"]) for r in rows if r.get("ci")]


def add_calibrated_interval(rows: Rows, factor: float) -> None:
    """The reported 95% PBL interval: Monte Carlo interval stretched by the conformal factor."""
    for row in rows:
        if row.get("ci"):
            wide = widen_interval(PBLInterval(row["ci"][0], row["ci"][1], 1000, 1000), row["pred_pbl"], factor)
            row["ci_calibrated"] = [wide.lower, wide.upper]
            row["ci_calibrated_covers_truth"] = bool(wide.lower <= row["truth_pbl"] <= wide.upper)


def cross_fitted_interval(rows: Rows) -> list[float]:
    factors = []
    for fold in range(1, 6):
        factor = conformal_factor(_interval_rows([r for r in rows if r["fold"] != fold]))
        add_calibrated_interval([r for r in rows if r["fold"] == fold], factor)
        factors.append(factor)
    return factors


def _policy_arrays(rows: Rows) -> dict[str, np.ndarray]:
    analysed = np.asarray([r.get("p_stage") is not None for r in rows])
    p_own = np.asarray([r["p_stage"][r["pred_stage"]] if r.get("p_stage") else 0.0 for r in rows])
    p_severe = np.asarray([r["p_stage"]["III/IV"] if r.get("p_stage") else 1.0 for r in rows])
    not_severe = np.asarray([r["valid"] and r["pred_stage"] != "III/IV" for r in rows])
    wrong = np.asarray([(not r["valid"]) or r["pred_stage"] != r["truth_stage"] for r in rows])
    severe = np.asarray([r["truth_stage"] == "III/IV" for r in rows])
    miss = severe & np.asarray([(not r["valid"]) or r["pred_stage"] != "III/IV" for r in rows])
    max_sigma = np.asarray([max(r["sigma"]) if "sigma" in r else math.inf for r in rows])
    return {
        "analysed": analysed, "p_own": p_own, "p_severe": p_severe, "not_severe": not_severe,
        "wrong": wrong, "severe": severe, "miss": miss, "max_sigma": max_sigma,
    }


def policy_flags(rows: Rows, policy: ReviewPolicy, arrays: Mapping[str, np.ndarray] | None = None) -> np.ndarray:
    a = arrays or _policy_arrays(rows)
    flag = ~a["analysed"] | (a["p_own"] < policy.min_stage_probability)
    if policy.severe_guard is not None:
        flag |= a["not_severe"] & (a["p_severe"] >= policy.severe_guard)
    if policy.max_sigma_px is not None:
        flag |= a["max_sigma"] > policy.max_sigma_px
    # Orientation switches are always shown to the clinician.
    flag |= np.asarray([bool(r.get("orientation_switched")) for r in rows])
    return flag


def margin_flags(rows: Rows, k: float) -> np.ndarray:
    """Week 4 rule: PBL closer to a boundary than k x the CI half-width."""
    out = []
    for r in rows:
        if not r["valid"] or r.get("ci") is None:
            out.append(True)
            continue
        half = max((r["ci"][1] - r["ci"][0]) / 2, 1e-9)
        margin = min(abs(r["pred_pbl"] - b) for b in STAGE_BOUNDARIES)
        out.append(margin < k * half)
    return np.asarray(out)


def crossing_flags(rows: Rows) -> np.ndarray:
    return np.asarray([
        (not r["valid"]) or r.get("ci") is None or any(r["ci"][0] < b <= r["ci"][1] for b in STAGE_BOUNDARIES)
        for r in rows
    ])


def operating_point(rows: Rows, flag: np.ndarray) -> dict[str, Any]:
    a = _policy_arrays(rows)
    accepted = ~flag
    n_severe = int(a["severe"].sum())
    return {
        "n": len(rows),
        "review_rate": float(flag.mean()),
        "accepted_n": int(accepted.sum()),
        "accepted_stage_accuracy": float((~a["wrong"][accepted]).mean()) if accepted.any() else None,
        "accepted_stage_errors": int((a["wrong"] & accepted).sum()),
        "accepted_severe_misses": int((a["miss"] & accepted).sum()),
        "severe_n": n_severe,
        "stage_error_recall": float(flag[a["wrong"]].mean()) if a["wrong"].any() else 1.0,
        "severe_miss_recall": float(flag[a["miss"]].mean()) if a["miss"].any() else 1.0,
    }


def target_check(point: Mapping[str, Any], severe_target: float = SEVERE_MISS_TARGET) -> dict[str, Any]:
    """Whether one operating point meets each clinical target, reported separately."""
    accuracy = point["accepted_stage_accuracy"]
    miss_rate = point["accepted_severe_misses"] / point["severe_n"] if point["severe_n"] else 0.0
    return {
        "accepted_stage_accuracy": accuracy,
        "accepted_stage_accuracy_met": accuracy is not None and accuracy >= ACCEPTED_ACCURACY_TARGET,
        "accepted_severe_miss_rate": miss_rate,
        "accepted_severe_miss_rate_met": miss_rate <= severe_target,
    }


def fit_policy(rows: Rows, severe_target: float = SEVERE_MISS_TARGET) -> tuple[ReviewPolicy, bool]:
    """Smallest review rate meeting both clinical targets on the given (development) rows."""
    a = _policy_arrays(rows)
    n_severe = max(int(a["severe"].sum()), 1)
    best: tuple[float, ReviewPolicy] | None = None
    fallback: tuple[float, float, ReviewPolicy] | None = None
    for guard in SEVERE_GRID:
        for tau in STAGE_GRID:
            policy = ReviewPolicy(float(tau), guard)
            flag = policy_flags(rows, policy, a)
            accepted = ~flag
            accuracy = float((~a["wrong"][accepted]).mean()) if accepted.any() else 1.0
            misses = int((a["miss"] & accepted).sum())
            if accuracy >= ACCEPTED_ACCURACY_TARGET and misses <= severe_target * n_severe:
                if best is None or flag.mean() < best[0]:
                    best = (float(flag.mean()), policy)
            key = (accuracy - misses / n_severe, -float(flag.mean()))
            if fallback is None or key > fallback[:2]:
                fallback = (*key, policy)
    if best is not None:
        return best[1], True
    assert fallback is not None
    return fallback[2], False


def cross_fitted_policy(rows: Rows) -> tuple[np.ndarray, list[dict[str, Any]]]:
    flags = np.zeros(len(rows), dtype=bool)
    fitted = []
    for fold in range(1, 6):
        train = [r for r in rows if r["fold"] != fold]
        index = [i for i, r in enumerate(rows) if r["fold"] == fold]
        policy, feasible = fit_policy(train)
        flags[index] = policy_flags([rows[i] for i in index], policy)
        fitted.append({**policy.to_json(), "targets_met_on_training_folds": feasible, "held_out_fold": fold})
    return flags, fitted


def match_review_rate(rows: Rows, rate: float, guard: float | None) -> ReviewPolicy:
    """Stage-probability threshold whose development review rate is closest to ``rate``."""
    a = _policy_arrays(rows)
    return min(
        (ReviewPolicy(float(t), guard) for t in np.round(np.arange(0.30, 0.995, 0.005), 3)),
        key=lambda p: abs(policy_flags(rows, p, a).mean() - rate),
    )


def fit_margin_k(rows: Rows) -> float:
    """Week 4 margin rule re-tuned to the same accepted-accuracy target (development only)."""
    a = _policy_arrays(rows)
    for k in np.round(np.arange(0.0, 3.01, 0.05), 2):
        flag = margin_flags(rows, float(k))
        accepted = ~flag
        if accepted.any() and (~a["wrong"][accepted]).mean() >= ACCEPTED_ACCURACY_TARGET:
            return float(k)
    return 3.0


def _auroc(score_values: np.ndarray, positive: np.ndarray) -> float | None:
    if positive.all() or (~positive).all():
        return None
    ranks = np.argsort(np.argsort(score_values, kind="mergesort"), kind="mergesort").astype(float)
    # Average ranks for ties.
    for value in np.unique(score_values):
        tied = score_values == value
        if tied.sum() > 1:
            ranks[tied] = ranks[tied].mean()
    n_pos, n_neg = positive.sum(), (~positive).sum()
    return float((ranks[positive].sum() - n_pos * (n_pos - 1) / 2) / (n_pos * n_neg))


def _spearman(a: Sequence[float], b: Sequence[float]) -> float:
    ra = np.argsort(np.argsort(a))
    rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def confidence_metrics(rows: Rows) -> dict[str, Any]:
    analysed = [r for r in rows if r.get("p_stage")]
    error = np.asarray([np.mean(r["radial"]) for r in analysed])
    pbl_error = np.asarray([abs(r["pred_pbl"] - r["truth_pbl"]) for r in analysed])
    wrong = np.asarray([r["pred_stage"] != r["truth_stage"] for r in analysed])
    scores = {
        "max_sigma_px": np.asarray([max(r["sigma"]) for r in analysed]),
        "mean_sigma_px": np.asarray([np.mean(r["sigma"]) for r in analysed]),
        "ci_width_pp": np.asarray([r["ci"][1] - r["ci"][0] for r in analysed]),
        "one_minus_p_auto_stage": np.asarray([1 - r["p_stage"][r["pred_stage"]] for r in analysed]),
    }
    landmark_level = {
        name: _spearman([r["sigma"][k] for r in analysed], [r["radial"][k] for r in analysed])
        for k, name in enumerate(LANDMARK_NAMES)
    }
    return {
        "n": len(analysed),
        "scores": {
            name: {
                "spearman_vs_mean_landmark_error": _spearman(values, error),
                "pearson_vs_mean_landmark_error": float(np.corrcoef(values, error)[0, 1]),
                "spearman_vs_abs_pbl_error": _spearman(values, pbl_error),
                "auroc_stage_error": _auroc(values, wrong),
            }
            for name, values in scores.items()
        },
        "landmark_level_spearman_sigma_vs_error": landmark_level,
        "pbl_ci95_coverage": float(np.mean([r["ci_covers_truth"] for r in analysed])),
        "median_ci_width_pp": float(np.median(scores["ci_width_pp"])),
    }


NOMINAL = (0.5, 0.68, 0.8, 0.9, 0.95, 0.99)


def radial_coverage(rows: Rows, key: str = "sigma") -> dict[str, dict[str, float]]:
    """Empirical share of landmarks inside the nominal 2-D Gaussian radius."""
    scored = [r for r in rows if "radial" in r]
    out = {}
    for name_index, name in [*enumerate(LANDMARK_NAMES), (None, "all")]:
        ratios = np.asarray([
            r["radial"][k] / max(r[key][k], 1e-6)
            for r in scored
            for k in (range(5) if name_index is None else [name_index])
        ])
        out[name] = {f"{p:.2f}": float(np.mean(ratios <= math.sqrt(-2 * math.log(1 - p)))) for p in NOMINAL}
    return out


def stage_reliability(rows: Rows) -> dict[str, Any]:
    analysed = [r for r in rows if r.get("p_stage")]
    confidence = np.asarray([r["p_stage"][r["pred_stage"]] for r in analysed])
    correct = np.asarray([r["pred_stage"] == r["truth_stage"] for r in analysed])
    edges = np.asarray([0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0001])
    bins = []
    ece = 0.0
    for low, high in zip(edges[:-1], edges[1:]):
        members = (confidence >= low) & (confidence < high)
        if members.any():
            gap = abs(confidence[members].mean() - correct[members].mean())
            ece += members.mean() * gap
            bins.append({
                "range": [float(low), float(min(high, 1.0))], "n": int(members.sum()),
                "mean_confidence": float(confidence[members].mean()), "accuracy": float(correct[members].mean()),
            })
    brier = float(np.mean([
        sum((r["p_stage"][s] - (r["truth_stage"] == s)) ** 2 for s in STAGES) for r in analysed
    ]))
    return {"bins": bins, "expected_calibration_error": float(ece), "multiclass_brier": brier}


def high_confidence_failures(rows: Rows, sigma_cut: float, error_cut: float, flags: np.ndarray) -> dict[str, Any]:
    picked = [
        (r, bool(f)) for r, f in zip(rows, flags)
        if "radial" in r and max(r["sigma"]) <= sigma_cut and np.mean(r["radial"]) >= error_cut
    ]
    return {
        "definition": f"max calibrated sigma <= {sigma_cut:.1f}px (development median) and mean error >= {error_cut:.1f}px (development 90th percentile)",
        "n": len(picked),
        "stage_wrong": sum(r["valid"] and r["pred_stage"] != r["truth_stage"] for r, _ in picked),
        "stage_wrong_and_accepted": sum(r["valid"] and r["pred_stage"] != r["truth_stage"] and not f for r, f in picked),
        "tilted": sum(bool(r["tilted"]) for r, _ in picked),
        "multirooted": sum(bool(r["multirooted"]) for r, _ in picked),
        "ids": [int(r["id"]) for r, _ in picked],
    }


# ---------------------------------------------------------------- clinical


def add_sharpness(teeth: Sequence[dict[str, Any]]) -> None:
    """Mean absolute Laplacian inside the tooth box: low values mean a blurred film."""
    by_file: dict[str, list[dict[str, Any]]] = {}
    for tooth in teeth:
        by_file.setdefault(tooth["file_name"], []).append(tooth)
    for file_name, group in by_file.items():
        gray = Image.open(DENPAR / file_name).convert("L")
        edges = np.asarray(gray.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
        for tooth in group:
            x0, y0, x1, y1 = tooth["bbox"]
            tooth["sharpness"] = float(edges[y0:y1, x0:x1].mean())


def subgroups(
    rows: Rows, reference: Rows, flags: np.ndarray, teeth: Sequence[dict[str, Any]], cuts: Mapping[str, float]
) -> list[dict[str, Any]]:
    lookup = {int(t["id"]): t for t in teeth}
    ref = indexed(reference)
    definitions: dict[str, Callable[[dict[str, Any]], bool]] = {
        "all": lambda t: True,
        "multi-rooted (molar-like)": lambda t: t["multirooted"],
        "single-rooted": lambda t: not t["multirooted"],
        "anterior site": lambda t: t["site"] == "Anterior",
        "posterior site": lambda t: t["site"] != "Anterior",
        "maxillary": lambda t: t["arch"] == "Upper",
        "mandibular": lambda t: t["arch"] == "Lower",
        "tilted >15°": lambda t: t["tilted"],
        "low contrast (dev bottom quartile)": lambda t: t["rms_contrast"] <= cuts["rms_contrast"],
        "blurred (dev bottom-quartile sharpness)": lambda t: t["sharpness"] <= cuts["sharpness"],
        "orientation metadata wrong (>45°)": lambda t: t["orientation_error_deg"] > 45,
    }
    table = []
    for name, keep in definitions.items():
        index = [i for i, r in enumerate(rows) if keep(lookup[int(r["id"])])]
        members = [rows[i] for i in index]
        if not members:
            continue
        valid = [r for r in members if r["valid"]]
        old = [ref[int(r["id"])] for r in members]
        old_valid = [r for r in old if r["valid"]]
        point = operating_point(members, flags[index])
        table.append({
            "subgroup": name,
            "n": len(members),
            "week4_mre_px": mre(old),
            "mre_px": mre(members),
            "week4_stage_accuracy": float(np.mean([r["pred_stage"] == r["truth_stage"] for r in old_valid])),
            "stage_accuracy": float(np.mean([r["pred_stage"] == r["truth_stage"] for r in valid])) if valid else None,
            "severe_n": point["severe_n"],
            "severe_misses": int(sum(r["truth_stage"] == "III/IV" and (not r["valid"] or r["pred_stage"] != "III/IV") for r in members)),
            "review_rate": point["review_rate"],
            "accepted_stage_accuracy": point["accepted_stage_accuracy"],
            "accepted_severe_misses": point["accepted_severe_misses"],
        })
    return table


def _stage(points: Mapping[str, Sequence[float]]) -> str | None:
    try:
        return calculate_tooth_pbl(to_tooth_landmarks({n: tuple(points[n]) for n in LANDMARK_NAMES})).stage
    except (PBLValidationError, EmptyPredictionError):
        return None


def culprits(rows: Rows, teeth_by_id: Mapping[int, dict[str, Any]]) -> dict[str, Any]:
    """Which single landmark, moved to the reference, fixes each wrong stage?"""
    fixers: Counter[str] = Counter()
    records = []
    uncertain_hit = 0
    for row in rows:
        if not row["valid"] or row["pred_stage"] == row["truth_stage"]:
            continue
        truth = teeth_by_id[int(row["id"])]["truth"]
        fixes = [
            name for name in LANDMARK_NAMES
            if _stage({**row["points"], name: truth[name]}) == row["truth_stage"]
        ]
        fixers.update(fixes or ["needs ≥2 landmarks"])
        top = LANDMARK_NAMES[int(np.argmax(row["sigma"]))]
        uncertain_hit += top in fixes
        records.append({"id": int(row["id"]), "fixed_by": fixes, "most_uncertain": top})
    n = len(records)
    return {
        "n_stage_errors": n,
        "single_landmark_fix_counts": dict(fixers),
        "most_uncertain_landmark_is_a_fix": uncertain_hit,
        "records": records,
    }


def human_sigma(row: dict[str, Any], pct_root: Mapping[str, float], factor: float = 1.0) -> np.ndarray:
    """Per-axis SD of one reader: the mean distance between two reads is sigma*sqrt(pi)."""
    return np.asarray([pct_root[n] / 100 * row["root_px"] / math.sqrt(math.pi) * factor for n in LANDMARK_NAMES])


CORRECTION_POLICIES = ("no review", "re-place all five", "move visibly wrong", "move two most uncertain")


def simulate_corrections(
    rows: Rows,
    flags: np.ndarray,
    teeth_by_id: Mapping[int, dict[str, Any]],
    pct_root: Mapping[str, float],
    *,
    noise_factor: float = 1.0,
    seeds: int = CORRECTION_SEEDS,
) -> dict[str, Any]:
    """Reviewer model: flagged teeth only; a moved landmark lands at reference + reader noise.

    Reader noise is the Week 3 test-retest distance (as % of root length) of a
    single non-specialist reader, so this estimates whether review resolves the
    errors without assuming a perfect clinician.
    """
    results: dict[str, list[dict[str, float]]] = {p: [] for p in CORRECTION_POLICIES}
    results["manual read of every tooth (no AI)"] = []
    visible = {n: 2 * pct_root[n] / 100 for n in LANDMARK_NAMES}  # x root length
    first_seed: dict[str, list[dict[str, Any]]] = {p: [] for p in CORRECTION_POLICIES}
    for seed in range(seeds):
        rng = np.random.default_rng(SEED + 7919 * seed)
        noise = {int(r["id"]): rng.normal(0, 1, (5, 2)) for r in rows}
        for policy in (*CORRECTION_POLICIES, "manual read of every tooth (no AI)"):
            correct = severe_missed = resolved = broken = moved = reviewed = errors_flagged = correct_flagged = 0
            for row, flag in zip(rows, flags):
                truth = teeth_by_id[int(row["id"])]["truth"]
                scale = human_sigma(row, pct_root, noise_factor)
                reread = {
                    n: (np.asarray(truth[n]) + scale[k] * noise[int(row["id"])][k]).tolist()
                    for k, n in enumerate(LANDMARK_NAMES)
                }
                auto_stage = row["pred_stage"] if row["valid"] else None
                auto_ok = auto_stage == row["truth_stage"]
                if policy == "manual read of every tooth (no AI)":
                    final, count = _stage(reread), 5
                elif policy == "no review" or not flag:
                    final, count = auto_stage, 0
                else:
                    reviewed += 1
                    if not row["valid"] or policy == "re-place all five":
                        chosen = list(LANDMARK_NAMES)
                    elif policy == "move visibly wrong":
                        chosen = [n for k, n in enumerate(LANDMARK_NAMES) if row["radial"][k] > visible[n] * row["root_px"]]
                    else:
                        chosen = [LANDMARK_NAMES[k] for k in np.argsort(row["sigma"])[-2:]]
                    edited = {**row["points"], **{n: reread[n] for n in chosen}}
                    final, count = _stage(edited), len(chosen)
                    if final is None:  # the edit broke a guardrail: the reviewer re-places all five
                        final, count = _stage(reread), 5
                    errors_flagged += not auto_ok
                    correct_flagged += auto_ok
                    resolved += (not auto_ok) and final == row["truth_stage"]
                    broken += auto_ok and final != row["truth_stage"]
                moved += count
                correct += final == row["truth_stage"]
                severe_missed += row["truth_stage"] == "III/IV" and final != "III/IV"
                if seed == 0 and policy in first_seed and flag:
                    first_seed[policy].append({"id": int(row["id"]), "final_stage": final, "landmarks_moved": count})
            results[policy].append({
                "stage_accuracy": correct / len(rows),
                "severe_misses": severe_missed,
                "flagged_errors_resolved": resolved / errors_flagged if errors_flagged else 1.0,
                "flagged_correct_broken": broken / correct_flagged if correct_flagged else 0.0,
                "landmarks_moved_per_reviewed_tooth": (moved / reviewed) if reviewed else (5.0 if policy.startswith("manual") else 0.0),
            })
    summary_out: dict[str, Any] = {}
    for policy, values in results.items():
        summary_out[policy] = {
            key: {
                "mean": float(np.mean([v[key] for v in values])),
                "p2.5": float(np.percentile([v[key] for v in values], 2.5)),
                "p97.5": float(np.percentile([v[key] for v in values], 97.5)),
            }
            for key in values[0]
        }
    return {"noise_factor": noise_factor, "seeds": seeds, "policies": summary_out, "first_seed": first_seed}


def error_concentration(rows: Rows, share: float = 0.05) -> dict[str, float]:
    """How much of the total landmark error the worst ``share`` of teeth produce."""
    errors = np.sort([float(np.sum(r["radial"])) for r in rows if "radial" in r])[::-1]
    top = max(1, round(share * len(errors)))
    return {"top_5pct_share_of_error": share, "top_5pct_error_share": float(errors[:top].sum() / errors.sum())}


# ----------------------------------------------------------------- figures


def plot_confidence(dev: Rows, ext: Rows, w4_dev: Rows, path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 8.5))
    for ax, title, rows in zip(axes[0], ("Development (cross-fitted OOF)", "External test"), (dev, ext)):
        analysed = [r for r in rows if r.get("p_stage")]
        x = np.asarray([max(r["sigma"]) for r in analysed])
        y = np.asarray([np.mean(r["radial"]) for r in analysed])
        wrong = np.asarray([r["truth_stage"] != r["pred_stage"] for r in analysed])
        ax.scatter(x[~wrong], y[~wrong], s=9, alpha=0.35, color="#277da1", label="stage correct")
        ax.scatter(x[wrong], y[wrong], s=14, alpha=0.75, color="#d62728", label="stage wrong")
        edges = np.quantile(x, np.linspace(0, 1, 11))
        centers, medians = [], []
        for low, high in zip(edges[:-1], edges[1:]):
            members = (x >= low) & (x <= high)
            centers.append(float(np.median(x[members])))
            medians.append(float(np.median(y[members])))
        ax.plot(centers, medians, "-o", color="black", ms=4, lw=1.5, label="decile median")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(f"{title}\nSpearman ρ = {_spearman(x, y):.2f}, n = {len(x)}")
        ax.set_xlabel("Maximum calibrated landmark σ (px, log)")
        ax.set_ylabel("Mean landmark error (px, log)")
        ax.grid(alpha=0.2, which="both")
        ax.legend(fontsize=8, loc="upper left")
    ax = axes[1, 0]
    levels = np.asarray(NOMINAL)
    for label, rows, key, style in (
        ("Week 4 Raw heatmap σ (dev)", w4_dev, "sigma", "--"),
        ("Week 5 before scaling (dev)", dev, "sigma_unscaled", ":"),
        ("Week 5 calibrated (dev)", dev, "sigma", "-"),
        ("Week 5 calibrated (external)", ext, "sigma", "-."),
    ):
        coverage = radial_coverage(rows, key)["all"]
        ax.plot(levels, [coverage[f"{p:.2f}"] for p in levels], style, marker="o", ms=4, label=label)
    ax.plot([0.4, 1], [0.4, 1], color="grey", lw=0.8)
    ax.set_xlim(0.45, 1.0)
    ax.set_ylim(0.3, 1.0)
    ax.set_xlabel("Nominal radial coverage")
    ax.set_ylabel("Empirical coverage")
    ax.set_title("Landmark uncertainty calibration")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2)
    ax = axes[1, 1]
    for label, rows, marker in (("development", dev, "o"), ("external", ext, "s")):
        bins = stage_reliability(rows)["bins"]
        ax.plot([b["mean_confidence"] for b in bins], [b["accuracy"] for b in bins], marker=marker, label=label)
        for b in bins:
            ax.annotate(str(b["n"]), (b["mean_confidence"], b["accuracy"]), fontsize=7, xytext=(3, -9), textcoords="offset points")
    ax.plot([0.3, 1], [0.3, 1], color="grey", lw=0.8)
    ax.set_xlabel("Monte Carlo P(auto stage)")
    ax.set_ylabel("Observed stage accuracy")
    ax.set_title("Stage-probability reliability (labels = teeth per bin)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def risk_curves(rows: Rows, guard: float | None) -> dict[str, list[list[float]]]:
    a = _policy_arrays(rows)

    def point(flag: np.ndarray) -> list[float]:
        accepted = ~flag
        error = float(a["wrong"][accepted].mean()) if accepted.any() else 0.0
        return [float(flag.mean()), error, int((a["miss"] & accepted).sum())]

    return {
        "stage probability (+ severe guard)": [point(policy_flags(rows, ReviewPolicy(float(t), guard), a)) for t in np.arange(0.3, 1.0, 0.01)],
        "Week 4 boundary margin (k sweep)": [point(margin_flags(rows, float(k))) for k in np.arange(0.0, 3.01, 0.05)],
        "max landmark σ (sweep)": [
            point(~a["analysed"] | (a["max_sigma"] >= q)) for q in np.quantile(a["max_sigma"][np.isfinite(a["max_sigma"])], np.linspace(0.0, 1.0, 60))
        ],
    }


def plot_risk(dev: Rows, ext: Rows, policy: ReviewPolicy, points: Mapping[str, Mapping[str, Any]], path: Path) -> dict[str, Any]:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    curves = {}
    for ax, (name, rows) in zip(axes, (("development", dev), ("external", ext))):
        curves[name] = risk_curves(rows, policy.severe_guard)
        for label, values in curves[name].items():
            values = sorted(values)
            ax.plot([v[0] for v in values], [v[1] for v in values], label=label)
        for label, marker in (("Week 5 policy", "*"), ("Week 4 rule as shipped (k=0.45)", "X"), ("CI crosses 15%/33%", "D")):
            p = points[name][label]
            ax.plot(p["review_rate"], 1 - p["accepted_stage_accuracy"], marker, ms=11 if marker == "*" else 8, label=label, color="black" if marker == "*" else None)
        ax.axhline(1 - ACCEPTED_ACCURACY_TARGET, color="grey", ls=":", lw=1)
        ax.set_title(f"{name.capitalize()}: error left in auto-accepted teeth")
        ax.set_xlabel("Share of teeth sent to clinician review")
        ax.grid(alpha=0.2)
    axes[0].set_ylabel("Stage error rate among accepted teeth")
    axes[0].legend(fontsize=7.5)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return curves


def plot_comparison(ladder: Sequence[dict[str, Any]], final_dev: Rows, final_ext: Rows, w4_dev: Rows, w4_ext: Rows, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    width = 0.2
    x = np.arange(len(LANDMARK_NAMES))
    for offset, (label, rows) in zip(
        (-1.5, -0.5, 0.5, 1.5),
        (("Week 4 dev", w4_dev), ("Week 5 dev", final_dev), ("Week 4 external", w4_ext), ("Week 5 external", final_ext)),
    ):
        table = landmark_table(rows)
        axes[0].bar(x + offset * width, [table[n]["mre_px"] for n in LANDMARK_NAMES], width, label=label,
                    color={"Week 4 dev": "#adb5bd", "Week 5 dev": "#277da1", "Week 4 external": "#6c757d", "Week 5 external": "#f3722c"}[label])
    axes[0].set_xticks(x, [SHORT[n] for n in LANDMARK_NAMES])
    axes[0].set_ylabel("MRE (px)")
    axes[0].set_title("Per-landmark MRE")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.2, axis="y")
    labels = [step["label"] for step in ladder]
    axes[1].plot(range(len(ladder)), [step["dev_mre_px"] for step in ladder], "-o", label="development (cross-fitted)")
    axes[1].plot(range(len(ladder)), [step["ext_mre_px"] for step in ladder], "-s", label="external (reported only)")
    for i, step in enumerate(ladder):
        if not step["accepted"]:
            axes[1].annotate("rejected", (i, step["dev_mre_px"]), fontsize=8, xytext=(0, 8), textcoords="offset points", ha="center")
    axes[1].set_xticks(range(len(ladder)), labels, rotation=20, ha="right", fontsize=8)
    axes[1].set_ylabel("Overall MRE (px)")
    axes[1].set_title("Refinement ladder (kept only if dev MRE falls)")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


# --------------------------------------------------------------- examples


def _pick(rows: Rows, keep: Callable[[dict[str, Any]], bool], used: set[int], *, key: Callable[[dict[str, Any]], float], median: bool = False) -> dict[str, Any] | None:
    pool = sorted((r for r in rows if keep(r) and int(r["id"]) not in used), key=key)
    if not pool:
        return None
    choice = pool[len(pool) // 2] if median else pool[-1]
    used.add(int(choice["id"]))
    return choice


def select_cases(ext: Rows, dev: Rows, ext_flags: np.ndarray, dev_flags: np.ndarray, corrected_ext: Mapping[int, str | None], corrected_dev: Mapping[int, str | None]) -> list[tuple[str, str, dict[str, Any], bool, str | None]]:
    """Four representative successes, four corrected errors and four challenging cases."""
    flagged = {int(r["id"]): bool(f) for r, f in zip(ext, ext_flags)} | {int(r["id"]): bool(f) for r, f in zip(dev, dev_flags)}
    after = {**corrected_dev, **corrected_ext}
    used: set[int] = set()
    error = lambda r: float(np.mean(r["radial"])) if "radial" in r else math.inf  # noqa: E731
    ok = lambda r: r["valid"] and r["pred_stage"] == r["truth_stage"]  # noqa: E731
    out: list[tuple[str, str, dict[str, Any], bool, str | None]] = []

    def add(kind: str, why: str, rows: Rows, keep: Callable[[dict[str, Any]], bool], *, median: bool = False, key: Callable[[dict[str, Any]], float] = error) -> None:
        row = _pick(rows, keep, used, key=key, median=median)
        if row is not None:
            out.append((kind, why, row, flagged[int(row["id"])], after.get(int(row["id"]))))

    accepted = lambda r: not flagged[int(r["id"])]  # noqa: E731
    for stage in STAGES:
        add("successful", f"typical accepted Stage {stage} (median error)", ext, lambda r, s=stage: ok(r) and accepted(r) and r["truth_stage"] == s and not r["multirooted"], median=True)
    add("successful", "typical accepted multi-rooted tooth", ext, lambda r: ok(r) and accepted(r) and r["multirooted"], median=True)
    fixed = lambda r: r["valid"] and r["pred_stage"] != r["truth_stage"] and flagged[int(r["id"])] and after.get(int(r["id"])) == r["truth_stage"]  # noqa: E731
    pbl_gap = lambda r: abs(r["pred_pbl"] - r["truth_pbl"]) if r["valid"] else 0.0  # noqa: E731
    add("corrected", "flagged Stage III/IV undercall, resolved by review", ext, lambda r: fixed(r) and r["truth_stage"] == "III/IV", key=pbl_gap)
    add("corrected", "flagged Stage III/IV undercall, resolved by review", dev, lambda r: fixed(r) and r["truth_stage"] == "III/IV", key=pbl_gap)
    add("corrected", "flagged boundary stage error, resolved by review", ext, fixed, key=pbl_gap)
    add("corrected", "flagged overcall, resolved by review", ext, lambda r: fixed(r) and r["pred_stage"] > r["truth_stage"], key=pbl_gap)
    add("challenging", "wrong stage NOT flagged (accepted error)", ext, lambda r: r["valid"] and r["pred_stage"] != r["truth_stage"] and accepted(r), key=pbl_gap)
    add("challenging", "orientation self-check reversed the apex (typical case)", dev, lambda r: bool(r.get("orientation_switched")), median=True)
    add("challenging", "high confidence, large landmark error", ext, lambda r: "radial" in r and r["valid"], key=lambda r: error(r) / max(max(r["sigma"]), 1e-6))
    add("challenging", "largest external landmark error", ext, lambda r: "radial" in r)
    return out


def render_case(number: int, kind: str, why: str, row: dict[str, Any], flagged: bool, corrected_stage: str | None, tooth: dict[str, Any], reasons: Sequence[str]) -> Path:
    image = Image.open(DENPAR / tooth["file_name"]).convert("L")
    x0, y0, x1, y1 = map(float, tooth["bbox"])
    margin_x, margin_y = 0.18 * (x1 - x0), 0.12 * (y1 - y0)
    fig, ax = plt.subplots(figsize=(5.4, 6.6))
    ax.imshow(image, cmap="gray", vmin=0, vmax=255)
    for k, name in enumerate(LANDMARK_NAMES):
        px, py = row["points"][name]
        tx, ty = tooth["truth"][name]
        ax.add_patch(Circle((px, py), 2.4477 * row["sigma"][k], fill=False, ec=COLORS[name], lw=1, ls="--", alpha=0.85))
        ax.plot(px, py, "x", color=COLORS[name], ms=9, mew=2)
        ax.plot(tx, ty, "o", mfc="none", mec=COLORS[name], ms=9, mew=1.5)
        ax.plot([px, tx], [py, ty], color=COLORS[name], lw=0.8, alpha=0.7)
        ax.annotate(SHORT[name], (px, py), color=COLORS[name], fontsize=7, xytext=(5, 4), textcoords="offset points")
    ax.set_xlim(x0 - margin_x, x1 + margin_x)
    ax.set_ylim(y1 + margin_y, y0 - margin_y)
    ax.axis("off")
    split = "external test" if row["fold"] == 0 else f"development fold {row['fold']} (OOF)"
    auto = f"{row['pred_pbl']:.1f}% {row['pred_stage']}" if row["valid"] else "invalid geometry"
    p = row.get("p_stage")
    ci = row.get("ci_calibrated")
    lines = [
        f"Auto: {auto}" + (f"  CI {ci[0]:.0f}–{ci[1]:.0f}%" if ci else ""),
        "P(I/II/III-IV): " + (" / ".join(f"{p[s]:.2f}" for s in STAGES) if p else "n/a"),
        f"Review: {'FLAGGED' if flagged else 'accepted'}" + (f" — {reasons[0]}" if reasons else ""),
        f"Reference: {row['truth_pbl']:.1f}% {row['truth_stage']}"
        + (f"   After simulated review: {corrected_stage}" if flagged and corrected_stage else ""),
        f"Mean landmark error {np.mean(row['radial']):.1f}px; max σ {max(row['sigma']):.1f}px",
    ]
    ax.set_title(f"Case {number} · {kind}: {why}\n{split} · {tooth['file_name']} · tooth {tooth['tooth_id']}", fontsize=8.5)
    ax.text(0.01, 0.01, "\n".join(lines), transform=ax.transAxes, color="white", fontsize=7, va="bottom",
            bbox={"facecolor": "black", "alpha": 0.62, "pad": 3})
    ax.text(0.99, 0.99, "× auto   ○ reference   - - 95% radius", transform=ax.transAxes, color="white", fontsize=7,
            ha="right", va="top", bbox={"facecolor": "black", "alpha": 0.55, "pad": 2})
    output = CASES / f"case_{number:02d}_{kind}.png"
    fig.tight_layout()
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output


def contact_sheet(paths: Sequence[Path], output: Path) -> None:
    columns = 4
    rows = math.ceil(len(paths) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(4.2 * columns, 5.1 * rows))
    for ax in np.ravel(axes):
        ax.axis("off")
    for ax, path in zip(np.ravel(axes), paths):
        ax.imshow(Image.open(path))
    fig.tight_layout()
    fig.savefig(output, dpi=110)
    plt.close(fig)


# ----------------------------------------------------------------- reports


def pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{100 * value:.{digits}f}%"


def fmt_delta(entry: Mapping[str, Any], *, percent: bool = False, digits: int = 2) -> str:
    scale = 100 if percent else 1
    unit = " pp" if percent else ""
    low, high = (scale * v for v in entry["ci95"])
    significant = " **" if low > 0 or high < 0 else ""
    return f"{scale * entry['delta']:+.{digits}f}{unit} [{low:+.{digits}f}, {high:+.{digits}f}]{significant}"


def policy_reasons(row: dict[str, Any], policy: ReviewPolicy) -> list[str]:
    if row.get("p_stage") is None:
        return ["no valid automatic measurement — measure manually"]
    reasons = []
    if row.get("orientation_switched"):
        reasons.append("orientation self-check reversed the apex")
    own = row["p_stage"][row["pred_stage"]]
    if own < policy.min_stage_probability:
        reasons.append(f"P(auto stage) {own:.2f}")
    if policy.severe_guard is not None and row["pred_stage"] != "III/IV" and row["p_stage"]["III/IV"] >= policy.severe_guard:
        reasons.append(f"possible missed III/IV (P={row['p_stage']['III/IV']:.2f})")
    return reasons


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    CASES.mkdir(parents=True, exist_ok=True)
    for old in CASES.glob("case_*.png"):
        old.unlink()
    screening = json.loads((RESULTS / "screening.json").read_text())
    selected, tta = screening["selected_config"], bool(screening["tta_selected"])
    sources = load_sources(selected, tta)
    _, _, dev, ext = load()
    teeth_by_id = {int(t["id"]): t for t in [*dev, *ext]}
    week4_metrics = json.loads((W4_RESULTS / "metrics.json").read_text())
    human_pct = week4_metrics["human_reference_week3"]["raw"]["mean_interround_distance_pct_root"]

    # ---- refinement ladder: greedy, development-only acceptance
    state = System("Week 4 Raw (shipped)", "week4")
    steps: list[tuple[str, dict[str, Any]]] = [("+ Raw/CLAHE 50/50 blend", {"blend": True})]
    if tta:
        steps.append(("+ multi-margin TTA", {"source": "week4_views"}))
    steps.append(("+ orientation self-check", {"orientation": True, "source": "week4_views"}))
    if selected != "week4":
        steps.append((f"+ re-trained '{selected}' weights", {"source": f"{selected}_tta" if tta else selected}))
    reference = evaluate_system(state, dev, ext, sources)
    ladder = [{"label": state.label, "accepted": True, "dev_mre_px": mre(reference["dev"]), "ext_mre_px": mre(reference["ext"]),
               "dev_stage_accuracy": downstream(reference["dev"])["stage_accuracy"], "ext_stage_accuracy": downstream(reference["ext"])["stage_accuracy"]}]
    current = reference
    for label, change in steps:
        candidate_system = replace(current["system"], label=label, **change)
        candidate = evaluate_system(candidate_system, dev, ext, sources)
        accepted = mre(candidate["dev"]) < mre(current["dev"])
        ladder.append({"label": label, "accepted": accepted, "dev_mre_px": mre(candidate["dev"]), "ext_mre_px": mre(candidate["ext"]),
                       "dev_stage_accuracy": downstream(candidate["dev"])["stage_accuracy"], "ext_stage_accuracy": downstream(candidate["ext"])["stage_accuracy"]})
        if accepted:
            current = candidate
    final = current
    final_system: System = final["system"]
    dev_rows, ext_rows = final["dev"], final["ext"]
    w4_dev, w4_ext = reference["dev"], reference["ext"]
    # Week 4 exactly as shipped: its own heatmap sigma and Monte Carlo interval.
    shipped_dev = [sources["week4"]["raw_dev"][int(t["id"])] for t in dev]
    shipped_ext = [sources["week4"]["raw_ext"][int(t["id"])] for t in ext]

    # Learned landmark-specific blend weights, cross-fitted on development only.
    w4 = sources["week4"]
    learned_dev: dict[int, dict[str, Any]] = {}
    for fold in range(1, 6):
        train = [t for t in dev if t["fold"] != fold]
        test = [t for t in dev if t["fold"] == fold]
        weights = fit_blend_weights(train, w4["raw_dev"], w4["clahe_dev"])
        preds = [blend_prediction(w4["raw_dev"][int(t["id"])], w4["clahe_dev"][int(t["id"])], weights)[:2] for t in test]
        learned_dev.update(indexed(score(test, preds)))
    fitted_blend_dev_mre = mre([learned_dev[int(t["id"])] for t in dev])
    fixed_blend_dev_mre = ladder[1]["dev_mre_px"]

    # ---- uncertainty
    add_stage_analysis(dev_rows)
    add_stage_analysis(ext_rows)
    interval_fold_factors = cross_fitted_interval(dev_rows)
    interval_factor = conformal_factor(_interval_rows(dev_rows))
    add_calibrated_interval(ext_rows, interval_factor)
    dev_flags, fold_policies = cross_fitted_policy(dev_rows)
    policy, feasible = fit_policy(dev_rows)
    ext_flags = policy_flags(ext_rows, policy)
    k_matched = fit_margin_k(dev_rows)
    first_run, _ = fit_policy(dev_rows, FIRST_RUN_SEVERE_MISS_TARGET)
    shipped_dev_rate = float(margin_flags(shipped_dev, MARGIN_K).mean())
    same_burden = match_review_rate(dev_rows, shipped_dev_rate, policy.severe_guard)
    points = {}
    for name, rows, flags in (("development", dev_rows, dev_flags), ("external", ext_rows, ext_flags)):
        w4_rows = shipped_dev if name == "development" else shipped_ext
        points[name] = {
            "Week 5 policy": operating_point(rows, flags),
            f"Week 5 first-run target (τ={first_run.min_stage_probability:.2f}, no guard)" if first_run.severe_guard is None
            else f"Week 5 first-run target (τ={first_run.min_stage_probability:.2f}, guard {first_run.severe_guard:.2f})":
                operating_point(rows, policy_flags(rows, first_run)),
            f"Week 5 at Week 4's review burden (τ={same_burden.min_stage_probability:.3f})":
                operating_point(rows, policy_flags(rows, same_burden)),
            "Week 4 rule as shipped (k=0.45)": operating_point(rows, margin_flags(rows, MARGIN_K)),
            f"Week 4 rule re-tuned to {ACCEPTED_ACCURACY_TARGET:.0%} (k={k_matched:.2f})": operating_point(rows, margin_flags(rows, k_matched)),
            "CI crosses 15%/33%": operating_point(rows, crossing_flags(rows)),
            "Week 4 system as shipped (Week 4 Raw + k=0.45)": operating_point(w4_rows, margin_flags(w4_rows, MARGIN_K)),
        }
    sigma_cut = float(np.median([max(r["sigma"]) for r in dev_rows if "sigma" in r]))
    error_cut = float(np.quantile([np.mean(r["radial"]) for r in dev_rows if "radial" in r], 0.90))
    uncertainty = {
        "development": {
            "confidence": confidence_metrics(dev_rows),
            "radial_coverage_calibrated": radial_coverage(dev_rows),
            "radial_coverage_before_scaling": radial_coverage(dev_rows, "sigma_unscaled"),
            "stage_reliability": stage_reliability(dev_rows),
            "high_confidence_failures": high_confidence_failures(dev_rows, sigma_cut, error_cut, dev_flags),
        },
        "external": {
            "confidence": confidence_metrics(ext_rows),
            "radial_coverage_calibrated": radial_coverage(ext_rows),
            "radial_coverage_before_scaling": radial_coverage(ext_rows, "sigma_unscaled"),
            "stage_reliability": stage_reliability(ext_rows),
            "high_confidence_failures": high_confidence_failures(ext_rows, sigma_cut, error_cut, ext_flags),
        },
        "week4_raw": {
            "radial_coverage_development": radial_coverage(shipped_dev),
            "pbl_ci95_coverage_development": week4_metrics["uncertainty"]["development"]["ci95_empirical_coverage"],
            "pbl_ci95_coverage_external": week4_metrics["uncertainty"]["external"]["ci95_empirical_coverage"],
            "spearman_max_sigma_vs_mean_error_development": _spearman(
                [max(r["sigma"]) for r in shipped_dev if r["valid"]], [np.mean(r["radial"]) for r in shipped_dev if r["valid"]]
            ),
            "auroc_max_sigma_stage_error_development": _auroc(
                np.asarray([max(r["sigma"]) for r in shipped_dev if r["valid"]]),
                np.asarray([r["pred_stage"] != r["truth_stage"] for r in shipped_dev if r["valid"]]),
            ),
        },
        "policy": {**policy.to_json(), "targets_met_in_sample": feasible,
                   "target_check": {"development_cross_fitted": target_check(points["development"]["Week 5 policy"]),
                                    "external": target_check(points["external"]["Week 5 policy"])},
                   "targets": {"accepted_stage_accuracy": ACCEPTED_ACCURACY_TARGET, "accepted_severe_misses_per_severe": SEVERE_MISS_TARGET}},
        "policy_cross_fitted_folds": fold_policies,
        "pbl_interval": {
            "conformal_factor": interval_factor,
            "cross_fitted_fold_factors": interval_fold_factors,
            "coverage_monte_carlo_development": float(np.mean([r["ci_covers_truth"] for r in dev_rows if r.get("ci")])),
            "coverage_monte_carlo_external": float(np.mean([r["ci_covers_truth"] for r in ext_rows if r.get("ci")])),
            "coverage_calibrated_development": float(np.mean([r["ci_calibrated_covers_truth"] for r in dev_rows if r.get("ci")])),
            "coverage_calibrated_external": float(np.mean([r["ci_calibrated_covers_truth"] for r in ext_rows if r.get("ci")])),
            "median_width_calibrated_development_pp": float(np.median([r["ci_calibrated"][1] - r["ci_calibrated"][0] for r in dev_rows if r.get("ci")])),
            "median_width_calibrated_external_pp": float(np.median([r["ci_calibrated"][1] - r["ci_calibrated"][0] for r in ext_rows if r.get("ci")])),
        },
        "operating_points": points,
    }
    plot_confidence(dev_rows, ext_rows, shipped_dev, REPORTS / "confidence_vs_error.png")
    curves = plot_risk(dev_rows, ext_rows, policy, points, REPORTS / "risk_coverage.png")

    # ---- clinical
    add_image_features([*dev, *ext])
    add_sharpness([*dev, *ext])
    cuts = {
        "rms_contrast": float(np.quantile([t["rms_contrast"] for t in dev], 0.25)),
        "sharpness": float(np.quantile([t["sharpness"] for t in dev], 0.25)),
    }
    corrections = {
        name: simulate_corrections(rows, flags, teeth_by_id, human_pct, noise_factor=factor)
        for name, rows, flags, factor in (
            ("external", ext_rows, ext_flags, 1.0),
            ("development", dev_rows, dev_flags, 1.0),
            ("external_double_reader_noise", ext_rows, ext_flags, 2.0),
        )
    }
    after = {
        split: {e["id"]: e["final_stage"] for e in corrections[split]["first_seed"]["move visibly wrong"]}
        for split in ("external", "development")
    }
    severe_cases = []
    for rows, flags in ((dev_rows, dev_flags), (ext_rows, ext_flags)):
        culprit = {r["id"]: r for r in culprits(rows, teeth_by_id)["records"]}
        for row, flag in zip(rows, flags):
            if row["truth_stage"] == "III/IV" and (not row["valid"] or row["pred_stage"] != "III/IV"):
                tooth = teeth_by_id[int(row["id"])]
                severe_cases.append({
                    "split": "external" if row["fold"] == 0 else "development",
                    "id": int(row["id"]), "image": row["image"],
                    "truth_pbl": row["truth_pbl"], "auto_pbl": row.get("pred_pbl"), "auto_stage": row.get("pred_stage"),
                    "p_severe": row["p_stage"]["III/IV"] if row.get("p_stage") else None,
                    "flagged": bool(flag), "reasons": policy_reasons(row, policy),
                    "fixed_by": culprit.get(int(row["id"]), {}).get("fixed_by"),
                    "multirooted": bool(tooth["multirooted"]), "tilted": bool(tooth["tilted"]),
                    "anterior": tooth["site"] == "Anterior",
                    "after_review": after["external" if row["fold"] == 0 else "development"].get(int(row["id"])),
                })
    clinical = {
        "external_stage_confusion_rows_truth_cols_pred": downstream(ext_rows)["confusion_rows_truth_cols_pred"],
        "subgroups_external": subgroups(ext_rows, w4_ext, ext_flags, ext, cuts),
        "subgroups_development": subgroups(dev_rows, w4_dev, dev_flags, dev, cuts),
        "image_condition_cuts_from_development": cuts,
        "culprits_external": culprits(ext_rows, teeth_by_id),
        "culprits_development": culprits(dev_rows, teeth_by_id),
        "severe_undercalls": severe_cases,
        "correction_simulation": {k: {kk: vv for kk, vv in v.items() if kk != "first_seed"} for k, v in corrections.items()},
        "human_noise_pct_root": human_pct,
        "error_concentration_week4_dev": error_concentration(w4_dev),
    }

    # ---- 12 examples
    cases = select_cases(ext_rows, dev_rows, ext_flags, dev_flags, after["external"], after["development"])
    manifest, paths = [], []
    for number, (kind, why, row, flagged, corrected_stage) in enumerate(cases, 1):
        tooth = teeth_by_id[int(row["id"])]
        reasons = policy_reasons(row, policy) if flagged else []
        path = render_case(number, kind, why, row, flagged, corrected_stage, tooth, reasons)
        paths.append(path)
        manifest.append({
            "case": number, "kind": kind, "why": why, "split": "external" if row["fold"] == 0 else "development_oof",
            "tooth_id": int(row["id"]), "image": row["image"], "truth_stage": row["truth_stage"],
            "auto_stage": row.get("pred_stage"), "truth_pbl": row["truth_pbl"], "auto_pbl": row.get("pred_pbl"),
            "auto_ci95": row.get("ci_calibrated"), "stage_probabilities": row.get("p_stage"), "flagged": flagged,
            "review_reasons": reasons, "stage_after_simulated_review": corrected_stage if flagged else None,
            "mean_landmark_error_px": float(np.mean(row["radial"])), "max_sigma_px": float(max(row["sigma"])),
            "multirooted": bool(tooth["multirooted"]), "tilted": bool(tooth["tilted"]), "figure": path.name,
        })
    contact_sheet(paths, CASES / "overview.png")
    (CASES / "manifest.json").write_text(json.dumps(manifest, indent=2, default=float) + "\n")

    # ---- calibration and metrics
    parameters = final["parameters"]
    config = final_system.source
    config_name = selected if config not in {"week4", "week4_views"} else "week4"
    use_tta = config != "week4"
    calibration = {
        "model": {
            "config": config_name,
            "tta_margins": list(TTA_MARGINS) if use_tta and tta else [0.08],
            "raw_checkpoints": [str(checkpoint(config_name, "raw", f).relative_to(ROOT)) for f in range(1, 6)],
            "clahe_checkpoints": [str(checkpoint(config_name, "clahe", f).relative_to(ROOT)) for f in range(1, 6)],
        },
        "blend_raw_weight": {n: parameters["raw_weight"] for n in LANDMARK_NAMES},
        "sigma_scale": parameters["sigma_scale"],
        "orientation_switch_ratio": parameters["orientation_switch_ratio"] if final_system.orientation else None,
        "review_policy": policy.to_json(),
        "pbl_interval_factor": interval_factor,
        "fit_source": "all development out-of-fold predictions; external test never used for fitting",
        "external_labels_used": False,
        "seed": SEED,
        "fold_parameters": final["fold_parameters"],
    }
    (REPORTS / "calibration.json").write_text(json.dumps(calibration, indent=2) + "\n")
    comparison = {
        "development_oof": paired_bootstrap(w4_dev, dev_rows),
        "development_oof_excluding_screen_fold_1": paired_bootstrap(
            [r for r in w4_dev if r["fold"] != 1], [r for r in dev_rows if r["fold"] != 1]
        ),
        "external": paired_bootstrap(w4_ext, ext_rows),
    }
    metrics = {
        "protocol": {
            "split": "unchanged week4/data/denpar_split_5fold.json (radiograph-level)",
            "development": "5-fold cross-fitted: fold k uses parameters fitted on the other four folds",
            "external": "scored once with parameters fitted on all development OOF rows",
            "external_labels_used_for_fitting": False,
            "screen": "configurations screened on development fold 1 only",
            "acceptance": "a refinement step is kept only if it lowers cross-fitted development MRE",
        },
        "screening": {k: {kk: vv for kk, vv in v.items() if kk != "vs_week4_saved"} for k, v in screening["candidates"].items()},
        "screening_vs_week4": {k: v["vs_week4_saved"] for k, v in screening["candidates"].items() if v.get("vs_week4_saved")},
        "selected_config": selected,
        "screening_n_teeth": screening["n_teeth"],
        "seed_noise_floor_px": screening.get("seed_noise_floor_px", 0.1),
        "tta_selected": tta,
        "ladder": ladder,
        "final_system": {"label": final_system.label, "source": final_system.source, "blend": final_system.blend, "orientation": final_system.orientation},
        "blend_selection_development": {"fixed_50_50_mre_px": fixed_blend_dev_mre, "fitted_per_landmark_mre_px": fitted_blend_dev_mre},
        "orientation": {
            "switch_ratio": parameters["orientation_switch_ratio"],
            "development_switched": int(sum(bool(r.get("orientation_switched")) for r in dev_rows)),
            "external_switched": int(sum(bool(r.get("orientation_switched")) for r in ext_rows)),
            "development_switched_with_wrong_metadata": int(sum(
                bool(r.get("orientation_switched")) and teeth_by_id[int(r["id"])]["orientation_error_deg"] > 45 for r in dev_rows
            )),
            "development_wrong_metadata": int(sum(t["orientation_error_deg"] > 45 for t in dev)),
            "external_wrong_metadata": int(sum(t["orientation_error_deg"] > 45 for t in ext)),
            "external_switched_with_wrong_metadata": int(sum(
                bool(r.get("orientation_switched")) and teeth_by_id[int(r["id"])]["orientation_error_deg"] > 45 for r in ext_rows
            )),
        },
        "week4_raw_development_oof": summary(w4_dev),
        "week4_raw_external": summary(w4_ext),
        "refined_development_oof": summary(dev_rows),
        "refined_external": summary(ext_rows),
        "paired_comparison_refined_minus_week4": comparison,
        "uncertainty": uncertainty,
        "risk_coverage_curves": curves,
        "clinical": clinical,
    }
    (REPORTS / "metrics.json").write_text(json.dumps(metrics, indent=2, allow_nan=False, default=float) + "\n")
    plot_comparison(ladder, dev_rows, ext_rows, w4_dev, w4_ext, REPORTS / "model_comparison.png")
    (REPORTS / "refined_predictions.json").write_text(json.dumps({"development_oof": dev_rows, "external": ext_rows}, default=float) + "\n")

    from week5.report import write_reports

    write_reports(metrics, calibration, manifest)
    print(json.dumps({
        "ladder": ladder,
        "external": comparison["external"]["mre_px"],
        "policy": policy.to_json(),
        "operating_points_external": points["external"],
    }, indent=2, default=float))


if __name__ == "__main__":
    main()
