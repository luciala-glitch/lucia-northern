"""Regenerate every Week 4 metric table and figure from the saved split and weights.

Evaluation design (fixed before looking at results):

* Development = DenPAR Training + Validation, 5 radiograph-level folds. Each
  learned fold model predicts only the radiographs held out of its training.
* External test = DenPAR Testing. It is never used for training, thresholds,
  or rule selection; all five fold models are averaged there.
* Human reference = Week 3 round-1-vs-round-2 readings of 15 teeth (RAW).

Run ``python -m week4.benchmark`` after ``week4/train_all.sh``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

from week3.image_processing import preprocess  # noqa: E402
from week3.pbl_calculator import PBLValidationError, calculate_tooth_pbl, long_axis  # noqa: E402
from week3.statistics import agreement  # noqa: E402
from week4.constants import LANDMARK_NAMES, SEED, STAGE_BOUNDARIES  # noqa: E402
from week4.errors import EmptyPredictionError  # noqa: E402
from week4.metrics import STAGE_CODE  # noqa: E402
from week4.predict import ClassicalLandmarkDetector  # noqa: E402
from week4.train import DATASET, DENPAR, ROOT, SPLIT  # noqa: E402
from week4.training import BOX_MARGIN, INPUT_SIZE, CanonicalCrop  # noqa: E402
from week4.uncertainty import needs_manual_review, pbl_confidence_interval, to_tooth_landmarks  # noqa: E402

WEIGHTS = Path(os.environ.get("PBL_WEIGHTS", ROOT / "week4" / "weights"))
RESULTS = Path(os.environ.get("PBL_RESULTS", ROOT / "week4" / "reports" / "results"))
HUMAN = ROOT / "week3" / "reports" / "collected_study" / "exports" / "measurements.json"
SDR_THRESHOLDS = (2, 5, 10)
PRESPECIFIED_MAX_SIGMA_PX = 5.0
BOOTSTRAP = 2000
DEGRADATIONS: tuple[tuple[str, str, float], ...] = (
    ("none", "none", 0.0),
    ("blur σ=1", "blur", 1.0),
    ("blur σ=2", "blur", 2.0),
    ("blur σ=3", "blur", 3.0),
    ("noise σ=10", "noise", 10.0),
    ("noise σ=20", "noise", 20.0),
    ("resolution 0.75×", "scale", 0.75),
    ("resolution 0.5×", "scale", 0.5),
)

Points = dict[str, tuple[float, float]]


# --------------------------------------------------------------------------- data


def load() -> tuple[dict[str, Any], dict[int, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dataset = json.loads(DATASET.read_text())
    split = json.loads(SPLIT.read_text())
    images = {int(i["id"]): i for i in dataset["images"]}
    fold_of = {i: int(f["fold"]) for f in split["folds"] for i in f["test_image_ids"]}
    development, external = [], []
    for annotation in dataset["annotations"]:
        image = images[int(annotation["image_id"])]
        tooth = {
            **annotation,
            "file_name": image["file_name"],
            "partition": image["partition"],
            "denpar_id": image["denpar_id"],
            "arch": image["arch"],
            "site": image["site"],
            "truth": {name: tuple(annotation["mean"][name]) for name in LANDMARK_NAMES},
        }
        if image["partition"] == "Testing":
            tooth["fold"] = 0
            external.append(tooth)
        else:
            tooth["fold"] = fold_of[int(annotation["image_id"])]
            development.append(tooth)
    return split, images, development, external


def by_image(teeth: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tooth in teeth:
        grouped[tooth["file_name"]].append(tooth)
    return dict(sorted(grouped.items()))


def degrade(image: Image.Image, kind: str, level: float, seed: int) -> Image.Image:
    gray = image.convert("L")
    if kind == "none":
        return gray
    if kind == "blur":
        return gray.filter(ImageFilter.GaussianBlur(radius=level))
    if kind == "noise":
        rng = np.random.default_rng(seed)
        pixels = np.asarray(gray, dtype=np.float32) + rng.normal(0, level, (gray.height, gray.width))
        return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))
    if kind == "scale":
        small = gray.resize(
            (max(1, round(gray.width * level)), max(1, round(gray.height * level))),
            Image.Resampling.BILINEAR,
        )
        return small.resize(gray.size, Image.Resampling.BILINEAR)
    raise ValueError(kind)


# ---------------------------------------------------------------------- detectors


def canonical_local(tooth: dict[str, Any]) -> Points:
    """Ground truth in the canonical crop frame; geometry only, no pixels needed."""
    x0, y0, x1, y1 = map(float, tooth["bbox"])
    px, py = (x1 - x0) * BOX_MARGIN, (y1 - y0) * BOX_MARGIN
    box = tuple(float(round(v)) for v in (x0 - px, y0 - py, x1 + px, y1 + py))
    crop = CanonicalCrop(Image.new("L", INPUT_SIZE), box, not tooth["mesial_on_left"], not tooth["apex_at_bottom"])  # type: ignore[arg-type]
    return {name: crop.to_local(tooth["truth"][name]) for name in LANDMARK_NAMES}


def fit_baseline_shape(training: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    return ClassicalLandmarkDetector.fit_shape([canonical_local(t) for t in training], INPUT_SIZE)


def run_baseline(
    teeth: list[dict[str, Any]],
    shape: tuple[np.ndarray, np.ndarray],
    transform: Callable[[Image.Image, str], Image.Image] | None = None,
) -> list[tuple[Points, dict[str, float]] | None]:
    out: dict[int, tuple[Points, dict[str, float]] | None] = {}
    for file_name, group in by_image(teeth).items():
        image = Image.open(DENPAR / file_name).convert("L")
        if transform is not None:
            image = transform(image, file_name)
        for tooth in group:
            detector = ClassicalLandmarkDetector(
                apex_at_bottom=tooth["apex_at_bottom"],
                mesial_on_left=tooth["mesial_on_left"],
                mean_shape=shape[0],
                shape_sd=shape[1],
            )
            try:
                out[int(tooth["id"])] = detector.predict(image, tuple(int(v) for v in tooth["bbox"]))
            except EmptyPredictionError:
                out[int(tooth["id"])] = None
    return [out[int(t["id"])] for t in teeth]


def run_baseline_oof(teeth: list[dict[str, Any]]) -> list[tuple[Points, dict[str, float]] | None]:
    """The mean shape for fold k is fitted only on the other four folds."""
    out: dict[int, tuple[Points, dict[str, float]] | None] = {}
    for fold in range(1, 6):
        members = [t for t in teeth if t["fold"] == fold]
        shape = fit_baseline_shape([t for t in teeth if t["fold"] != fold])
        for tooth, prediction in zip(members, run_baseline(members, shape)):
            out[int(tooth["id"])] = prediction
    return [out[int(t["id"])] for t in teeth]


def learned(paths: Sequence[Path]) -> Any:
    from week4.learned import LearnedHeatmapDetector

    return LearnedHeatmapDetector(list(paths))


def run_learned(
    detector: Any,
    teeth: list[dict[str, Any]],
    *,
    input_condition: str | None = None,
    transform: Callable[[Image.Image, str], Image.Image] | None = None,
) -> list[tuple[Points, dict[str, float]]]:
    condition = input_condition or detector.condition
    out: dict[int, tuple[Points, dict[str, float]]] = {}
    for file_name, group in by_image(teeth).items():
        image = Image.open(DENPAR / file_name).convert("L")
        if transform is not None:
            image = transform(image, file_name)
        source = preprocess(image, condition)
        crops = []
        for tooth in group:
            detector.apex_at_bottom = tooth["apex_at_bottom"]
            detector.mesial_on_left = tooth["mesial_on_left"]
            crops.append(detector.crop(source, tuple(int(v) for v in tooth["bbox"]), preprocessed=True))
        for tooth, prediction in zip(group, detector.predict_crops(crops)):
            out[int(tooth["id"])] = prediction
    return [out[int(t["id"])] for t in teeth]


def run_learned_oof(teeth: list[dict[str, Any]], condition: str) -> list[tuple[Points, dict[str, float]]]:
    """Out-of-fold predictions: each fold model sees only radiographs it never trained on."""
    out: dict[int, tuple[Points, dict[str, float]]] = {}
    for fold in range(1, 6):
        members = [t for t in teeth if t["fold"] == fold]
        detector = learned([WEIGHTS / f"{condition}_fold_{fold}.pt"])
        for tooth, prediction in zip(members, run_learned(detector, members)):
            out[int(tooth["id"])] = prediction
    return [out[int(t["id"])] for t in teeth]


# ------------------------------------------------------------------------ scoring


def score(
    teeth: list[dict[str, Any]],
    predictions: Sequence[tuple[Points, dict[str, float]] | None],
    *,
    with_ci: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    for tooth, prediction in zip(teeth, predictions):
        truth = tooth["truth"]
        truth_result = calculate_tooth_pbl(to_tooth_landmarks(truth))
        axis = np.asarray(long_axis(to_tooth_landmarks(truth)))
        normal = np.asarray([-axis[1], axis[0]])
        root_px = float(np.linalg.norm(np.asarray(truth["apex"]) - np.mean([truth["mesial_cej"], truth["distal_cej"]], axis=0)))
        row: dict[str, Any] = {
            "id": int(tooth["id"]),
            "image": tooth["file_name"],
            "fold": tooth["fold"],
            "root_px": root_px,
            "truth_pbl": truth_result.pbl_max_pct,
            "truth_stage": truth_result.stage,
            "multirooted": tooth["multirooted"],
            "tilted": tooth["tilted"],
            "arch": tooth["arch"],
            "valid": False,
            "invalid_reason": None,
        }
        if prediction is None:
            row["invalid_reason"] = "EmptyPredictionError"
            rows.append(row)
            continue
        points, sigma = prediction
        error = np.asarray([np.asarray(points[n]) - np.asarray(truth[n]) for n in LANDMARK_NAMES])
        row["radial"] = np.linalg.norm(error, axis=1).tolist()
        row["along"] = np.abs(error @ axis).tolist()
        row["perpendicular"] = np.abs(error @ normal).tolist()
        row["signed_along"] = (error @ axis).tolist()
        row["sigma"] = [float(sigma[n]) for n in LANDMARK_NAMES]
        row["points"] = {n: list(points[n]) for n in LANDMARK_NAMES}
        try:
            result = calculate_tooth_pbl(to_tooth_landmarks(points))
        except PBLValidationError as exc:
            row["invalid_reason"] = type(exc).__name__
            rows.append(row)
            continue
        row.update(valid=True, pred_pbl=result.pbl_max_pct, pred_stage=result.stage)
        if with_ci:
            try:
                interval = pbl_confidence_interval(points, sigma, draws=1000, seed=SEED + int(tooth["id"]))
                flagged, reasons = needs_manual_review(interval, sigma, maximum_landmark_px=PRESPECIFIED_MAX_SIGMA_PX)
                row.update(
                    ci=[interval.lower, interval.upper],
                    ci_valid_draws=interval.valid_draws,
                    ci_crosses_boundary=any(interval.lower < b <= interval.upper for b in STAGE_BOUNDARIES),
                    prespecified_flag=flagged,
                )
            except EmptyPredictionError:
                row.update(ci=None, ci_crosses_boundary=True, prespecified_flag=True)
        rows.append(row)
    return rows


def landmark_table(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    scored = [r for r in rows if "radial" in r]
    table = {}
    for k, name in enumerate(LANDMARK_NAMES):
        radial = np.asarray([r["radial"][k] for r in scored])
        table[name] = {
            "n": len(radial),
            "mre_px": float(radial.mean()),
            **{f"sdr_{t}px": float((radial <= t).mean()) for t in SDR_THRESHOLDS},
            "along_mae_px": float(np.mean([r["along"][k] for r in scored])),
            "perpendicular_mae_px": float(np.mean([r["perpendicular"][k] for r in scored])),
            "mre_pct_root": float(np.mean([r["radial"][k] / r["root_px"] * 100 for r in scored])),
        }
    all_radial = np.asarray([v for r in scored for v in r["radial"]])
    table["all"] = {
        "n": len(scored),
        "mre_px": float(all_radial.mean()),
        **{f"sdr_{t}px": float((all_radial <= t).mean()) for t in SDR_THRESHOLDS},
        "along_mae_px": float(np.mean([v for r in scored for v in r["along"]])),
        "perpendicular_mae_px": float(np.mean([v for r in scored for v in r["perpendicular"]])),
        "mre_pct_root": float(np.mean([v / r["root_px"] * 100 for r in scored for v in r["radial"]])),
    }
    return table


def downstream(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r["valid"]]
    truth = np.asarray([r["truth_pbl"] for r in valid])
    pred = np.asarray([r["pred_pbl"] for r in valid])
    ts = np.asarray([STAGE_CODE[r["truth_stage"]] for r in valid])
    ps = np.asarray([STAGE_CODE[r["pred_stage"]] for r in valid])
    stats = agreement(truth, pred, ts, ps)
    confusion = np.zeros((3, 3), dtype=int)
    for a, b in zip(ts, ps):
        confusion[a, b] += 1
    severe = ts == 2
    return {
        "n_total": len(rows),
        "n_valid": len(valid),
        "invalid_rate": 1 - len(valid) / len(rows),
        "icc_2_1": stats.icc_2_1,
        "weighted_kappa": stats.weighted_kappa,
        "bias_pp": stats.bias,
        "loa": [stats.loa_lower, stats.loa_upper],
        "loa_width_pp": stats.loa_upper - stats.loa_lower,
        "mae_pp": float(np.mean(np.abs(pred - truth))),
        "stage_accuracy": float(np.mean(ts == ps)),
        "confusion_rows_truth_cols_pred": confusion.tolist(),
        "severe_n": int(severe.sum()),
        "severe_undercalled": int(np.sum(severe & (ps < 2))),
        "overcalled_any": int(np.sum(ps > ts)),
        "undercalled_any": int(np.sum(ps < ts)),
    }


def mean_sd(values: Iterable[float]) -> tuple[float, float]:
    array = np.asarray(list(values), dtype=float)
    return float(array.mean()), float(array.std(ddof=1)) if len(array) > 1 else 0.0


def per_fold(rows: list[dict[str, Any]]) -> dict[str, Any]:
    folds = sorted({r["fold"] for r in rows})
    landmark = [landmark_table([r for r in rows if r["fold"] == f]) for f in folds]
    agreement_rows = [downstream([r for r in rows if r["fold"] == f]) for f in folds]
    summary: dict[str, Any] = {"landmarks": {}, "downstream": {}}
    for name in (*LANDMARK_NAMES, "all"):
        summary["landmarks"][name] = {
            key: mean_sd(t[name][key] for t in landmark)
            for key in landmark[0][name]
            if key != "n"
        }
    for key in ("icc_2_1", "weighted_kappa", "bias_pp", "loa_width_pp", "mae_pp", "stage_accuracy", "invalid_rate"):
        summary["downstream"][key] = mean_sd(a[key] for a in agreement_rows)
    return summary


def clustered_ci(rows: list[dict[str, Any]], statistic: Callable[[list[dict[str, Any]]], float], seed: int = SEED) -> tuple[float, float]:
    """Percentile CI resampling whole radiographs (teeth in one image are correlated)."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r["image"]].append(r)
    keys = sorted(groups)
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(BOOTSTRAP):
        sample = [r for k in rng.choice(keys, len(keys)) for r in groups[k]]
        try:
            values.append(statistic(sample))
        except (ValueError, ZeroDivisionError):
            continue
    low, high = np.percentile(values, [2.5, 97.5])
    return float(low), float(high)


