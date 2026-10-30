"""Build five-landmark tooth ground truth from the official DenPAR annotations.

DenPAR stores CEJ and apex points per radiograph and alveolar crest as
polylines. Each tooth also has its own segmentation mask (``maskN.png`` in the
same order as ``bboxes``), so points are assigned to the tooth whose mask they
lie on, not merely to an overlapping box. A tooth is kept only when it has two
CEJs, at least one apex, and a crest point touching each side of its mask.

Mesial direction comes from DenPAR's arch/site sheet: in the standard labial
view, patient-right teeth have mesial on the image right and patient-left teeth
on the image left. Anterior radiographs are split at the estimated midline.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

from week3.pbl_calculator import PBLValidationError, calculate_tooth_pbl
from week4.constants import LANDMARK_NAMES
from week4.uncertainty import to_tooth_landmarks

ROOT = Path(__file__).resolve().parents[1]
DENPAR = ROOT / "week4" / "data" / "denpar_full"
OUTPUT = ROOT / "week4" / "data" / "denpar_landmarks.json"
PARTITIONS = ("Training", "Validation", "Testing")
POINT_TOLERANCE_PX = 15.0
CREST_TOLERANCE_PX = 10.0
# Crests drawn up to this far coronal to the CEJ are treated as "no bone loss".
CLAMP_LIMIT_PX = 25.0


def _characteristics(path: Path) -> dict[int, tuple[str, str, list[str]]]:
    import openpyxl

    sheet = openpyxl.load_workbook(path, read_only=True).active
    rows: dict[int, tuple[str, str, list[str]]] = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        teeth = [t.strip() for t in str(row[3] or "").split(",") if t.strip()]
        rows[int(row[0])] = (str(row[1]), str(row[2]), teeth)
    return rows


def _dense(line: list[list[float]], step: float = 1.0) -> np.ndarray:
    points = np.asarray(line, dtype=float)
    if len(points) == 1:
        return points
    out = [points[0]]
    for a, b in zip(points[:-1], points[1:]):
        n = max(1, int(np.linalg.norm(b - a) / step))
        out.extend(a + (b - a) * t for t in np.linspace(0, 1, n + 1)[1:])
    return np.asarray(out)


def _owner(point: list[float], distances: list[np.ndarray]) -> int | None:
    height, width = distances[0].shape
    x = min(max(int(round(point[0])), 0), width - 1)
    y = min(max(int(round(point[1])), 0), height - 1)
    values = [d[y, x] for d in distances]
    index = int(np.argmin(values))
    return index if values[index] <= POINT_TOLERANCE_PX else None


def _mesial_on_right(
    site: str, fdi: list[str], box_index: int, centres: list[float], width: int
) -> tuple[bool, str]:
    if site == "Right":
        return True, "site_sheet"
    if site == "Left":
        return False, "site_sheet"
    patient_right = sum(t[:1] in {"1", "4"} for t in fdi)
    order = sorted(range(len(centres)), key=lambda i: centres[i])
    if fdi and len(fdi) == len(centres):
        return order.index(box_index) < patient_right, "anterior_fdi_order"
    return centres[box_index] < width / 2, "anterior_image_centre"


def _tooth(
    index: int,
    mask: np.ndarray,
    distance: np.ndarray,
    cejs: list[list[float]],
    apices: list[list[float]],
    crest: np.ndarray,
    mesial_right: bool,
) -> tuple[dict[str, Any] | None, str]:
    if len(cejs) < 2:
        return None, "fewer_than_two_cej"
    if not apices:
        return None, "no_apex"
    apex = np.mean(np.asarray(apices, dtype=float), axis=0)
    cej_array = np.asarray(cejs, dtype=float)
    provisional = apex - cej_array.mean(axis=0)
    provisional /= np.linalg.norm(provisional)
    across = np.asarray([-provisional[1], provisional[0]])
    lateral = (cej_array - apex) @ across
    left_cej, right_cej = cej_array[int(np.argmin(lateral))], cej_array[int(np.argmax(lateral))]
    if left_cej[0] > right_cej[0]:
        left_cej, right_cej = right_cej, left_cej
    mid = (left_cej + right_cej) / 2
    axis = apex - mid
    root = float(np.linalg.norm(axis))
    if root < 20:
        return None, "degenerate_axis"
    axis /= root
    across = np.asarray([-axis[1], axis[0]])
    if crest.size == 0:
        return None, "no_crest_line"
    height, width = mask.shape
    xi = np.clip(np.round(crest[:, 0]).astype(int), 0, width - 1)
    yi = np.clip(np.round(crest[:, 1]).astype(int), 0, height - 1)
    touching = crest[distance[yi, xi] <= CREST_TOLERANCE_PX]
    sides: dict[str, np.ndarray] = {}
    clamped = 0
    for label, cej in (("left", left_cej), ("right", right_cej)):
        sign = np.sign((cej - mid) @ across) or 1.0
        candidates = touching[((touching - mid) @ across) * sign > 0]
        if candidates.size == 0:
            return None, f"no_crest_on_{label}_side"
        axial = (candidates - cej) @ axis
        keep = (axial > -CLAMP_LIMIT_PX) & (axial < (apex - cej) @ axis)
        if not keep.any():
            return None, f"crest_outside_cej_apex_on_{label}_side"
        best = candidates[keep][int(np.argmin(axial[keep]))]
        depth = float((best - cej) @ axis)
        if depth < 0:
            best = best - depth * axis
            clamped += 1
        sides[label] = best
    mesial, distal = ("right", "left") if mesial_right else ("left", "right")
    points = {
        "mesial_cej": right_cej if mesial_right else left_cej,
        "distal_cej": left_cej if mesial_right else right_cej,
        "mesial_bc": sides[mesial],
        "distal_bc": sides[distal],
        "apex": apex,
    }
    named = {name: (float(points[name][0]), float(points[name][1])) for name in LANDMARK_NAMES}
    try:
        result = calculate_tooth_pbl(to_tooth_landmarks(named))
    except PBLValidationError as exc:
        return None, f"calculator_rejected:{type(exc).__name__}"
    tilt = math.degrees(math.acos(min(1.0, abs(float(axis[1])))))
    ys, xs = np.nonzero(mask)
    return {
        "tooth_id": index + 1,
        "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
        "mean": {name: list(named[name]) for name in LANDMARK_NAMES},
        "apex_count": len(apices),
        "tilt_deg": tilt,
        "bc_clamped_sides": clamped,
        "pbl_max_pct": result.pbl_max_pct,
        "stage": result.stage,
    }, "kept"


def build(root: Path = DENPAR) -> dict[str, Any]:
    sheet = _characteristics(root / "Characteristics of radiographs included.xlsx")
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for partition in PARTITIONS:
        folder = root / partition
        for keypoint_file in sorted(
            (folder / "Key Points Annotations").glob("*.json"), key=lambda p: int(p.stem)
        ):
            number = int(keypoint_file.stem)
            keypoints = json.loads(keypoint_file.read_text())
            bone = json.loads((folder / "Bone Level Annotations" / keypoint_file.name).read_text())
            arch, site, fdi = sheet[number]
            mask_dir = folder / "Masks (Tooth-wise)" / str(number)
            mask_files = [mask_dir / f"mask{i}.png" for i in range(1, len(keypoints["bboxes"]) + 1)]
            # One Training radiograph (803) lists a box whose mask was never released.
            reasons["missing_mask"] += sum(not f.is_file() for f in mask_files)
            masks = [
                np.asarray(Image.open(f).convert("L")) > 127 for f in mask_files if f.is_file()
            ]
            if not masks:
                continue
            distances = [ndimage.distance_transform_edt(~m) for m in masks]
            cej: dict[int, list[list[float]]] = {i: [] for i in range(len(masks))}
            apex: dict[int, list[list[float]]] = {i: [] for i in range(len(masks))}
            for target, source in ((cej, keypoints["CEJ_Points"]), (apex, keypoints["Apex_Points"])):
                for point in source:
                    owner = _owner(point, distances)
                    if owner is not None:
                        target[owner].append(point)
            lines = [line for line in bone.get("Bone_Lines", []) if line]
            crest = np.vstack([_dense(line) for line in lines]) if lines else np.zeros((0, 2))
            image_id = len(images) + 1
            height, width = masks[0].shape
            images.append(
                {
                    "id": image_id,
                    "file_name": f"{partition}/Images/{number}.jpg",
                    "partition": partition,
                    "denpar_id": number,
                    "group_id": f"denpar_{number}",
                    "condition": "raw",
                    "arch": arch,
                    "site": site,
                    "width": width,
                    "height": height,
                }
            )
            centres = [float(np.nonzero(m)[1].mean()) for m in masks]
            for index, (mask, distance) in enumerate(zip(masks, distances)):
                mesial_right, method = _mesial_on_right(site, fdi, index, centres, width)
                tooth, reason = _tooth(
                    index, mask, distance, cej[index], apex[index], crest, mesial_right
                )
                reasons[reason] += 1
                if tooth is None:
                    continue
                flat = [c for name in LANDMARK_NAMES for c in tooth["mean"][name]]
                annotations.append(
                    {
                        "id": len(annotations) + 1,
                        "image_id": image_id,
                        "category_id": 1,
                        "num_keypoints": 5,
                        "keypoints": flat,
                        "keypoint_names": list(LANDMARK_NAMES),
                        "apex_at_bottom": arch == "Lower",
                        "mesial_on_left": not mesial_right,
                        "mesial_assignment": method,
                        "multirooted": tooth["apex_count"] >= 2,
                        "tilted": tooth["tilt_deg"] > 15.0,
                        **tooth,
                    }
                )
    kept = reasons.pop("kept", 0)
    return {
        "info": {
            "description": "DenPAR v3 official annotations associated to five landmarks per tooth",
            "source_doi": "10.5281/zenodo.16645076",
            "license": "CC BY 4.0",
            "ground_truth": "single official DenPAR annotation; no repeat reading exists",
            "group": "radiograph (DenPAR publishes no patient identifiers)",
            "tooth_masks": sum(reasons.values()) + kept,
            "teeth_kept": kept,
            "excluded_by_reason": dict(sorted(reasons.items())),
        },
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": "tooth", "keypoints": list(LANDMARK_NAMES)}],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DENPAR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    dataset = build(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=1, allow_nan=False) + "\n")
    print(json.dumps(dataset["info"], indent=2))


if __name__ == "__main__":
    main()
