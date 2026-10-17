"""Tests for X-ray image conversion and enhancement."""

import numpy as np
from PIL import Image

from week2.image_processing import enhance_contrast, fit_for_display


def test_16_bit_xray_is_scaled_instead_of_clipped_to_white():
    pixels = np.linspace(0, 65535, 256, dtype=np.uint16).reshape(16, 16)
    image = Image.fromarray(pixels)

    displayed = np.asarray(fit_for_display(image))

    assert displayed.dtype == np.uint8
    assert displayed.min() == 0
    assert displayed.max() == 255
    assert np.unique(displayed).size > 200


def test_clahe_accepts_16_bit_xray():
    pixels = np.linspace(0, 65535, 1024, dtype=np.uint16).reshape(32, 32)
    enhanced = enhance_contrast(Image.fromarray(pixels))

    assert enhanced.mode == "L"
    assert np.asarray(enhanced).dtype == np.uint8