def human_reference() -> dict[str, Any]:
    records = json.loads(HUMAN.read_text())
    out: dict[str, Any] = {}
    for condition in ("raw", "he", "clahe"):
        pairs: dict[int, dict[int, Any]] = defaultdict(dict)
        for r in records:
            if r["condition"] == condition:
                pairs[int(r["tooth_id"])][int(r["round"])] = r
        first = [pairs[t][1]["metrics"] for t in sorted(pairs)]
        second = [pairs[t][2]["metrics"] for t in sorted(pairs)]
        stats = agreement(
            [m["pbl_max_pct"] for m in first],
            [m["pbl_max_pct"] for m in second],
            [STAGE_CODE[m["stage"]] for m in first],
            [STAGE_CODE[m["stage"]] for m in second],
        )
        noise = {}
        for name in LANDMARK_NAMES:
            side, kind = (name.split("_") + [""])[:2]
            def get(r: dict[str, Any]) -> np.ndarray:
                lm = r["landmarks"]
                return np.asarray(lm["apex"] if name == "apex" else lm[side][kind], dtype=float)
            distances = []
            for t in sorted(pairs):
                distances.append(float(np.linalg.norm(get(pairs[t][1]) - get(pairs[t][2]))))
            noise[name] = float(np.mean(distances))
        roots = []
        for t in sorted(pairs):
            lm = pairs[t][1]["landmarks"]
            mid = (np.asarray(lm["mesial"]["cej"]) + np.asarray(lm["distal"]["cej"])) / 2
            roots.append(float(np.linalg.norm(np.asarray(lm["apex"]) - mid)))
        out[condition] = {
            "n_teeth": stats.n,
            "icc_2_1": stats.icc_2_1,
            "weighted_kappa": stats.weighted_kappa,
            "bias_pp": stats.bias,
            "loa": [stats.loa_lower, stats.loa_upper],
            "loa_width_pp": stats.loa_upper - stats.loa_lower,
            "mean_interround_distance_px": noise,
            "mean_interround_distance_pct_root": {
                k: v / float(np.mean(roots)) * 100 for k, v in noise.items()
            },
        }
    return out


