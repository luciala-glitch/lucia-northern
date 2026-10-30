from __future__ import annotations

import numpy as np
from PIL import Image
import pytest

from week4.robustness import degradation_grid, degrade


def test_degradations_preserve_coordinate_frame_and_are_deterministic():
    image = Image.fromarray(np.tile(np.arange(80, dtype=np.uint8)[:, None], (1, 60)))
    for kind, level in degradation_grid():
        output = degrade(image, kind, level)
        assert output.size == image.size
        assert output.mode == "L"
    assert np.array_equal(
        np.asarray(degrade(image, "noise", 10)),
        np.asarray(degrade(image, "noise", 10)),
    )


@pytest.mark.parametrize(
    ("kind", "level"),
    [("blur", 4), ("noise", 0), ("resolution", 0.25), ("unknown", 1)],
)
def test_invalid_degradation_levels(kind, level):
    with pytest.raises(ValueError):
        degrade(Image.new("L", (40, 40)), kind, level)
