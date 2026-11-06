"""Review-bundle validation and the automatic-versus-corrected comparison table."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import jsonschema

from week4.constants import LANDMARK_NAMES
from week4.predict import SCHEMA as MEASUREMENT_SCHEMA

BUNDLE_SCHEMA = json.loads(Path(__file__).with_name("review_bundle.schema.json").read_text())


def validate_bundle(bundle: Mapping[str, Any]) -> None:
    """Raise ``jsonschema.ValidationError`` unless the bundle and both records are valid.

    The two records must also refer to the same tooth, so a correction can
    only ever sit beside the automatic prediction it corrects.
    """
    jsonschema.validate(bundle, BUNDLE_SCHEMA)
    original, corrected = bundle["original_prediction"], bundle["corrected_result"]
    jsonschema.validate(original, MEASUREMENT_SCHEMA)
    jsonschema.validate(corrected, MEASUREMENT_SCHEMA)
    for key in ("image_id", "tooth_id", "condition", "round"):
        if original[key] != corrected[key]:
            raise jsonschema.ValidationError(f"original_prediction and corrected_result differ in {key}")


def _point(record: Mapping[str, Any], name: str) -> list[float]:
    landmarks = record["landmarks"]
    if name == "apex":
        return landmarks["apex"]
    side, kind = name.split("_")
    return landmarks[side][kind]


def comparison_rows(bundle: Mapping[str, Any]) -> list[dict[str, str]]:
    """Display rows: automatic point and its 95% radius, the correction and the move."""
    original, corrected = bundle["original_prediction"], bundle["corrected_result"]
    sigma = original["uncertainty"]["landmark_px"]
    rows = []
    for name in LANDMARK_NAMES:
        auto, manual = _point(original, name), _point(corrected, name)
        moved = float(bundle["moved_px"][name])
        radius = 2.4477 * float(sigma[name])
        rows.append({
            "Landmark": name,
            "AI (x, y)": f"{auto[0]:.0f}, {auto[1]:.0f}",
            "Corrected (x, y)": f"{manual[0]:.0f}, {manual[1]:.0f}",
            "AI 95% radius": f"{radius:.1f} px",
            "Moved": f"{moved:.1f} px",
            "Outside AI 95% radius": "yes" if moved > radius else "no",
        })
    om, cm = original["metrics"], corrected["metrics"]
    rows.append({
        "Landmark": "PBL / stage",
        "AI (x, y)": f"{om['pbl_max_pct']:.1f}% · {om['stage']}",
        "Corrected (x, y)": f"{cm['pbl_max_pct']:.1f}% · {cm['stage']}",
        "AI 95% radius": "CI {:.1f}–{:.1f}%".format(*original["uncertainty"]["pbl_ci95"]),
        "Moved": f"{cm['pbl_max_pct'] - om['pbl_max_pct']:+.1f} pp",
        "Outside AI 95% radius": "stage changed" if om["stage"] != cm["stage"] else "same stage",
    })
    return rows