# ---------------------------------------------------------------- uncertainty


def uncertainty_analysis(dev: list[dict[str, Any]], ext: list[dict[str, Any]]) -> dict[str, Any]:
    def spearman(a: Sequence[float], b: Sequence[float]) -> float:
        ra = np.argsort(np.argsort(a))
        rb = np.argsort(np.argsort(b))
        return float(np.corrcoef(ra, rb)[0, 1])

    def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [r for r in rows if r["valid"] and r.get("ci")]
        error = [abs(r["pred_pbl"] - r["truth_pbl"]) for r in valid]
        max_sigma = [max(r["sigma"]) for r in valid]
        width = [r["ci"][1] - r["ci"][0] for r in valid]
        landmark_sigma = [s for r in rows if "sigma" in r for s in r["sigma"]]
        landmark_error = [e for r in rows if "sigma" in r for e in r["radial"]]
        per_landmark = {
            name: spearman([r["sigma"][k] for r in rows if "sigma" in r], [r["radial"][k] for r in rows if "sigma" in r])
            for k, name in enumerate(LANDMARK_NAMES)
        }
        inside = [r["ci"][0] <= r["truth_pbl"] <= r["ci"][1] for r in valid]
        z = [e / s for r in rows if "sigma" in r for e, s in zip(r["radial"], r["sigma"]) if s > 0]
        return {
            "n": len(valid),
            "spearman_landmark_sigma_vs_radial_error": spearman(landmark_sigma, landmark_error),
            "spearman_per_landmark": per_landmark,
            "spearman_max_sigma_vs_abs_pbl_error": spearman(max_sigma, error),
            "spearman_ci_width_vs_abs_pbl_error": spearman(width, error),
            "pearson_ci_width_vs_abs_pbl_error": float(np.corrcoef(width, error)[0, 1]),
            "ci95_empirical_coverage": float(np.mean(inside)),
            "median_ci_width_pp": float(np.median(width)),
            # For an isotropic 2-D Gaussian, radial error / sigma has median 1.177.
            "median_radial_error_over_sigma": float(np.median(z)),
        }

    def curve(rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], float]) -> dict[str, list[float]]:
        valid = sorted([r for r in rows if r["valid"] and r.get("ci")], key=key)
        correct = np.asarray([r["pred_stage"] == r["truth_stage"] for r in valid])
        error = np.asarray([abs(r["pred_pbl"] - r["truth_pbl"]) for r in valid])
        n = np.arange(1, len(valid) + 1)
        return {
            "coverage": (n / len(rows)).tolist(),
            "stage_accuracy": (np.cumsum(correct) / n).tolist(),
            "mae_pp": (np.cumsum(error) / n).tolist(),
        }

    def max_coverage(c: dict[str, list[float]], target: float = 0.90) -> float | None:
        ok = [cov for cov, acc in zip(c["coverage"], c["stage_accuracy"]) if acc >= target]
        return max(ok) if ok else None

    def boundary_margin(r: dict[str, Any]) -> float:
        # Smaller = closer to a stage boundary relative to the interval half-width.
        half = max((r["ci"][1] - r["ci"][0]) / 2, 1e-6)
        return -min(abs(r["pred_pbl"] - b) for b in STAGE_BOUNDARIES) / half

    scores = {
        "ci_width": lambda r: r["ci"][1] - r["ci"][0],
        "max_landmark_sigma": lambda r: max(r["sigma"]),
        "boundary_margin": boundary_margin,
    }
    curves = {split: {name: curve(rows, key) for name, key in scores.items()} for split, rows in (("development", dev), ("external", ext))}

    def rule(rows: list[dict[str, Any]], max_sigma_px: float | None, use_boundary: bool) -> dict[str, Any]:
        accepted = []
        for r in rows:
            if not r["valid"] or not r.get("ci"):
                continue
            if use_boundary and r["ci_crosses_boundary"]:
                continue
            if max_sigma_px is not None and max(r["sigma"]) > max_sigma_px:
                continue
            accepted.append(r)
        severe_missed = sum(r["truth_stage"] == "III/IV" and r["pred_stage"] != "III/IV" for r in accepted)
        return {
            "coverage": len(accepted) / len(rows),
            "accepted": len(accepted),
            "stage_accuracy": float(np.mean([r["pred_stage"] == r["truth_stage"] for r in accepted])) if accepted else None,
            "mae_pp": float(np.mean([abs(r["pred_pbl"] - r["truth_pbl"]) for r in accepted])) if accepted else None,
            "accepted_severe_undercalls": int(severe_missed),
        }

    # Tune the sigma threshold on development out-of-fold predictions only.
    grid = sorted({round(float(s), 1) for r in dev if "sigma" in r for s in [max(r["sigma"])]})
    tuned = None
    for threshold in grid:
        result = rule(dev, threshold, True)
        if result["stage_accuracy"] is not None and result["stage_accuracy"] >= 0.90:
            tuned = threshold
    def margin_rule(rows: list[dict[str, Any]], k: float) -> dict[str, Any]:
        accepted = [r for r in rows if r["valid"] and r.get("ci") and -boundary_margin(r) >= k]
        return {
            "coverage": len(accepted) / len(rows),
            "accepted": len(accepted),
            "stage_accuracy": float(np.mean([r["pred_stage"] == r["truth_stage"] for r in accepted])) if accepted else None,
            "mae_pp": float(np.mean([abs(r["pred_pbl"] - r["truth_pbl"]) for r in accepted])) if accepted else None,
            "accepted_severe_undercalls": int(sum(r["truth_stage"] == "III/IV" and r["pred_stage"] != "III/IV" for r in accepted)),
        }

    # Smallest margin k (|PBL - nearest boundary| / CI half-width) giving >=90%
    # stage accuracy on development; then frozen and applied to the external set.
    margin_k = None
    for k in np.round(np.arange(0.0, 3.01, 0.05), 2):
        result = margin_rule(dev, float(k))
        if result["stage_accuracy"] is not None and result["stage_accuracy"] >= 0.90:
            margin_k = float(k)
            break
    rules = {
        "margin_tuned_on_development": {
            "k": margin_k,
            "development": margin_rule(dev, margin_k) if margin_k is not None else None,
            "external": margin_rule(ext, margin_k) if margin_k is not None else None,
        },
        "prespecified_boundary_or_sigma_gt_5px": {
            "development": rule(dev, PRESPECIFIED_MAX_SIGMA_PX, True),
            "external": rule(ext, PRESPECIFIED_MAX_SIGMA_PX, True),
        },
        "boundary_only": {"development": rule(dev, None, True), "external": rule(ext, None, True)},
        "tuned_on_development": {
            "max_sigma_px": tuned,
            "development": rule(dev, tuned, True) if tuned is not None else None,
            "external": rule(ext, tuned, True) if tuned is not None else None,
        },
    }
    return {
        "development": summarise(dev),
        "external": summarise(ext),
        "rules": rules,
        "max_coverage_at_90pct_stage_accuracy": {
            split: {name: max_coverage(c) for name, c in by_score.items()} for split, by_score in curves.items()
        },
        "curves": curves,
    }


