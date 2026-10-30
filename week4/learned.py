"""Checkpoint-backed learned heatmap inference with peak-dispersion uncertainty."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from week3.image_processing import preprocess
from week4.constants import LANDMARK_NAMES
from week4.errors import ModelNotReadyError
from week4.model import build_heatmap_model, decode_heatmaps, to_input_tensor
from week4.predict import BBox, Point
from week4.training import CanonicalCrop, canonical_crop


class LearnedHeatmapDetector:
    """Five-keypoint detector; uncertainty is the heatmap's spatial spread in pixels.

    Several fold checkpoints may be passed; their coordinates are averaged and
    the reported uncertainty combines the mean heatmap spread with the spread
    between checkpoints. Orientation inputs match the classical baseline and
    the App, because the canonical crop must know where the apex and mesial are.
    """

    def __init__(
        self,
        checkpoints: str | Path | Sequence[str | Path],
        *,
        apex_at_bottom: bool = True,
        mesial_on_left: bool = True,
        device: str | None = None,
    ) -> None:
        try:
            import torch
        except ImportError as exc:
            raise ModelNotReadyError(
                "Install week4/requirements-model.txt for learned inference"
            ) from exc
        paths = [Path(checkpoints)] if isinstance(checkpoints, (str, Path)) else [Path(p) for p in checkpoints]
        if not paths:
            raise ModelNotReadyError("At least one checkpoint is required")
        self.torch = torch
        if device is None:
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.device = torch.device(device)
        self.models = []
        conditions = set()
        for path in paths:
            if not path.is_file():
                raise ModelNotReadyError(f"Checkpoint does not exist: {path}")
            saved: dict[str, Any] = torch.load(path, map_location=self.device, weights_only=True)
            if tuple(saved.get("landmark_names", ())) != LANDMARK_NAMES:
                raise ModelNotReadyError("Checkpoint landmark order does not match this pipeline")
            model = build_heatmap_model(pretrained=False).to(self.device)
            model.load_state_dict(saved["state_dict"])
            model.eval()
            self.models.append(model)
            conditions.add(str(saved.get("condition", "raw")))
        if len(conditions) != 1:
            raise ModelNotReadyError("Checkpoints were trained on different input conditions")
        self.condition = conditions.pop()
        self.apex_at_bottom = apex_at_bottom
        self.mesial_on_left = mesial_on_left

    def crop(self, image: Image.Image, bbox: BBox, *, preprocessed: bool = False) -> CanonicalCrop:
        source = image if preprocessed else preprocess(image, self.condition)
        return canonical_crop(
            source, bbox, apex_at_bottom=self.apex_at_bottom, mesial_on_left=self.mesial_on_left
        )

    def predict_crops(self, crops: Sequence[CanonicalCrop]) -> list[tuple[dict[str, Point], dict[str, float]]]:
        """Batch inference on canonical crops (used by evaluation and the App)."""
        torch = self.torch
        pixels = np.stack([np.asarray(c.image, dtype=np.uint8) for c in crops])
        coords_all, spread_all = [], []
        with torch.no_grad():
            batch = to_input_tensor(torch.from_numpy(pixels).to(self.device), torch)
            for model in self.models:
                coords, spread = decode_heatmaps(model(batch), torch)
                coords_all.append(coords.cpu().numpy())
                spread_all.append(spread.cpu().numpy())
        coords = np.mean(coords_all, axis=0)
        within = np.mean(np.square(spread_all), axis=0)
        between = np.var(coords_all, axis=0) if len(coords_all) > 1 else 0.0
        sigma = np.sqrt(within + between)
        results = []
        for crop, xy, s in zip(crops, coords, sigma):
            sx, sy = crop.scale_px()
            points = {name: crop.to_original((float(xy[k, 0]), float(xy[k, 1]))) for k, name in enumerate(LANDMARK_NAMES)}
            # Isotropic 1-SD radius in original pixels, as the Monte Carlo CI expects.
            uncertainty = {
                name: float(np.sqrt(((s[k, 0] * sx) ** 2 + (s[k, 1] * sy) ** 2) / 2))
                for k, name in enumerate(LANDMARK_NAMES)
            }
            results.append((points, uncertainty))
        return results

    def predict(self, image: Image.Image, bbox: BBox) -> tuple[dict[str, Point], dict[str, float]]:
        return self.predict_crops([self.crop(image, bbox)])[0]
