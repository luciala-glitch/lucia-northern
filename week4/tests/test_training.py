from __future__ import annotations

import random

import numpy as np
from PIL import Image
import pytest

from week4.constants import LANDMARK_NAMES
from week4.training import augment, canonical_crop, gaussian_heatmaps


def points():
    return {
        "mesial_cej": (30.0, 25.0),
        "distal_cej": (70.0, 25.0),
        "mesial_bc": (30.0, 40.0),
        "distal_bc": (70.0, 45.0),
        "apex": (50.0, 90.0),
    }


def test_crop_augment_and_heatmaps_are_label_aligned():
    image = Image.fromarray(np.tile(np.arange(120, dtype=np.uint8)[:, None], (1, 100)))
    crop = canonical_crop(image, (10, 10, 90, 110), apex_at_bottom=True, mesial_on_left=True, size=(64, 128))
    local = {name: crop.to_local(point) for name, point in points().items()}
    sample = augment(crop.image, local, random.Random(4))
    heatmaps = gaussian_heatmaps(sample.points, sample.image.size, sigma=2)
    assert sample.image.size == (64, 128)
    assert set(sample.points) == set(LANDMARK_NAMES)
    assert heatmaps.shape == (5, 128, 64)
    assert np.all(heatmaps.max(axis=(1, 2)) > 0.9)


def test_training_helpers_validate_inputs():
    with pytest.raises(ValueError, match="five"):
        augment(Image.new("L", (100, 100)), {"apex": (1, 1)}, random.Random(1))
    with pytest.raises(ValueError, match="sigma"):
        gaussian_heatmaps(points(), (100, 100), sigma=0)
    with pytest.raises(ValueError, match="dimensions"):
        gaussian_heatmaps(points(), (0, 100))
    incomplete = points()
    incomplete.pop("apex")
    with pytest.raises(ValueError, match="Missing"):
        gaussian_heatmaps(incomplete, (100, 100))


@pytest.mark.parametrize("apex_at_bottom", [True, False])
@pytest.mark.parametrize("mesial_on_left", [True, False])
def test_canonical_crop_round_trips_and_puts_mesial_left(apex_at_bottom, mesial_on_left):
    image = Image.new("L", (200, 300))
    crop = canonical_crop(
        image, (40, 50, 140, 250), apex_at_bottom=apex_at_bottom, mesial_on_left=mesial_on_left
    )
    apex = (90.0, 240.0 if apex_at_bottom else 60.0)
    mesial = (45.0 if mesial_on_left else 135.0, 100.0)
    assert crop.to_local(apex)[1] > crop.image.height * 0.8
    assert crop.to_local(mesial)[0] < crop.image.width * 0.2
    for point in (apex, mesial):
        assert np.allclose(crop.to_original(crop.to_local(point)), point)


def test_canonical_crop_rejects_empty_box():
    with pytest.raises(ValueError, match="positive"):
        canonical_crop(Image.new("L", (50, 50)), (10, 10, 10, 30), apex_at_bottom=True, mesial_on_left=True)