# --------------------------------------------------------------------- subgroups


def add_image_features(teeth: list[dict[str, Any]]) -> None:
    """RMS contrast of the tooth box, computed from pixels rather than labels.

    Two pixel-based "obscured CEJ" proxies (saturation near the CEJ and crown
    radiopacity) were tried and visually rejected: they mostly flagged film
    markers, wires and image borders. DenPAR has no restoration labels, so that
    subgroup is reported as not estimable instead of with a misleading proxy.
    """
    for file_name, group in by_image(teeth).items():
        gray = np.asarray(Image.open(DENPAR / file_name).convert("L"), dtype=np.float32)
        for tooth in group:
            x0, y0, x1, y1 = tooth["bbox"]
            tooth["rms_contrast"] = float(gray[y0:y1, x0:x1].std() / 255)
            # Angle between the manual long axis and the direction the arch metadata
            # implies. >45° means the detector was given the wrong orientation.
            mid = np.mean([tooth["truth"]["mesial_cej"], tooth["truth"]["distal_cej"]], axis=0)
            axis = np.asarray(tooth["truth"]["apex"]) - mid
            expected = np.asarray([0.0, 1.0 if tooth["apex_at_bottom"] else -1.0])
            cosine = float(axis @ expected / np.linalg.norm(axis))
            tooth["orientation_error_deg"] = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def subgroup_table(rows: list[dict[str, Any]], teeth: list[dict[str, Any]], low_contrast: float) -> list[dict[str, Any]]:
    lookup = {int(t["id"]): t for t in teeth}
    definitions: dict[str, Callable[[dict[str, Any]], bool]] = {
        "all": lambda t: True,
        "multi-rooted (≥2 apices)": lambda t: t["multirooted"],
        "tilted >15°": lambda t: t["tilted"],
        "low contrast (dev bottom quartile)": lambda t: t["rms_contrast"] <= low_contrast,
        "maxillary": lambda t: t["arch"] == "Upper",
        "mandibular": lambda t: t["arch"] == "Lower",
        "anterior site": lambda t: t["site"] == "Anterior",
        "orientation metadata wrong (>45°)": lambda t: t["orientation_error_deg"] > 45,
        "orientation metadata correct": lambda t: t["orientation_error_deg"] <= 45,
    }

    def mre(sample: list[dict[str, Any]]) -> float:
        return float(np.mean([np.mean(r["radial"]) for r in sample if "radial" in r]))

    def accuracy(sample: list[dict[str, Any]]) -> float:
        valid = [r for r in sample if r["valid"]]
        return float(np.mean([r["pred_stage"] == r["truth_stage"] for r in valid]))

    table = []
    for name, keep in definitions.items():
        members = [r for r in rows if keep(lookup[r["id"]])]
        if len(members) < 3:
            table.append({"subgroup": name, "n": len(members)})
            continue
        valid = [r for r in members if r["valid"]]
        table.append(
            {
                "subgroup": name,
                "n": len(members),
                "images": len({r["image"] for r in members}),
                "mre_px": mre(members),
                "mre_ci95": clustered_ci(members, mre),
                "along_mae_px": float(np.mean([np.mean(r["along"]) for r in members if "along" in r])),
                "pbl_mae_pp": float(np.mean([abs(r["pred_pbl"] - r["truth_pbl"]) for r in valid])),
                "stage_accuracy": accuracy(members),
                "stage_accuracy_ci95": clustered_ci(members, accuracy),
                "invalid_rate": 1 - len(valid) / len(members),
                "severe_undercall": sum(r["truth_stage"] == "III/IV" and r["pred_stage"] != "III/IV" for r in valid),
                "severe_n": sum(r["truth_stage"] == "III/IV" for r in valid),
            }
        )
    return table


