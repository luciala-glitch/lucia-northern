"""Demo cases from the saved Week 5 predictions on DenPAR test images.

Each case is one radiograph from week4/demo_denpar/external_test, with the Week 5
model's landmarks, uncertainty and stage probabilities.

The manual corrections here are SIMULATED, because I do not have clinician
corrections. For each tooth flagged by the Week 5 review rule, I move the two
landmarks with the largest AI uncertainty to the DenPAR reference points. This was
the best strategy in my Week 5 correction study. Every export labels these
corrections as simulated. Real corrections are entered in the App.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from week4.constants import LANDMARK_NAMES

REPO = Path(__file__).resolve().parents[1]
PREDICTIONS = REPO / "week5" / "reports" / "refined_predictions.json"
REFERENCE = REPO / "week4" / "data" / "denpar_landmarks.json"
DEMO_IMAGES = REPO / "week4" / "demo_denpar" / "external_test" / "images"
DETECTOR = "Week 5 refined Raw + CLAHE ensemble (strong_aug, TTA), saved predictions"
SIM_REVIEWER = "simulated-reviewer"
SIM_TIME = "2026-11-19T12:00:00+00:00"
SIM_METHOD = "SIMULATED: two most-uncertain landmarks moved to DenPAR reference annotation"
REVIEW_THRESHOLD = 0.94


def _load() -> tuple[dict[int, dict], dict[int, dict], dict[int, dict]]:
    preds = {r["id"]: r for r in json.loads(PREDICTIONS.read_text())["external"]}
    ref = json.loads(REFERENCE.read_text())
    images = {i["id"]: i for i in ref["images"]}
    anns = {a["id"]: a for a in ref["annotations"]}
    return preds, anns, images


def build_demo_cases(simulate_corrections: bool = True) -> list[dict[str, Any]]:
    """One case per demo radiograph with saved predictions (19 cases, 36 teeth)."""
    preds, anns, images = _load()
    available = {p.name for p in DEMO_IMAGES.glob("*.jpg")}
    by_image: dict[int, list[tuple[dict, dict]]] = {}
    for pid, pred in preds.items():
        ann = anns[pid]
        img = images[ann["image_id"]]
        if Path(img["file_name"]).name in available:
            by_image.setdefault(img["id"], []).append((ann, pred))

    cases = []
    for image_id, pairs in sorted(by_image.items(), key=lambda kv: int(Path(images[kv[0]]["file_name"]).stem)):
        img = images[image_id]
        name = Path(img["file_name"]).name
        teeth = []
        for ann, pred in sorted(pairs, key=lambda ap: ap[0]["tooth_id"]):
            sigma = dict(zip(LANDMARK_NAMES, pred["sigma"]))
            x0, y0, x1, y1 = ann["bbox"]  # corner coordinates, as drawn by the Week 4 App
            tooth: dict[str, Any] = {
                "tooth_id": ann["tooth_id"],
                "label": f"T{ann['tooth_id']}",
                "arch": img.get("arch"),
                "site": img.get("site"),
                "bbox": [x0, y0, x1, y1],
                "auto": {
                    "detector": DETECTOR,
                    "landmarks": {n: list(pred["points"][n]) for n in LANDMARK_NAMES},
                    "sigma_px": sigma,
                    "pbl_ci95": list(pred["ci_calibrated"]),
                    "stage_probabilities": pred["p_stage"],
                    "orientation_switched": bool(pred["orientation_switched"]),
                },
                "manual": None,
            }
            own = pred["p_stage"][pred["pred_stage"]]
            if simulate_corrections and (own < REVIEW_THRESHOLD or pred["orientation_switched"]):
                worst_two = sorted(LANDMARK_NAMES, key=lambda n: sigma[n], reverse=True)[:2]
                corrected = {n: list(pred["points"][n]) for n in LANDMARK_NAMES}
                for n in worst_two:
                    corrected[n] = list(ann["mean"][n])
                tooth["manual"] = {
                    "landmarks": corrected,
                    "reviewer_id": SIM_REVIEWER,
                    "saved_at_utc": SIM_TIME,
                    "method": SIM_METHOD,
                    "note": "moved: " + ", ".join(worst_two),
                }
            teeth.append(tooth)
        cases.append({
            "case_id": f"DENPAR-TEST-{Path(name).stem}",
            "image": {
                "path": str((DEMO_IMAGES / name).relative_to(REPO)).replace("\\", "/"),
                "width": img["width"],
                "height": img["height"],
            },
            "source": {
                "dataset": "DenPAR v3 official Testing partition (CC BY 4.0, doi:10.5281/zenodo.16645076)",
                "patient_identifier": "none published; case = one radiograph",
                "tooth_numbering": "DenPAR per-image tooth index (FDI number not available)",
                "predictions": "week5/reports/refined_predictions.json (external)",
                "manual_corrections": SIM_METHOD if simulate_corrections else "none",
            },
            "teeth": teeth,
        })
    return cases


def reference_values() -> dict[tuple[str, int], dict[str, Any]]:
    """DenPAR reference PBL and stage for each tooth. Only used to check the demo results."""
    preds, anns, images = _load()
    out = {}
    for pid, pred in preds.items():
        ann = anns[pid]
        img = images[ann["image_id"]]
        out[(f"DENPAR-TEST-{Path(img['file_name']).stem}", ann["tooth_id"])] = {
            "pbl_max_pct": pred["truth_pbl"], "stage": pred["truth_stage"],
            "landmarks": ann["mean"], "auto_pbl_saved": pred["pred_pbl"], "auto_stage_saved": pred["pred_stage"],
        }
    return out
