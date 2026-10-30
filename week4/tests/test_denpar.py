from __future__ import annotations

import json

import numpy as np
import openpyxl
from PIL import Image

from week4.denpar import _mesial_on_right, build


def write_case(root, partition, number, boxes, cej, apex, bone, site="Right", arch="Lower"):
    folder = root / partition
    for sub in ("Key Points Annotations", "Bone Level Annotations", "Images"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    (folder / "Key Points Annotations" / f"{number}.json").write_text(
        json.dumps({"bboxes": boxes, "CEJ_Points": cej, "Apex_Points": apex})
    )
    (folder / "Bone Level Annotations" / f"{number}.json").write_text(json.dumps({"Bone_Lines": bone}))
    masks = folder / "Masks (Tooth-wise)" / str(number)
    masks.mkdir(parents=True, exist_ok=True)
    for index, (x0, y0, x1, y1) in enumerate(boxes, start=1):
        array = np.zeros((300, 200), dtype=np.uint8)
        array[int(y0):int(y1), int(x0):int(x1)] = 255
        Image.fromarray(array).save(masks / f"mask{index}.png")


def sheet(root, rows):
    book = openpyxl.Workbook()
    page = book.active
    page.append(["id", "Arch", "Site", "FDI"])
    for row in rows:
        page.append(row)
    book.save(root / "Characteristics of radiographs included.xlsx")


def test_build_associates_points_by_mask_and_records_exclusions(tmp_path):
    tooth = [60, 40, 140, 280]
    write_case(
        tmp_path, "Training", 1, [tooth, [150, 40, 199, 280]],
        cej=[[60, 100], [140, 100]], apex=[[100, 280]],
        bone=[[[55, 160], [61, 150]], [[139, 130], [146, 140]]],
    )
    # Second partition: a tooth with one CEJ only, and an upper-arch tooth with no crest.
    write_case(
        tmp_path, "Testing", 2, [tooth, [150, 40, 199, 280]],
        cej=[[60, 200], [140, 200], [150, 100]], apex=[[100, 40]], bone=[], site="Left", arch="Upper",
    )
    (tmp_path / "Validation" / "Key Points Annotations").mkdir(parents=True)
    sheet(tmp_path, [[1, "Lower", "Right", "44,45"], [2, "Upper", "Left", "24,25"]])
    dataset = build(tmp_path)
    assert dataset["info"]["teeth_kept"] == 1
    reasons = dataset["info"]["excluded_by_reason"]
    assert reasons["fewer_than_two_cej"] == 2 and reasons["no_crest_line"] == 1
    (kept,) = dataset["annotations"]
    assert kept["apex_at_bottom"] is True and kept["mesial_on_left"] is False
    # Right-site tooth: mesial is the image-right CEJ, and its crest touches that side.
    assert kept["mean"]["mesial_cej"] == [140.0, 100.0]
    assert kept["mean"]["mesial_bc"][0] > 135 and kept["mean"]["distal_bc"][0] < 65
    assert kept["stage"] in {"I", "II", "III/IV"} and not kept["multirooted"]


def test_crest_coronal_to_cej_is_clamped_to_zero_bone_loss(tmp_path):
    write_case(
        tmp_path, "Training", 3, [[60, 40, 140, 280]],
        cej=[[60, 100], [140, 100]], apex=[[100, 280], [110, 279]],
        bone=[[[58, 90], [61, 92]], [[139, 92], [142, 90]]],
    )
    sheet(tmp_path, [[3, "Lower", "Left", "34"]])
    (kept,) = build(tmp_path)["annotations"]
    assert kept["bc_clamped_sides"] == 2 and abs(kept["pbl_max_pct"]) < 1e-9
    assert kept["multirooted"] and kept["mesial_on_left"] is True


def test_anterior_mesial_side_uses_fdi_order_then_image_centre():
    assert _mesial_on_right("Anterior", ["12", "11", "21"], 0, [10.0, 50.0, 90.0], 100) == (True, "anterior_fdi_order")
    assert _mesial_on_right("Anterior", ["12", "11", "21"], 2, [10.0, 50.0, 90.0], 100) == (False, "anterior_fdi_order")
    assert _mesial_on_right("Anterior", [], 0, [80.0], 100) == (False, "anterior_image_centre")