# ------------------------------------------------------------------------ figures


def plot_bland_altman(panels: list[tuple[str, list[dict[str, Any]]]], human: dict[str, Any], path: Path) -> None:
    figure, axes = plt.subplots(1, len(panels), figsize=(6.2 * len(panels), 4.6), squeeze=False)
    for axis, (title, rows) in zip(axes[0], panels):
        valid = [r for r in rows if r["valid"]]
        truth = np.asarray([r["truth_pbl"] for r in valid])
        pred = np.asarray([r["pred_pbl"] for r in valid])
        diff, mean = pred - truth, (pred + truth) / 2
        bias, sd = diff.mean(), diff.std(ddof=1)
        axis.scatter(mean, diff, s=8, alpha=0.35, color="#2a6f97")
        axis.axhline(bias, color="#2a6f97", label=f"bias {bias:+.2f} pp")
        for v in (bias - 1.96 * sd, bias + 1.96 * sd):
            axis.axhline(v, color="#c0392b", linestyle="--")
        lo, hi = human["loa"]
        axis.axhspan(lo, hi, color="#7f8c8d", alpha=0.15, label=f"human R1–R2 LoA ({lo:.1f}, {hi:.1f})")
        axis.set(
            title=f"{title}: LoA {bias - 1.96 * sd:.1f} to {bias + 1.96 * sd:.1f} pp (n={len(valid)})",
            xlabel="Mean of manual and predicted PBLmax (%)",
            ylabel="Predicted − manual (pp)",
        )
        axis.legend(loc="lower left", fontsize=8)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_confusions(panels: list[tuple[str, dict[str, Any]]], path: Path) -> None:
    labels = ["I", "II", "III/IV"]
    figure, axes = plt.subplots(1, len(panels), figsize=(4.4 * len(panels), 4), squeeze=False)
    for axis, (title, result) in zip(axes[0], panels):
        matrix = np.asarray(result["confusion_rows_truth_cols_pred"])
        axis.imshow(matrix, cmap="Blues")
        for i in range(3):
            for j in range(3):
                axis.text(j, i, str(matrix[i, j]), ha="center", va="center",
                          color="white" if matrix[i, j] > matrix.max() / 2 else "black")
        axis.set_xticks(range(3), labels=labels)
        axis.set_yticks(range(3), labels=labels)
        axis.set(title=title, xlabel="Predicted stage", ylabel="Manual (DenPAR) stage")
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_risk_coverage(analysis: dict[str, Any], path: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    names = {"ci_width": "PBL 95% CI width", "max_landmark_sigma": "max landmark σ", "boundary_margin": "distance to stage boundary / CI half-width"}
    for axis, split in zip(axes, ("development", "external")):
        for key, label in names.items():
            c = analysis["curves"][split][key]
            axis.plot(c["coverage"], c["stage_accuracy"], label=label)
        axis.axhline(0.90, color="#7f8c8d", linestyle="--", linewidth=1)
        axis.set(title=f"{split.title()} (learned, Raw)", xlabel="Coverage (fraction of teeth accepted)",
                 ylabel="Stage accuracy of accepted teeth", ylim=(0.4, 1.01))
        axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_uncertainty_error(rows: list[dict[str, Any]], path: Path) -> None:
    valid = [r for r in rows if r["valid"] and r.get("ci")]
    width = np.asarray([r["ci"][1] - r["ci"][0] for r in valid])
    error = np.asarray([abs(r["pred_pbl"] - r["truth_pbl"]) for r in valid])
    sigma = np.asarray([s for r in rows if "sigma" in r for s in r["sigma"]])
    radial = np.asarray([e for r in rows if "sigma" in r for e in r["radial"]])
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    axes[0].scatter(sigma, radial, s=4, alpha=0.25)
    axes[0].set(xscale="log", yscale="log", xlabel="Predicted landmark σ (px)", ylabel="Radial error (px)",
                title="Landmark uncertainty vs error")
    edges = np.quantile(width, np.linspace(0, 1, 6))
    centres, medians = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (width >= lo) & (width <= hi)
        centres.append(np.median(width[mask]))
        medians.append(np.median(error[mask]))
    axes[1].scatter(width, error, s=6, alpha=0.25)
    axes[1].plot(centres, medians, "o-", color="#c0392b", label="quintile median")
    axes[1].set(xlabel="PBL 95% CI width (pp)", ylabel="|predicted − manual| PBLmax (pp)",
                title="Interval width vs PBL error")
    axes[1].legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_worst(rows: list[dict[str, Any]], teeth: list[dict[str, Any]], path: Path) -> list[dict[str, Any]]:
    lookup = {int(t["id"]): t for t in teeth}
    worst = sorted([r for r in rows if "radial" in r], key=lambda r: -float(np.mean(r["radial"])))[:5]
    figure, axes = plt.subplots(1, 5, figsize=(20, 7.5))
    summary = []
    colors = dict(zip(LANDMARK_NAMES, ["#2ecc71", "#1abc9c", "#f1c40f", "#e67e22", "#e74c3c"]))
    for axis, r in zip(axes, worst):
        tooth = lookup[r["id"]]
        image = Image.open(DENPAR / tooth["file_name"]).convert("L")
        axis.imshow(image, cmap="gray")
        truth, pred = tooth["truth"], r["points"]
        mid = np.mean([truth["mesial_cej"], truth["distal_cej"]], axis=0)
        axis.plot([mid[0], truth["apex"][0]], [mid[1], truth["apex"][1]], "--", color="#2ecc71", linewidth=1)
        for k, name in enumerate(LANDMARK_NAMES):
            t, p = np.asarray(truth[name]), np.asarray(pred[name])
            axis.scatter(*t, color=colors[name], s=40, marker="o", edgecolors="black", linewidths=0.5)
            axis.scatter(*p, color=colors[name], s=60, marker="x")
            axis.annotate("", xy=p, xytext=t, arrowprops={"arrowstyle": "->", "color": "#ff4d4d", "lw": 1})
        x0, y0, x1, y1 = tooth["bbox"]
        pad = 0.15 * max(x1 - x0, y1 - y0)
        axis.set_xlim(x0 - pad, x1 + pad)
        axis.set_ylim(y1 + pad, y0 - pad)
        along = ", ".join(f"{n.split('_')[0][0]}{n.split('_')[-1][0].upper()} {r['signed_along'][k]:+.0f}" for k, n in enumerate(LANDMARK_NAMES))
        pbl = f"PBL {r['truth_pbl']:.0f}→{r['pred_pbl']:.0f}%" if r["valid"] else f"invalid ({r['invalid_reason']})"
        axis.set_title(
            f"DenPAR {tooth['denpar_id']} tooth {tooth['tooth_id']} ({tooth['arch']}/{tooth['site']})\n"
            f"MRE {np.mean(r['radial']):.0f}px · {pbl}\nalong-axis px: {along}",
            fontsize=8,
        )
        axis.axis("off")
        summary.append({
            "denpar_id": tooth["denpar_id"], "tooth_id": tooth["tooth_id"], "arch": tooth["arch"], "site": tooth["site"],
            "mre_px": float(np.mean(r["radial"])), "signed_along_px": dict(zip(LANDMARK_NAMES, r["signed_along"])),
            "perpendicular_px": dict(zip(LANDMARK_NAMES, r["perpendicular"])),
            "truth_pbl": r["truth_pbl"], "pred_pbl": r.get("pred_pbl"), "valid": r["valid"],
            "multirooted": tooth["multirooted"], "tilted": tooth["tilted"],
            "rms_contrast": tooth["rms_contrast"], "max_sigma_px": max(r["sigma"]),
            "orientation_error_deg": tooth["orientation_error_deg"],
        })
    figure.text(0.5, 0.01, "o = DenPAR manual, x = learned prediction, red arrow = error vector, dashed = manual long axis. "
                "Along-axis: signed error along the manual axis (+ toward apex) for mC, dC, mB, dB, aA.", ha="center", fontsize=9)
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return summary


def plot_degradation(results: dict[str, dict[str, Any]], path: Path) -> None:
    labels = [name for name, _, _ in DEGRADATIONS]
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for detector, by_level in results.items():
        axes[0].plot(labels, [by_level[name]["mre_px"] for name in labels], "o-", label=detector)
        axes[1].plot(labels, [by_level[name]["icc_2_1"] for name in labels], "o-", label=detector)
    axes[0].set(ylabel="MRE (px, all landmarks)", title="External test: MRE vs degradation")
    axes[1].set(ylabel="ICC(2,1) PBLmax vs manual", title="External test: ICC vs degradation")
    for axis in axes:
        axis.tick_params(axis="x", rotation=35)
        axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


# ---------------------------------------------------------------------- tables


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, tuple) and len(value) == 2:
        return f"{value[0]:.{digits}f} ± {value[1]:.{digits}f}"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def landmark_markdown(summaries: dict[str, dict[str, Any]]) -> str:
    keys = ["mre_px", "sdr_2px", "sdr_5px", "sdr_10px", "along_mae_px", "perpendicular_mae_px", "mre_pct_root"]
    head = "| Detector | Landmark | MRE px | SDR@2 | SDR@5 | SDR@10 | Along-axis MAE px | Perpendicular MAE px | MRE % root |"
    lines = [head, "|" + " --- |" * 9]
    for detector, summary in summaries.items():
        for name in (*LANDMARK_NAMES, "all"):
            row = summary["landmarks"][name]
            lines.append(f"| {detector} | {name} | " + " | ".join(fmt(row[k], 3 if k.startswith("sdr") else 1) for k in keys) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-robustness", action="store_true")
    parser.add_argument("--skip-clahe", action="store_true", help="draft run before CLAHE folds exist")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    split, _, dev, ext = load()
    add_image_features(dev)
    add_image_features(ext)
    low_contrast = float(np.percentile([t["rms_contrast"] for t in dev], 25))
    print(f"development teeth {len(dev)}, external {len(ext)}", flush=True)

    rows: dict[str, list[dict[str, Any]]] = {}
    dev_shape = fit_baseline_shape(dev)
    rows["baseline_dev"] = score(dev, run_baseline_oof(dev), with_ci=True)
    rows["baseline_ext"] = score(ext, run_baseline(ext, dev_shape), with_ci=True)
    print("baseline scored", flush=True)
    conditions = ("raw",) if args.skip_clahe else ("raw", "clahe")
    for condition in conditions:
        rows[f"learned_{condition}_dev"] = score(dev, run_learned_oof(dev, condition), with_ci=condition == "raw")
        ensemble = learned([WEIGHTS / f"{condition}_fold_{f}.pt" for f in range(1, 6)])
        rows[f"learned_{condition}_ext"] = score(ext, run_learned(ensemble, ext), with_ci=condition == "raw")
        print(f"learned {condition} scored", flush=True)

    human = human_reference()
    detector_dev = {
        "Classical gradient baseline": per_fold(rows["baseline_dev"]),
        "Learned heatmap (Raw)": per_fold(rows["learned_raw_dev"]),
    }
    if not args.skip_clahe:
        detector_dev["Learned heatmap (CLAHE)"] = per_fold(rows["learned_clahe_dev"])
    pooled = {name: downstream(rows[name]) for name in rows}
    pooled_ci = {
        name: {
            "icc_2_1": clustered_ci(rows[name], lambda s: downstream(s)["icc_2_1"]),
            "loa_width_pp": clustered_ci(rows[name], lambda s: downstream(s)["loa_width_pp"]),
        }
        for name in ("learned_raw_dev", "learned_raw_ext", "baseline_dev", "baseline_ext")
    }
    landmark_external = {name: landmark_table(rows[name]) for name in rows if name.endswith("_ext")}
    uncertainty = uncertainty_analysis(rows["learned_raw_dev"], rows["learned_raw_ext"])
    subgroups = {
        "development_oof": subgroup_table(rows["learned_raw_dev"], dev, low_contrast),
        "external": subgroup_table(rows["learned_raw_ext"], ext, low_contrast),
        "baseline_external": subgroup_table(rows["baseline_ext"], ext, low_contrast),
    }
    worst = plot_worst(rows["learned_raw_dev"], dev, RESULTS / "worst_predictions.png")

    # Raw vs CLAHE: train x test input on the external set (fold-model ensembles).
    cross: dict[str, Any] = {}
    for train_condition in conditions:
        ensemble = learned([WEIGHTS / f"{train_condition}_fold_{f}.pt" for f in range(1, 6)])
        for test_condition in ("raw", "clahe"):
            r = score(ext, run_learned(ensemble, ext, input_condition=test_condition))
            table = landmark_table(r)
            agreement_result = downstream(r)
            cross[f"train {train_condition} / test {test_condition}"] = {
                "mre_px": table["all"]["mre_px"],
                "bc_along_mae_px": float(np.mean([table["mesial_bc"]["along_mae_px"], table["distal_bc"]["along_mae_px"]])),
                "bc_signed_along_mean_px": float(np.mean([r_["signed_along"][k] for r_ in r if "signed_along" in r_ for k in (2, 3)])),
                "icc_2_1": agreement_result["icc_2_1"],
                "bias_pp": agreement_result["bias_pp"],
                "loa_width_pp": agreement_result["loa_width_pp"],
            }

    robustness: dict[str, dict[str, Any]] = {}
    if not args.skip_robustness:
        raw_ensemble = learned([WEIGHTS / f"raw_fold_{f}.pt" for f in range(1, 6)])
        for detector_name in ("Learned heatmap (Raw)", "Classical gradient baseline"):
            robustness[detector_name] = {}
            for label, kind, level in DEGRADATIONS:
                def transform(image: Image.Image, file_name: str, kind: str = kind, level: float = level) -> Image.Image:
                    return degrade(image, kind, level, SEED + int(Path(file_name).stem))
                predictions = (
                    run_learned(raw_ensemble, ext, transform=transform)
                    if detector_name.startswith("Learned")
                    else run_baseline(ext, dev_shape, transform=transform)
                )
                r = score(ext, predictions)
                d = downstream(r)
                robustness[detector_name][label] = {
                    "mre_px": landmark_table(r)["all"]["mre_px"],
                    "icc_2_1": d["icc_2_1"],
                    "stage_accuracy": d["stage_accuracy"],
                    "invalid_rate": d["invalid_rate"],
                }
            print(f"robustness {detector_name} done", flush=True)
        plot_degradation(robustness, RESULTS / "degradation.png")

    plot_bland_altman(
        [("Learned, development OOF", rows["learned_raw_dev"]), ("Learned, external test", rows["learned_raw_ext"]),
         ("Baseline, external test", rows["baseline_ext"])],
        human["raw"],
        RESULTS / "bland_altman.png",
    )
    plot_confusions(
        [("Learned · dev OOF", pooled["learned_raw_dev"]), ("Learned · external", pooled["learned_raw_ext"]),
         ("Baseline · external", pooled["baseline_ext"])],
        RESULTS / "stage_confusion.png",
    )
    plot_risk_coverage(uncertainty, RESULTS / "risk_coverage.png")
    plot_uncertainty_error(rows["learned_raw_dev"], RESULTS / "uncertainty_vs_error.png")

    invalid = {
        name: dict(sorted({str(k): sum(1 for r in rs if r["invalid_reason"] == k) for k in {r["invalid_reason"] for r in rs if r["invalid_reason"]}}.items()))
        for name, rs in rows.items()
    }
    report = {
        "split": {"seed": split["seed"], "k": split["k"], "dataset_sha256": split["dataset_sha256"],
                  "fold_test_teeth": [f["test_teeth"] for f in split["folds"]]},
        "n": {"development_teeth": len(dev), "development_images": len({t["file_name"] for t in dev}),
              "external_teeth": len(ext), "external_images": len({t["file_name"] for t in ext})},
        "human_reference_week3": human,
        "detector_development_mean_sd_across_folds": detector_dev,
        "landmarks_external": landmark_external,
        "downstream_pooled": pooled,
        "downstream_pooled_clustered_ci95": pooled_ci,
        "invalid_predictions": invalid,
        "uncertainty": {k: v for k, v in uncertainty.items() if k != "curves"},
        "uncertainty_baseline": {
            k: v for k, v in uncertainty_analysis(rows["baseline_dev"], rows["baseline_ext"]).items() if k != "curves"
        },
        "subgroups": subgroups,
        "low_contrast_threshold_rms": low_contrast,
        "worst_five_development": worst,
        "raw_vs_clahe_external": cross,
        "robustness_external": robustness,
    }
    (RESULTS / "metrics.json").write_text(json.dumps(report, indent=2, allow_nan=False, default=float) + "\n")
    (RESULTS / "risk_coverage_curves.json").write_text(json.dumps(uncertainty["curves"]) + "\n")
    (RESULTS / "landmark_table_development.md").write_text(landmark_markdown(detector_dev) + "\n")
    # Per-tooth predictions for audit (no images; coordinates only).
    (RESULTS / "per_tooth_predictions.json").write_text(json.dumps(rows, default=float) + "\n")
    print(json.dumps({k: report[k] for k in ("n", "downstream_pooled")}, indent=1, default=float)[:4000])


if __name__ == "__main__":
    main()
