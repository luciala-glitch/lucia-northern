"""Validated five-landmark inference with a classical baseline and strict output."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import math
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

import jsonschema
import numpy as np
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from week3.pbl_calculator import calculate_tooth_pbl
from week4.constants import LANDMARK_NAMES
from week4.errors import (
    CorruptedImageError,
    EmptyPredictionError,
    ImageValidationError,
    MissingImageError,
    UnsupportedImageError,
)
from week4.training import canonical_crop
from week4.uncertainty import (
    PBLInterval,
    needs_review_by_margin,
    pbl_confidence_interval,
    to_tooth_landmarks,
)

SCHEMA = json.loads(Path(__file__).with_name("measurement.schema.json").read_text())
Point = tuple[float, float]
BBox = tuple[int, int, int, int]


class Detector(Protocol):
    def predict(self, image: Image.Image, bbox: BBox) -> tuple[dict[str, Point], dict[str, float]]: ...


def load_radiograph(source: str | Path | bytes | bytearray | Image.Image) -> Image.Image:
    """Decode and normalize a radiograph while retaining 8/16-bit information."""
    try:
        if isinstance(source, Image.Image):
            image = source.copy()
        elif isinstance(source, (bytes, bytearray)):
            image = Image.open(BytesIO(bytes(source)))
        else:
            path = Path(source)
            if not path.is_file():
                raise MissingImageError(f"Image does not exist: {path}")
            image = Image.open(path)
        image.load()
        image = ImageOps.exif_transpose(image)
    except MissingImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise CorruptedImageError("Image is corrupted or cannot be decoded") from exc
    width, height = image.size
    if width < 32 or height < 32 or width > 16384 or height > 16384:
        raise UnsupportedImageError(
            f"Image dimensions {width}x{height} are outside [32, 16384] pixels"
        )
    if image.mode not in {"L", "I;16", "I;16L", "I;16B", "I", "F", "RGB", "RGBA"}:
        raise UnsupportedImageError(f"Unsupported image mode/bit depth: {image.mode}")
    return image


def _gray_u8(image: Image.Image) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim == 3:
        array = np.average(array[..., :3], axis=2, weights=(0.299, 0.587, 0.114))
    array = np.asarray(array, dtype=np.float32)
    if not np.isfinite(array).all():
        raise ImageValidationError("Image contains non-finite values")
    low, high = np.percentile(array, [0.5, 99.5])
    if high <= low:
        return np.zeros(array.shape, dtype=np.uint8)
    return np.clip((array - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)


def _validate_bbox(bbox: BBox, size: tuple[int, int]) -> BBox:
    if len(bbox) != 4 or any(type(v) is not int for v in bbox):
        raise ImageValidationError("bbox must contain four integer original-pixel coordinates")
    left, top, right, bottom = bbox
    width, height = size
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ImageValidationError(f"bbox {bbox} lies outside image size {size}")
    if right - left < 20 or bottom - top < 30:
        raise ImageValidationError("bbox is too small for five-landmark detection")
    return bbox


# Mean landmark position (and SD) in the canonical tooth-box crop, as fractions of
# crop width/height, from all DenPAR development teeth. Evaluation refits it on
# each fold's training radiographs; these defaults are only for the App.
DEFAULT_MEAN_SHAPE: tuple[tuple[float, float], ...] = (
    (0.185, 0.366), (0.789, 0.374), (0.181, 0.465), (0.776, 0.474), (0.542, 0.867)
)
DEFAULT_SHAPE_SD: tuple[tuple[float, float], ...] = (
    (0.073, 0.092), (0.070, 0.084), (0.097, 0.109), (0.101, 0.110), (0.230, 0.195)
)


class ClassicalLandmarkDetector:
    """Mean-shape initialization plus a gradient search for each bone crest.

    The tooth box is converted to the canonical crop (apex down, mesial left).
    CEJs and apex stay at the mean shape. Each crest is the strongest
    dark-to-bright transition, moving apically, in the interproximal column just
    outside the root, weighted by a Gaussian prior around the mean crest
    height. Search settings were chosen on DenPAR development data only.
    """

    OUTWARD_OFFSET = 0.10
    SMOOTHING_PX = 5.0
    PRIOR_SD = 0.10

    def __init__(
        self,
        *,
        apex_at_bottom: bool = True,
        mesial_on_left: bool = True,
        mean_shape: Sequence[tuple[float, float]] = DEFAULT_MEAN_SHAPE,
        shape_sd: Sequence[tuple[float, float]] = DEFAULT_SHAPE_SD,
    ) -> None:
        self.apex_at_bottom = apex_at_bottom
        self.mesial_on_left = mesial_on_left
        self.mean_shape = np.asarray(mean_shape, dtype=float)
        self.shape_sd = np.asarray(shape_sd, dtype=float)
        if self.mean_shape.shape != (5, 2) or self.shape_sd.shape != (5, 2):
            raise ValueError("mean_shape and shape_sd need one (x, y) pair per landmark")

    @staticmethod
    def fit_shape(local_points: Sequence[Mapping[str, Point]], size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        """Mean and SD of canonical-crop landmark fractions for a training set."""
        array = np.asarray([[p[name] for name in LANDMARK_NAMES] for p in local_points], dtype=float)
        array /= np.asarray(size, dtype=float)
        return array.mean(axis=0), array.std(axis=0)

    def predict(self, image: Image.Image, bbox: BBox) -> tuple[dict[str, Point], dict[str, float]]:
        bbox = _validate_bbox(bbox, image.size)
        crop = canonical_crop(
            Image.fromarray(_gray_u8(image)),
            bbox,
            apex_at_bottom=self.apex_at_bottom,
            mesial_on_left=self.mesial_on_left,
        )
        width, height = crop.image.size
        mean = self.mean_shape * (width, height)
        blurred = np.asarray(
            crop.image.filter(ImageFilter.GaussianBlur(radius=self.SMOOTHING_PX)), dtype=np.float32
        )
        apical_gradient = np.gradient(blurred, axis=0)
        local = {name: (float(mean[k, 0]), float(mean[k, 1])) for k, name in enumerate(LANDMARK_NAMES)}
        sx, sy = crop.scale_px()
        sigma = {
            name: float(np.hypot(self.shape_sd[k, 0] * width * sx, self.shape_sd[k, 1] * height * sy) / math.sqrt(2))
            for k, name in enumerate(LANDMARK_NAMES)
        }
        for cej_index, bc_index, outward in ((0, 2, -1), (1, 3, 1)):
            x = int(np.clip(round(mean[bc_index, 0] + outward * self.OUTWARD_OFFSET * width), 0, width - 1))
            # Start just apical to the CEJ so a crest can never project coronal to it.
            start = int(max(0, mean[cej_index, 1] + 0.02 * height))
            stop = int(min(height - 1, mean[bc_index, 1] + 0.3 * height))
            ys = np.arange(start, max(start + 1, stop))
            profile = np.maximum(apical_gradient[ys, max(0, x - 3) : x + 4].mean(axis=1), 0)
            if profile.size == 0 or not np.isfinite(profile).all():
                raise EmptyPredictionError("No valid intensity profile inside the tooth box")
            prior = np.exp(-0.5 * ((ys - mean[bc_index, 1]) / (self.PRIOR_SD * height)) ** 2)
            weighted = profile * prior
            name = LANDMARK_NAMES[bc_index]
            if weighted.max() <= 0:
                continue  # flat profile: keep the mean-shape crest and its prior SD
            y = float(ys[int(np.argmax(weighted))])
            local[name] = (float(mean[bc_index, 0]), y)
            spread = float(np.sqrt(np.average((ys - y) ** 2, weights=weighted)))
            sigma[name] = max(1.0, spread * sy)
        points = {name: crop.to_original(local[name]) for name in LANDMARK_NAMES}
        return points, sigma


@dataclass(frozen=True)
class AutoPrediction:
    landmarks: Mapping[str, Point]
    landmark_uncertainty_px: Mapping[str, float]
    interval: PBLInterval
    review_required: bool
    review_reasons: tuple[str, ...]

    @property
    def result(self):
        return calculate_tooth_pbl(to_tooth_landmarks(self.landmarks))

    def to_record(
        self,
        *,
        image_id: str,
        tooth_id: int,
        condition: Literal["raw", "clahe", "he"] = "raw",
        source: Literal["manual", "auto"] = "auto",
        round_number: int = 1,
    ) -> dict[str, Any]:
        result = self.result
        p = self.landmarks
        record: dict[str, Any] = {
            "image_id": image_id,
            "tooth_id": tooth_id,
            "condition": condition,
            "round": round_number,
            "long_axis_vector": list(result.long_axis_vector),
            "landmarks": {
                "mesial": {"cej": list(p["mesial_cej"]), "bc": list(p["mesial_bc"])},
                "distal": {"cej": list(p["distal_cej"]), "bc": list(p["distal_bc"])},
                "apex": list(p["apex"]),
            },
            "metrics": {
                "mesial_pbl_pct": result.mesial.pbl_pct,
                "distal_pbl_pct": result.distal.pbl_pct,
                "pbl_max_pct": result.pbl_max_pct,
                "stage": result.stage,
            },
            "source": source,
            "uncertainty": {
                "landmark_px": dict(self.landmark_uncertainty_px),
                "pbl_ci95": list(self.interval.pair),
            },
        }
        jsonschema.validate(record, SCHEMA)
        return record


def predict_landmarks(
    source: str | Path | bytes | bytearray | Image.Image,
    bbox: BBox,
    *,
    detector: Detector | None = None,
    draws: int = 1000,
) -> AutoPrediction:
    image = load_radiograph(source)
    predictor = detector or ClassicalLandmarkDetector()
    points, uncertainty = predictor.predict(image, _validate_bbox(bbox, image.size))
    if set(points) != set(LANDMARK_NAMES):
        raise EmptyPredictionError("Detector must return exactly the five required landmarks")
    if any(not all(math.isfinite(v) for v in xy) for xy in points.values()):
        raise EmptyPredictionError("Detector returned non-finite coordinates")
    for x, y in points.values():
        if not (0 <= x < image.width and 0 <= y < image.height):
            raise EmptyPredictionError("Detector returned a landmark outside the image")
    # The calculator is the single source of truth and enforces geometric bounds.
    pbl = calculate_tooth_pbl(to_tooth_landmarks(points)).pbl_max_pct
    interval = pbl_confidence_interval(points, uncertainty, draws=draws)
    # The prespecified rule (needs_manual_review) referred every tooth, since its
    # 5 px limit sits below the model's resolution; the validated margin rule is used.
    rejected, reasons = needs_review_by_margin(pbl, interval)
    return AutoPrediction(points, uncertainty, interval, rejected, reasons)
