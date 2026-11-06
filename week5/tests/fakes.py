"""Weight-free stand-ins shared by the Week 5 tests."""

from __future__ import annotations

from pathlib import Path

from week4.constants import LANDMARK_NAMES

# Canonical-crop (160x320, crown up, mesial left) positions of a Stage I tooth.
CANONICAL = {
    "mesial_cej": (40.0, 80.0),
    "distal_cej": (120.0, 80.0),
    "mesial_bc": (40.0, 104.0),
    "distal_bc": (120.0, 106.0),
    "apex": (80.0, 300.0),
}


class FakeHeatmapDetector:
    """Stands in for ``LearnedHeatmapDetector`` without PyTorch or weights.

    It is confident (small sigma) only when the crop is in the orientation the
    test declares correct, mimicking a real model shown an upside-down tooth.
    """

    correct_flip_y = False
    calls: list[str] = []

    def __init__(self, checkpoints, *, device=None, **_):
        paths = [Path(p) for p in checkpoints]
        for path in paths:
            if not path.is_file():
                from week4.errors import ModelNotReadyError

                raise ModelNotReadyError(f"Checkpoint does not exist: {path}")
        self.condition = "clahe" if "clahe" in paths[0].name else "raw"
        # CLAHE sits 2 px lower so the blend and disagreement terms are exercised.
        self.offset = 2.0 if self.condition == "clahe" else 0.0

    def predict_crops(self, crops):
        out = []
        for crop in crops:
            FakeHeatmapDetector.calls.append(f"{self.condition}:{crop.flip_y}")
            good = crop.flip_y == FakeHeatmapDetector.correct_flip_y
            points = {n: crop.to_original((x, y + self.offset)) for n, (x, y) in CANONICAL.items()}
            sigma = {n: (1.5 if good else 12.0) for n in LANDMARK_NAMES}
            out.append((points, sigma))
        return out
