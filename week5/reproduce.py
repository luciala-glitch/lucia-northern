"""One-command Week 5 reproduction with prerequisite and output checks.

    python -m week5.reproduce                # from the saved per-tooth predictions (~3 min)
    python -m week5.reproduce --from-weights # first re-run inference from the checkpoints

``--from-weights`` checks the checkpoints against ``week5/weights/MANIFEST.json``
and the split hash stored in every checkpoint, then regenerates the fold-1
screen and every per-tooth prediction file before evaluating.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "week5" / "reports"
RESULTS = REPORTS / "results"
WEIGHTS = ROOT / "week5" / "weights"
MANIFEST = WEIGHTS / "MANIFEST.json"
SPLIT = ROOT / "week4" / "data" / "denpar_split_5fold.json"
REQUIRED_INPUTS = (
    ROOT / "week4" / "reports" / "results" / "per_tooth_predictions.json",
    ROOT / "week4" / "reports" / "results" / "metrics.json",
    ROOT / "week4" / "data" / "denpar_landmarks.json",
    SPLIT,
    ROOT / "week4" / "data" / "denpar_full" / "Testing" / "Images",
    RESULTS / "screening.json",
)


def prediction_files() -> list[Path]:
    screening = json.loads((RESULTS / "screening.json").read_text())
    suffix = "_tta" if screening["tta_selected"] else ""
    names = {f"week4{suffix}", f"{screening['selected_config']}{suffix}"}
    return [RESULTS / f"per_tooth_predictions_{name}.json" for name in sorted(names)]


def _show(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def missing_inputs() -> list[str]:
    missing = [_show(p) for p in REQUIRED_INPUTS if not p.exists()]
    if not missing:
        missing += [_show(p) for p in prediction_files() if not p.is_file()]
    return missing


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_weights() -> None:
    """Every checkpoint the calibration names must match the manifest and the split."""
    calibration = json.loads((REPORTS / "calibration.json").read_text())
    expected = json.loads(MANIFEST.read_text())
    split_hash = json.loads(SPLIT.read_text())["dataset_sha256"]
    names = calibration["model"]["raw_checkpoints"] + calibration["model"]["clahe_checkpoints"]
    unlisted = [name for name in names if name not in expected]
    if unlisted:
        raise SystemExit(f"week5/weights/MANIFEST.json has no digest for {', '.join(unlisted)}")
    import torch

    for relative in names:
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"Missing checkpoint {relative}; see week5/README.md for the download")
        if expected[relative] != sha256(path):
            raise SystemExit(f"{relative} does not match week5/weights/MANIFEST.json")
        saved = torch.load(path, map_location="cpu", weights_only=True)
        if saved.get("split_sha256") != split_hash:
            raise SystemExit(f"{relative} was trained on a different split")
    print("All checkpoints match the manifest and the saved radiograph-level split.")


def write_manifest() -> None:
    """Record SHA-256 digests of every checkpoint the calibration names."""
    calibration = json.loads((REPORTS / "calibration.json").read_text())
    names = calibration["model"]["raw_checkpoints"] + calibration["model"]["clahe_checkpoints"]
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({name: sha256(ROOT / name) for name in names}, indent=2) + "\n")
    print(f"Wrote {len(names)} digests to {_show(MANIFEST)}")


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def verify_outputs() -> None:
    metrics = json.loads((REPORTS / "metrics.json").read_text())
    calibration = json.loads((REPORTS / "calibration.json").read_text())
    manifest = json.loads((REPORTS / "clinical_examples" / "manifest.json").read_text())
    checks = {
        "external labels never used for fitting": metrics["protocol"]["external_labels_used_for_fitting"] is False
        and calibration["external_labels_used"] is False,
        "external test has all 327 teeth": metrics["refined_external"]["downstream"]["n_total"] == 327,
        "development OOF has all 1,330 teeth": metrics["refined_development_oof"]["downstream"]["n_total"] == 1330,
        "at least 10 annotated examples": len(manifest) >= 10
        and all((REPORTS / "clinical_examples" / e["figure"]).is_file() for e in manifest),
        "successful, corrected and challenging examples": {e["kind"] for e in manifest} == {"successful", "corrected", "challenging"},
        "five cross-fitted fold parameter sets": len(calibration["fold_parameters"]) == 5,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit("Reproduction check failed: " + "; ".join(failed))
    for name in checks:
        print(f"  ✓ {name}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-weights", action="store_true", help="re-run inference from the checkpoints first")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--write-manifest", action="store_true", help="record checkpoint digests and exit")
    args = parser.parse_args(argv)
    if args.write_manifest:
        write_manifest()
        return
    if args.from_weights:
        check_weights()
        screening = json.loads((RESULTS / "screening.json").read_text())
        run("-m", "week5.experiments", "screen")
        tta = ["--tta"] if screening["tta_selected"] else []
        run("-m", "week5.experiments", "predict", "--config", "week4", *tta)
        if screening["selected_config"] != "week4":
            run("-m", "week5.experiments", "predict", "--config", screening["selected_config"], *tta)
    missing = missing_inputs()
    if missing:
        raise SystemExit("Missing Week 5 prerequisites: " + ", ".join(missing))
    run("-m", "week5.evaluate")
    if not args.skip_tests:
        run("-m", "pytest", "-q", "week5/tests")
    verify_outputs()
    print("Week 5 reproduction complete.")


if __name__ == "__main__":
    main()
