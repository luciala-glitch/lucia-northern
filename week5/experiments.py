"""Week 5 model-refinement experiments on development data, then held-out inference.

``screen``  scores every fold-1 candidate (``week5/screen.sh``) on fold 1's
            held-out radiographs, plus test-time augmentation of the Week 4
            checkpoint. The external test is not touched.
``predict`` writes out-of-fold development and five-fold-ensemble external
            predictions for one 5-fold configuration, in the Week 4 row format.

Selection rule: the configuration with the lowest fold-1 held-out MRE is
retrained on all five folds, but only if it beats the saved Week 4 checkpoint by
more than the seed-noise floor, the MRE change from merely re-training the
Week 4 recipe with the same seed (GPU non-determinism), and never by less than
0.1 px. Otherwise the Week 4 configuration is kept (no change without evidence).
Test-time augmentation reuses the same weights, so it is judged by its paired
bootstrap interval instead.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


from week3.image_processing import preprocess
from week4.benchmark import DENPAR, by_image, downstream, landmark_table, load, score
from week4.constants import LANDMARK_NAMES
from week4.training import canonical_crop
from week5.refinement import combine_views
from week5.stats import paired_bootstrap
from week5.train import CONFIGS, ROOT, WEIGHTS

W4_WEIGHTS = ROOT / "week4" / "weights"
RESULTS = ROOT / "week5" / "reports" / "results"
TTA_MARGINS = (0.05, 0.08, 0.11)
SELECTION_TIE_PX = 0.1

Prediction = tuple[dict[str, tuple[float, float]], dict[str, float]]


def checkpoint(config: str, condition: str, fold: int) -> Path:
    if config == "week4":
        return W4_WEIGHTS / f"{condition}_fold_{fold}.pt"
    # Fold 1 of every configuration was trained once, during the screen.
    screened = WEIGHTS / "screen" / f"{config}_{condition}_fold_{fold}.pt"
    return screened if screened.is_file() else WEIGHTS / f"{config}_{condition}_fold_{fold}.pt"


def run(
    detector: Any,
    teeth: Sequence[dict[str, Any]],
    *,
    margins: Sequence[float] = (0.08,),
    flip_apex: bool = False,
) -> list[Prediction]:
    """Inference per radiograph; several box margins are averaged as test-time augmentation.

    Each margin is mapped back to original pixels before averaging, so no label
    geometry is involved. The spread between margins is added to the variance.
    ``flip_apex`` runs the opposite apex-direction hypothesis for the
    orientation self-check.
    """
    from PIL import Image

    out: dict[int, Prediction] = {}
    for file_name, group in by_image(teeth).items():
        source = preprocess(Image.open(DENPAR / file_name).convert("L"), detector.condition)
        per_margin = []
        for margin in margins:
            crops = [
                canonical_crop(
                    source,
                    tuple(int(v) for v in tooth["bbox"]),
                    apex_at_bottom=bool(tooth["apex_at_bottom"]) != flip_apex,
                    mesial_on_left=bool(tooth["mesial_on_left"]),
                    margin=margin,
                )
                for tooth in group
            ]
            per_margin.append(detector.predict_crops(crops))
        for index, tooth in enumerate(group):
            out[int(tooth["id"])] = combine_views([view[index] for view in per_margin])
    return [out[int(t["id"])] for t in teeth]


def detector(paths: Sequence[Path]) -> Any:
    from week4.learned import LearnedHeatmapDetector

    return LearnedHeatmapDetector(list(paths))


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    landmarks = landmark_table(rows)
    stats = downstream(rows)
    return {
        "mre_px": landmarks["all"]["mre_px"],
        "per_landmark_mre_px": {name: landmarks[name]["mre_px"] for name in LANDMARK_NAMES},
        "sdr_10px": landmarks["all"]["sdr_10px"],
        "along_mae_px": landmarks["all"]["along_mae_px"],
        "perpendicular_mae_px": landmarks["all"]["perpendicular_mae_px"],
        "icc_2_1": stats["icc_2_1"],
        "weighted_kappa": stats["weighted_kappa"],
        "stage_accuracy": stats["stage_accuracy"],
        "n_valid": stats["n_valid"],
        "n_total": stats["n_total"],
    }


def screen() -> dict[str, Any]:
    _, _, dev, _ = load()
    fold = [t for t in dev if t["fold"] == 1]
    candidates: dict[str, list[dict[str, Any]]] = {
        "week4 (saved Week 4 checkpoint)": score(fold, run(detector([checkpoint("week4", "raw", 1)]), fold)),
        "week4 + multi-margin TTA": score(
            fold, run(detector([checkpoint("week4", "raw", 1)]), fold, margins=TTA_MARGINS)
        ),
    }
    for name, config in CONFIGS.items():
        path = WEIGHTS / "screen" / f"{name}_raw_fold_1.pt"
        if path.is_file():
            label = "week4 (re-trained, seed noise)" if name == "week4" else name
            candidates[label] = score(fold, run(detector([path]), fold))
    baseline = candidates["week4 (saved Week 4 checkpoint)"]
    report = {
        "protocol": "trained on development fold-1 training radiographs; scored on fold-1 held-out radiographs only",
        "n_teeth": len(fold),
        "n_images": len({t["file_name"] for t in fold}),
        "configs": {name: {k: v for k, v in vars(c).items()} for name, c in CONFIGS.items()},
        "candidates": {
            name: {
                **summary(rows),
                "vs_week4_saved": paired_bootstrap(baseline, rows) if rows is not baseline else None,
            }
            for name, rows in candidates.items()
        },
    }
    trained = {
        name: value["mre_px"]
        for name, value in report["candidates"].items()
        if name not in {"week4 (saved Week 4 checkpoint)", "week4 + multi-margin TTA"}
    }
    reference = report["candidates"]["week4 (saved Week 4 checkpoint)"]["mre_px"]
    rerun = report["candidates"].get("week4 (re-trained, seed noise)")
    margin = max(SELECTION_TIE_PX, abs(rerun["mre_px"] - reference)) if rerun else SELECTION_TIE_PX
    contenders = {k: v for k, v in trained.items() if not k.startswith("week4")}
    best = min(contenders, key=contenders.get) if contenders else None
    report["seed_noise_floor_px"] = margin
    report["selected_config"] = best if best and contenders[best] < reference - margin else "week4"
    tta = report["candidates"]["week4 + multi-margin TTA"]["vs_week4_saved"]["mre_px"]
    report["tta_selected"] = tta["ci95"][1] < 0
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "screening.json").write_text(json.dumps(report, indent=2, default=float) + "\n")
    return report


def predict(config: str, *, tta: bool) -> dict[str, list[dict[str, Any]]]:
    _, _, dev, ext = load()
    margins = TTA_MARGINS if tta else (0.08,)
    out: dict[str, list[dict[str, Any]]] = {}
    for condition in ("raw", "clahe"):
        paths = [checkpoint(config, condition, fold) for fold in range(1, 6)]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            raise SystemExit("Missing checkpoints: " + ", ".join(missing))
        by_id: dict[int, Prediction] = {}
        for fold, path in enumerate(paths, 1):
            members = [t for t in dev if t["fold"] == fold]
            by_id.update({int(t["id"]): p for t, p in zip(members, run(detector([path]), members, margins=margins))})
        out[f"{condition}_dev"] = score(dev, [by_id[int(t["id"])] for t in dev])
        flipped: dict[int, Prediction] = {}
        for fold, path in enumerate(paths, 1):
            members = [t for t in dev if t["fold"] == fold]
            flipped.update({
                int(t["id"]): p
                for t, p in zip(members, run(detector([path]), members, margins=margins, flip_apex=True))
            })
        out[f"{condition}_dev_flipped"] = score(dev, [flipped[int(t["id"])] for t in dev])
        ensemble = detector(paths)
        out[f"{condition}_ext"] = score(ext, run(ensemble, ext, margins=margins))
        out[f"{condition}_ext_flipped"] = score(ext, run(ensemble, ext, margins=margins, flip_apex=True))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"per_tooth_predictions_{config}{'_tta' if tta else ''}.json").write_text(
        json.dumps(out, default=float) + "\n"
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("screen")
    p = sub.add_parser("predict")
    p.add_argument("--config", choices=sorted(CONFIGS), required=True)
    p.add_argument("--tta", action="store_true")
    args = parser.parse_args()
    if args.command == "screen":
        report = screen()
        print(json.dumps({k: {m: v[m] for m in ("mre_px", "stage_accuracy", "icc_2_1")} for k, v in report["candidates"].items()}, indent=2))
        print("selected:", report["selected_config"], "tta:", report["tta_selected"])
    else:
        predict(args.config, tta=args.tta)


if __name__ == "__main__":
    main()
