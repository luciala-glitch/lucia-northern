"""Review-first Week 4 auto-detect → drag-correct → dual export workflow."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
import math
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import streamlit as st  # noqa: E402
from PIL import Image  # noqa: E402

from week3.canvas import landmark_canvas
from week3.image_processing import preprocess
from week4.constants import LANDMARK_NAMES, STAGE_BOUNDARIES
from week4.denpar import _mesial_on_right
from week4.predict import AutoPrediction, ClassicalLandmarkDetector, load_radiograph, predict_landmarks
from week4.training import canonical_crop
from week4.uncertainty import PBLInterval, to_tooth_landmarks
from week3.pbl_calculator import PBLValidationError, calculate_tooth_pbl

ROOT = Path(__file__).resolve().parent
DEMO_ROOT = ROOT / "demo_denpar"
CORRECTIONS = Path(
    os.environ.get("PBL_CORRECTIONS", ROOT / "data" / "corrections.json")
)
# Trainee practice never mixes with reviewer data: it lives in its own file.
PRACTICE = Path(os.environ.get("PBL_PRACTICE", ROOT / "data" / "practice.json"))
REFERENCE = ROOT / "data" / "denpar_landmarks.json"
WEIGHTS = Path(os.environ.get("PBL_WEIGHTS", ROOT / "weights"))
TRAINEE = "trainee"
QUALIFIED = "qualified"
# Choosing a tooth on the image: one click inside a DenPAR box, or two corners on an upload.
PICK_BOX = ("locator",)
PICK_BOX_LABELS = ("Click inside the tooth you want to measure",)
PICK_CORNERS = ("box.a", "box.b")
PICK_CORNER_LABELS = (
    "Click one corner around the tooth (e.g. above the crown)",
    "Click the opposite corner (beyond the root tip)",
)
MIN_BOX = (20, 30)
CANVAS_NAMES = ("mesial.cej", "mesial.bc", "distal.cej", "distal.bc", "apex")
LABELS = ("Mesial CEJ", "Mesial bone crest", "Distal CEJ", "Distal bone crest", "Apex")
TO_CANVAS = {
    "mesial_cej": "mesial.cej",
    "mesial_bc": "mesial.bc",
    "distal_cej": "distal.cej",
    "distal_bc": "distal.bc",
    "apex": "apex",
}
FROM_CANVAS = {value: key for key, value in TO_CANVAS.items()}
CHARACTERISTICS = DEMO_ROOT / "characteristics.json"
LEARNED = "Learned heatmap (5-fold ensemble)"
BASELINE = "Classical gradient baseline"


def _orientation_defaults(
    partition: str,
    image_name: str,
    boxes: list[list[float]] | None = None,
    tooth_index: int = 0,
    image_width: int | None = None,
) -> tuple[bool, bool, str]:
    """DenPAR arch/site -> (apex at bottom, mesial on image left, description)."""
    if not CHARACTERISTICS.is_file():
        return True, True, ""
    info = json.loads(CHARACTERISTICS.read_text()).get(f"{partition}/{image_name}")
    if info is None:
        return True, True, ""
    # Labial viewing convention: patient-right teeth have mesial on the image right.
    mesial_left = info["site"] != "Right"
    note = f"DenPAR sheet: {info['arch']} arch, {info['site']} site (teeth {info['fdi_visible']})."
    if info["site"] == "Anterior":
        if boxes and image_width:
            # Mesial faces the midline, so it flips across it. Same rule week4/denpar.py
            # uses to build the reference, applied to box centres (no labels needed).
            fdi = [tooth.strip() for tooth in info["fdi_visible"].split(",") if tooth.strip()]
            centres = [(box[0] + box[2]) / 2 for box in boxes]
            mesial_left = not _mesial_on_right("Anterior", fdi, tooth_index, centres, image_width)[0]
            note += " Anterior image: mesial side estimated from this tooth's side of the midline — check it."
        else:
            note += " Anterior image: mesial depends on which side of the midline this tooth is — check it."
    return info["arch"] == "Lower", mesial_left, note


@st.cache_data(show_spinner=False)
def _development_references() -> dict[str, dict[int, dict[str, Any]]]:
    """Development image -> box index -> complete five-point DenPAR reference.

    The Development demo images come from DenPAR Training only. External-test
    references are deliberately never loaded into the review app.
    """
    if not REFERENCE.is_file():
        return {}
    dataset = json.loads(REFERENCE.read_text())
    training = {
        image["id"]: f"{image['denpar_id']}.jpg"
        for image in dataset["images"]
        if image["partition"] == "Training"
    }
    references: dict[str, dict[int, dict[str, Any]]] = {}
    for annotation in dataset["annotations"]:
        name = training.get(annotation["image_id"])
        if name is None:
            continue
        references.setdefault(name, {})[annotation["tooth_id"] - 1] = {
            "landmarks": {key: tuple(annotation["mean"][key]) for key in LANDMARK_NAMES},
            "apex_at_bottom": annotation["apex_at_bottom"],
            "mesial_on_left": annotation["mesial_on_left"],
        }
    return references


def _pbl_summary(landmarks: dict[str, tuple[float, float]]) -> dict[str, Any]:
    result = calculate_tooth_pbl(to_tooth_landmarks(landmarks))
    return {
        "mesial_pbl_pct": result.mesial.pbl_pct,
        "distal_pbl_pct": result.distal.pbl_pct,
        "pbl_max_pct": result.pbl_max_pct,
        "stage": result.stage,
    }


def _practice_feedback(
    points: dict[str, tuple[int, int]], reference: dict[str, Any]
) -> dict[str, Any]:
    """Compare a trainee's blind read with the expert reference for one tooth."""
    mine = {FROM_CANVAS[name]: tuple(map(float, point)) for name, point in points.items()}
    expert = reference["landmarks"]
    error = {name: round(math.dist(mine[name], expert[name]), 1) for name in LANDMARK_NAMES}
    try:
        trainee_pbl: dict[str, Any] | None = _pbl_summary(mine)
        problem = None
    except PBLValidationError as exc:
        trainee_pbl, problem = None, str(exc)
    return {
        "trainee_read": {name: list(mine[name]) for name in LANDMARK_NAMES},
        "expert_reference": {name: list(expert[name]) for name in LANDMARK_NAMES},
        "error_px": error,
        "mean_error_px": round(sum(error.values()) / len(error), 1),
        "trainee_pbl": trainee_pbl,
        "trainee_pbl_problem": problem,
        "expert_pbl": _pbl_summary(expert),
    }


def _load_practice() -> list[dict[str, Any]]:
    return json.loads(PRACTICE.read_text()) if PRACTICE.is_file() else []


def _append_practice(record: dict[str, Any]) -> None:
    # Every attempt is kept: repeat attempts are the learning history.
    PRACTICE.parent.mkdir(parents=True, exist_ok=True)
    saved = _load_practice()
    saved.append(record)
    PRACTICE.write_text(json.dumps(saved, indent=2, allow_nan=False) + "\n")


def _next_practice(
    names: list[str],
    references: dict[str, dict[int, dict[str, Any]]],
    current: tuple[str, int],
) -> tuple[str, int] | None:
    """Next reference tooth after the current one, preferring teeth not yet practised."""
    order = [(name, index) for name in names for index in sorted(references.get(name, {}))]
    if not order:
        return None
    practised = {
        (record["image_id"], int(record["tooth_id"]))
        for record in _load_practice()
        if record["purpose"] == "practice"
    }
    start = order.index(current) + 1 if current in order else 0
    rotated = order[start:] + order[:start]
    for name, index in rotated:
        if (f"denpar_development_{name}", index + 1) not in practised:
            return name, index
    return rotated[0]


def _checkpoint_digest(paths: list[Path]) -> list[dict[str, str]]:
    return [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16]} for p in paths]


def _orientation_preview(image: Any, bbox: tuple[int, int, int, int], apex_at_bottom: bool, mesial_on_left: bool) -> Any:
    """What the detector will see: crown up, apex down, mesial left."""
    crop = canonical_crop(image, bbox, apex_at_bottom=apex_at_bottom, mesial_on_left=mesial_on_left)
    figure, axis = plt.subplots(figsize=(1.6, 3.0))
    axis.imshow(crop.image, cmap="gray")
    axis.text(4, 16, "M", color="#ffd166", fontsize=12, weight="bold")
    axis.text(crop.image.width - 16, 16, "D", color="#ffd166", fontsize=12, weight="bold")
    axis.text(crop.image.width / 2, crop.image.height - 6, "apex", color="#ffd166", ha="center", fontsize=9)
    axis.axis("off")
    figure.tight_layout(pad=0.1)
    return figure


def _stage_bar(value: float, interval: PBLInterval) -> Any:
    """Point estimate and 95% CI on the stage scale, with the 15%/33% boundaries."""
    figure, axis = plt.subplots(figsize=(4.2, 1.05))
    spans = ((0, STAGE_BOUNDARIES[0], "I"), (STAGE_BOUNDARIES[0], STAGE_BOUNDARIES[1], "II"), (STAGE_BOUNDARIES[1], 100, "III/IV"))
    for (low, high, label), shade in zip(spans, ("#e8f1f8", "#c9dcec", "#9dbfdc")):
        axis.axvspan(low, high, color=shade)
        axis.text((low + min(high, 60)) / 2, 0.82, label, ha="center", va="center", fontsize=8)
    for boundary in STAGE_BOUNDARIES:
        axis.axvline(boundary, color="#34495e", linewidth=1)
    axis.plot([interval.lower, interval.upper], [0.4, 0.4], color="#1b4f72", linewidth=5, solid_capstyle="butt")
    axis.plot([value], [0.4], marker="D", color="white", markeredgecolor="#1b4f72", markersize=7)
    axis.set(xlim=(0, max(60.0, interval.upper + 5)), ylim=(0, 1), yticks=[])
    axis.set_xlabel("PBL (%) — bar = 95% CI, diamond = estimate", fontsize=8)
    axis.tick_params(labelsize=7)
    figure.tight_layout(pad=0.2)
    return figure


def _sample_boxes(name: str, annotation_root: Path) -> list[list[float]]:
    path = annotation_root / f"{Path(name).stem}.json"
    return json.loads(path.read_text())["bboxes"] if path.is_file() else []


def _set_prediction(prediction: AutoPrediction, context: tuple[Any, ...]) -> None:
    st.session_state.prediction = prediction
    st.session_state.points = {
        canvas_name: tuple(
            round(v) for v in prediction.landmarks[FROM_CANVAS[canvas_name]]
        )
        for canvas_name in CANVAS_NAMES
    }
    st.session_state.review_context = context
    st.session_state.epoch = st.session_state.get("epoch", 0) + 1
    st.session_state.canvas_revision = 0
    _reset_history()


def _reset_history() -> None:
    st.session_state.point_history = []
    st.session_state.last_points = dict(st.session_state.points)


def _track_history() -> None:
    """Remember the previous landmark set whenever the canvas changed it."""
    current = dict(st.session_state.points)
    last = st.session_state.get("last_points")
    if last is not None and current != last:
        st.session_state.setdefault("point_history", []).append(last)
    st.session_state.last_points = current


def _replace_points(points: dict[str, tuple[int, int]], *, record: bool = True) -> None:
    """Set the landmarks from the server side and make the canvas redraw them."""
    if record:
        st.session_state.setdefault("point_history", []).append(dict(st.session_state.points))
    st.session_state.points = dict(points)
    st.session_state.last_points = dict(points)
    st.session_state.epoch += 1
    st.session_state.canvas_revision = 0


def _undo() -> None:
    history = st.session_state.get("point_history", [])
    if history:
        _replace_points(history.pop(), record=False)


def _reset_to_suggestion() -> None:
    prediction = st.session_state.get("prediction")
    if prediction is not None:
        _replace_points(
            {name: tuple(round(v) for v in prediction.landmarks[FROM_CANVAS[name]]) for name in CANVAS_NAMES}
        )


def _clear_points() -> None:
    _replace_points({})


def _clear_for_context(context: tuple[Any, ...]) -> None:
    if st.session_state.get("review_context") != context:
        st.session_state.points = {}
        st.session_state.pop("prediction", None)
        st.session_state.pop("practice_result", None)
        st.session_state.opened_at = datetime.now(timezone.utc).isoformat()
        st.session_state.review_context = context
        st.session_state.epoch = st.session_state.get("epoch", 0) + 1
        st.session_state.canvas_revision = 0
        _reset_history()


def _corrected_prediction(
    points: dict[str, tuple[int, int]], original: AutoPrediction | None = None
) -> AutoPrediction:
    landmarks = {FROM_CANVAS[name]: tuple(map(float, point)) for name, point in points.items()}
    if original is not None:
        # The canvas stores whole pixels; an untouched marker keeps its exact
        # predicted position so "Change" reads 0.0 unless the reader moved it.
        for name, point in original.landmarks.items():
            if tuple(round(v) for v in point) == tuple(round(v) for v in landmarks[name]):
                landmarks[name] = tuple(map(float, point))
    result = calculate_tooth_pbl(to_tooth_landmarks(landmarks))
    zero = {name: 0.0 for name in landmarks}
    interval = PBLInterval(result.pbl_max_pct, result.pbl_max_pct, 1000, 1000)
    return AutoPrediction(landmarks, zero, interval, False, ())


def _csv_bundle(records: list[dict[str, Any]]) -> str:
    output = StringIO()
    fields = [
        "source", "image_id", "tooth_id", "pbl_max_pct", "stage",
        "mesial_cej", "mesial_bc", "distal_cej", "distal_bc", "apex", "pbl_ci95",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for record in records:
        landmarks = record["landmarks"]
        writer.writerow(
            {
                "source": record["source"],
                "image_id": record["image_id"],
                "tooth_id": record["tooth_id"],
                "pbl_max_pct": record["metrics"]["pbl_max_pct"],
                "stage": record["metrics"]["stage"],
                "mesial_cej": json.dumps(landmarks["mesial"]["cej"]),
                "mesial_bc": json.dumps(landmarks["mesial"]["bc"]),
                "distal_cej": json.dumps(landmarks["distal"]["cej"]),
                "distal_bc": json.dumps(landmarks["distal"]["bc"]),
                "apex": json.dumps(landmarks["apex"]),
                "pbl_ci95": json.dumps(record["uncertainty"]["pbl_ci95"]),
            }
        )
    return output.getvalue()


def _save_bundle(bundle: dict[str, Any]) -> None:
    CORRECTIONS.parent.mkdir(parents=True, exist_ok=True)
    saved = json.loads(CORRECTIONS.read_text()) if CORRECTIONS.is_file() else []
    record = bundle["corrected_result"]
    key = (
        bundle.get("reviewer_id"),
        record["image_id"],
        int(record["tooth_id"]),
        record["condition"],
        int(record["round"]),
    )
    # One reviewer's review slot has one current result. Re-saving replaces an
    # interrupted attempt instead of inflating the raw audit file with duplicates.
    saved = [
        existing
        for existing in saved
        if (
            existing.get("reviewer_id"),
            existing["corrected_result"]["image_id"],
            int(existing["corrected_result"]["tooth_id"]),
            existing["corrected_result"]["condition"],
            int(existing["corrected_result"]["round"]),
        )
        != key
    ]
    saved.append(bundle)
    CORRECTIONS.write_text(json.dumps(saved, indent=2, allow_nan=False) + "\n")


def _latest_manual_records(
    reviewer_id: str | None = None,
) -> dict[tuple[str, int, str, int], dict[str, Any]]:
    if not CORRECTIONS.is_file():
        return {}
    latest: dict[tuple[str, int, str, int], dict[str, Any]] = {}
    for bundle in json.loads(CORRECTIONS.read_text()):
        if bundle.get("reviewer_id") != reviewer_id:
            continue
        record = bundle["corrected_result"]
        key = (
            record["image_id"],
            int(record["tooth_id"]),
            record["condition"],
            int(record["round"]),
        )
        latest[key] = record
    return latest


def _next_pending(
    partition: str,
    condition: str,
    round_number: int,
    latest: dict[tuple[str, int, str, int], dict[str, Any]],
) -> tuple[str, int] | None:
    sample_root = DEMO_ROOT / partition / "images"
    annotation_root = DEMO_ROOT / partition / "official_annotations" / "keypoints"
    names = sorted((p.name for p in sample_root.glob("*.jpg")), key=lambda value: int(Path(value).stem))
    for name in names:
        for tooth_index in range(len(_sample_boxes(name, annotation_root))):
            key = (
                f"denpar_{partition}_{name}",
                tooth_index + 1,
                condition,
                round_number,
            )
            if key not in latest:
                return name, tooth_index
    return None


def _box_at(point: tuple[int, int], boxes: list[list[float]]) -> int | None:
    """Smallest tooth box containing the clicked point, if any."""
    x, y = point
    inside = [
        index for index, (left, top, right, bottom) in enumerate(boxes)
        if left <= x <= right and top <= y <= bottom
    ]
    return min(
        inside, key=lambda i: (boxes[i][2] - boxes[i][0]) * (boxes[i][3] - boxes[i][1]), default=None
    )


def _start_picking() -> None:
    st.session_state.picking_tooth = True
    st.session_state.stashed_points = dict(st.session_state.points)
    _replace_points({}, record=False)
    st.session_state.point_history = []


def _stop_picking(restore: bool) -> None:
    st.session_state.picking_tooth = False
    stashed = st.session_state.pop("stashed_points", {})
    _replace_points(stashed if restore else {}, record=False)
    st.session_state.point_history = []
    st.session_state.last_points = dict(st.session_state.points)


def _cancel_picking() -> None:
    _stop_picking(restore=True)


def _tooth_picker(
    image: Any,
    digest: str,
    condition: str,
    image_name: str,
    boxes: list[list[float]] | None,
    current: int | None,
) -> None:
    """Choose the tooth by clicking the image instead of a dropdown or pixel numbers."""
    names, labels = (PICK_BOX, PICK_BOX_LABELS) if boxes is not None else (PICK_CORNERS, PICK_CORNER_LABELS)
    points = st.session_state.points
    if set(points) == set(names):
        if boxes is not None:
            index = _box_at(points["locator"], boxes)
            if index is None:
                st.warning("That spot is not inside any tooth box. Click inside the tooth itself.")
                _replace_points({}, record=False)
            else:
                _stop_picking(restore=index == current)
                st.session_state["_next_review_item"] = (image_name, index)
                st.rerun()
        else:
            (ax, ay), (bx, by) = points["box.a"], points["box.b"]
            box = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
            if box[2] - box[0] < MIN_BOX[0] or box[3] - box[1] < MIN_BOX[1]:
                st.warning("That box is too small. Click two opposite corners around the whole tooth, crown to root tip.")
                _replace_points({}, record=False)
            else:
                chosen = st.session_state.setdefault("upload_boxes", {}).setdefault(digest, [])
                chosen.append(box)
                st.session_state["_upload_tooth"] = len(chosen) - 1
                _stop_picking(restore=False)
                st.rerun()
    st.markdown("**Select a tooth** — " + (
        "click inside the tooth you want to measure. Numbers mark the available teeth."
        if boxes is not None
        else "click two opposite corners of a box around one whole tooth, crown to root tip."
    ))
    markers = [
        {"id": i + 1, "x": round((b[0] + b[2]) / 2), "y": round((b[1] + b[3]) / 2), "selected": False, "saved": False}
        for i, b in enumerate(boxes or [])
    ]
    landmark_canvas(image, (digest, condition), names, labels, 1100, markers=markers)
    if current is not None:
        st.button("Cancel — keep the current tooth", on_click=_cancel_picking)


def _submit_practice(record_context: dict[str, Any], reference: dict[str, Any]) -> None:
    feedback = _practice_feedback(st.session_state.points, reference)
    opened = st.session_state.get("opened_at")
    now = datetime.now(timezone.utc)
    record = {
        "purpose": "practice",
        "annotator_role": "trainee",
        "not_ground_truth": True,
        "saved_at_utc": now.isoformat(),
        "seconds_to_submit": (
            round((now - datetime.fromisoformat(opened)).total_seconds(), 1) if opened else None
        ),
        **record_context,
        **feedback,
    }
    _append_practice(record)
    st.session_state.practice_result = feedback


def _retry_practice() -> None:
    st.session_state.pop("practice_result", None)
    st.session_state.opened_at = datetime.now(timezone.utc).isoformat()
    _replace_points({}, record=False)
    st.session_state.point_history = []


def _practice_main(
    data: bytes,
    image_name: str,
    record_image_id: str,
    tooth_index: int,
    bbox: tuple[int, ...],
    condition: str,
    apex_at_bottom: bool,
    mesial_on_left: bool,
    names: list[str],
    references: dict[str, dict[int, dict[str, Any]]],
) -> None:
    """Blind read first, then the DenPAR expert reference as feedback. Never saved as a label."""
    try:
        image = preprocess(load_radiograph(data), condition)
    except Exception as exc:
        st.error(str(exc))
        return
    digest = hashlib.sha256(data).hexdigest()
    context = (digest, "practice", tooth_index, bbox, condition, apex_at_bottom, mesial_on_left)
    _clear_for_context(context)
    _track_history()
    reference = references[image_name][tooth_index]
    result = st.session_state.get("practice_result")
    ready = set(st.session_state.points) == set(CANVAS_NAMES)
    record_context = {
        "image_id": record_image_id,
        "tooth_id": tooth_index + 1,
        "condition": condition,
        "bbox": list(bbox),
        "apex_at_bottom": apex_at_bottom,
        "mesial_on_left": mesial_on_left,
    }
    left_column, summary = st.columns([3, 1])
    with left_column:
        markers = [
            {
                "id": tooth_index + 1,
                "x": round((bbox[0] + bbox[2]) / 2),
                "y": round((bbox[1] + bbox[3]) / 2),
                "selected": True,
                "saved": False,
            }
        ]
        landmark_canvas(
            image,
            (digest, condition),
            CANVAS_NAMES,
            LABELS,
            1100,
            markers=markers,
            locked=result is not None,
            focus=[markers[0]["x"], markers[0]["y"]],
            focus_box=list(bbox),
            reference=(
                {TO_CANVAS[name]: list(xy) for name, xy in result["expert_reference"].items()}
                if result else None
            ),
            locked_message="Practice submitted · white rings are the expert reference",
        )
        # Actions sit directly under the image so they are reachable without scrolling.
        if result is None:
            undo, clear, submit = st.columns([1, 1, 2])
            undo.button(
                "↶ Undo last change", on_click=_undo, width="stretch",
                disabled=not st.session_state.get("point_history"),
            )
            clear.button(
                "Clear my points", on_click=_clear_points, width="stretch",
                disabled=not st.session_state.points,
            )
            if submit.button(
                "Submit & show expert reference", type="primary", width="stretch", disabled=not ready
            ):
                _submit_practice(record_context, reference)
                st.rerun()
        else:
            next_column, retry = st.columns(2)
            if next_column.button("Next reference tooth →", type="primary", width="stretch"):
                next_item = _next_practice(names, references, (image_name, tooth_index))
                if next_item is not None:
                    st.session_state["_next_review_item"] = next_item
                    st.rerun()
            retry.button("↺ Try this tooth again", on_click=_retry_practice, width="stretch")
    with summary:
        if result is None:
            st.markdown("**Which side is M and which is D?**")
            st.caption(
                "**M = mesial**: the side of the tooth facing the middle of the front teeth "
                "(the gap between the two central incisors). **D = distal**: the side facing "
                "the back of the mouth. The small picture below shows this tooth with "
                "**M** and **D** marked."
            )
            st.caption(
                "Click order: M-CEJ → M-bone crest → D-CEJ → D-bone crest → apex. "
                "Submit to see the expert reference; your read then locks."
            )
            st.pyplot(
                _orientation_preview(image, bbox, apex_at_bottom, mesial_on_left),
                clear_figure=True, width="content",
            )
            st.caption("Same tooth turned crown-up, mesial (M) on the left.")
        else:
            st.success("Saved as practice (not a label). White rings = expert reference.")
            expert = result["expert_pbl"]
            mine = result["trainee_pbl"]
            st.metric("Expert PBL", f"{expert['pbl_max_pct']:.1f}% · {expert['stage']}")
            if mine is None:
                st.warning(f"Your points fail the geometric checks: {result['trainee_pbl_problem']}")
            else:
                st.metric(
                    "Your PBL",
                    f"{mine['pbl_max_pct']:.1f}% · {mine['stage']}",
                    f"{mine['pbl_max_pct'] - expert['pbl_max_pct']:+.1f} pp vs expert",
                    delta_color="off",
                )
            st.metric("Mean landmark distance", f"{result['mean_error_px']:.1f} px")
            st.dataframe(
                [
                    {"Landmark": label, "Distance (px)": result["error_px"][FROM_CANVAS[name]]}
                    for name, label in zip(CANVAS_NAMES, LABELS)
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Reference = the single official DenPAR annotation assigned to this tooth by "
                "week4/denpar.py (bone crest = most coronal point of the official crest line on "
                "each side). It is a teaching reference, not a second expert's opinion."
            )


def main() -> None:
    st.set_page_config(page_title="PBL Week 4 · Landmark review", layout="wide")
    # Keep the header short so the image and the buttons under it fit on one screen.
    st.markdown(
        "<style>.block-container,[data-testid='stMainBlockContainer']"
        "{padding-top:1.2rem;padding-bottom:1rem}"
        "[data-testid='stHeader']{background:transparent}</style>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "#### PBL Week 4 · Landmark review &nbsp;<small style='font-weight:400;opacity:.65;font-size:.8rem'>"
        "Research prototype only — not a diagnostic device. Every automatic result requires clinician review."
        "</small>",
        unsafe_allow_html=True,
    )
    st.session_state.setdefault("points", {})
    st.session_state.setdefault("epoch", 0)
    st.session_state.setdefault("canvas_revision", 0)
    # Widget-backed keys may only be changed before their widgets are created.
    # Saving queues the next tooth, then the following rerun applies it here.
    next_item = st.session_state.pop("_next_review_item", None)
    if next_item is not None:
        st.session_state["demo_image"], st.session_state["tooth_box"] = next_item
    next_upload = st.session_state.pop("_upload_tooth", None)
    if next_upload is not None:
        st.session_state["upload_tooth"] = next_upload
    saved_notice = st.session_state.pop("_review_saved_notice", None)
    if saved_notice:
        st.success(saved_notice)

    with st.sidebar:
        st.header("Reader")
        role = st.radio(
            "Who is reading?",
            [TRAINEE, QUALIFIED],
            format_func=lambda value: (
                "Practice / calibration (not ground truth)"
                if value == TRAINEE
                else "Qualified dental reviewer"
            ),
            key="reviewer_role",
        )
        trainee = role == TRAINEE
        reviewer_id = ""
        references: dict[str, dict[int, dict[str, Any]]] = {}
        if trainee:
            st.caption(
                "Practise on Development teeth that have a complete DenPAR expert reference. "
                "Practice reads are saved to a separate file and are never used as labels. "
                "External test and Blind R1/R2 are reserved for qualified reviewers."
            )
            source_kind = "DenPAR demo"
            references = _development_references()
            if not references:
                st.error(f"Expert reference file not found: {REFERENCE}. Run `make data` first.")
                return
        else:
            st.caption("Choose this only if you are a dentist or trained periodontal-radiograph reader.")
            reviewer_id = st.text_input(
                "Reviewer ID", key="reviewer_id", help="Initials or code, saved with every review."
            ).strip()
        st.header("Image and tooth")
        if not trainee:
            source_kind = st.radio("Source", ["DenPAR demo", "Upload"], horizontal=True)
        if source_kind == "DenPAR demo":
            if trainee:
                partition = "development"
                st.caption("Partition: Development (DenPAR Training images only)")
            else:
                partition = st.radio(
                    "DenPAR partition",
                    ["development", "external_test"],
                    format_func=lambda value: (
                        "Development (annotate/train)"
                        if value == "development"
                        else "External test (never train)"
                    ),
                )
            sample_root = DEMO_ROOT / partition / "images"
            annotation_root = (
                DEMO_ROOT / partition / "official_annotations" / "keypoints"
            )
            names = sorted((p.name for p in sample_root.glob("*.jpg")), key=lambda value: int(Path(value).stem))
            if trainee:
                names = [name for name in names if references.get(name)]
                references = {name: references[name] for name in names}
            if st.session_state.get("demo_image") not in names:
                st.session_state.demo_image = names[0]
            image_name = st.selectbox("Demo radiograph", names, key="demo_image")
            data = (sample_root / image_name).read_bytes()
            boxes = _sample_boxes(image_name, annotation_root)
            # Practice needs a complete five-point expert reference to give feedback.
            options = sorted(references[image_name]) if trainee else list(range(len(boxes)))
            if st.session_state.get("tooth_box") not in options:
                st.session_state.tooth_box = options[0]
            tooth_index = st.selectbox(
                "Tooth (only teeth with a complete expert answer)" if trainee else "Tooth",
                options,
                format_func=lambda index: f"Tooth {index + 1} of {len(boxes)} on this image",
                key="tooth_box",
            )
            if not trainee:
                st.button("👆 Select tooth on image", on_click=_start_picking, width="stretch")
            if trainee and len(options) < len(boxes):
                hidden = ", ".join(str(i + 1) for i in range(len(boxes)) if i not in options)
                st.caption(
                    f"{len(options)} of the {len(boxes)} teeth on this image can be practised. "
                    f"DenPAR did not mark all five points on tooth {hidden} (e.g. a CEJ hidden by a "
                    "crown, or a tooth cut off at the film edge), so there is no answer to compare with. "
                    "Qualified-reviewer mode can still run the AI on every tooth."
                )
            bbox = tuple(round(value) for value in boxes[tooth_index])
            record_image_id = f"denpar_{partition}_{image_name}"
            with Image.open(sample_root / image_name) as header:
                image_width = header.width
            default_apex, default_mesial, orientation_note = _orientation_defaults(
                partition, image_name, boxes, tooth_index, image_width
            )
            if trainee:
                reference = references[image_name][tooth_index]
                default_apex, default_mesial = reference["apex_at_bottom"], reference["mesial_on_left"]
        else:
            upload = st.file_uploader("JPG, PNG, or TIFF", type=["jpg", "jpeg", "png", "tif", "tiff"])
            if upload is None:
                st.info("Upload a radiograph to continue.")
                return
            image_name, data = upload.name, upload.getvalue()
            boxes = None
            chosen = st.session_state.get("upload_boxes", {}).get(hashlib.sha256(data).hexdigest(), [])
            if chosen:
                if st.session_state.get("upload_tooth") not in range(len(chosen)):
                    st.session_state.upload_tooth = len(chosen) - 1
                tooth_index = st.selectbox(
                    "Tooth", list(range(len(chosen))),
                    format_func=lambda index: f"Tooth {index + 1} / {len(chosen)}", key="upload_tooth",
                )
                bbox = tuple(chosen[tooth_index])
            else:
                # No tooth yet: the main area asks for one on the image.
                st.session_state.picking_tooth = True
                tooth_index, bbox = 0, (0, 0, 0, 0)
            partition = "upload"
            record_image_id = image_name
            default_apex, default_mesial, orientation_note = True, True, ""
            if chosen:
                st.button("👆 Add another tooth on image", on_click=_start_picking, width="stretch")
        condition = st.selectbox("Display condition", ["raw", "clahe", "he"], key="review_condition")
        round_number = 1 if trainee else st.selectbox("Independent review round", [1, 2], key="review_round")
        st.markdown("**Orientation** — the detector depends on it")
        if orientation_note:
            st.caption(orientation_note)
        apex_at_bottom = st.radio(
            "Root apex is toward", ["bottom", "top"], index=0 if default_apex else 1,
            horizontal=True, key=f"apex_{record_image_id}",
        ) == "bottom"
        mesial_on_left = st.radio(
            "Mesial side is image", ["left", "right"], index=0 if default_mesial else 1,
            horizontal=True, key=f"mesial_{record_image_id}_{tooth_index}",
        ) == "left"
    if trainee:
        with st.sidebar:
            practice = [r for r in _load_practice() if r["purpose"] == "practice"]
            attempted = {(r["image_id"], int(r["tooth_id"])) for r in practice}
            total = sum(len(teeth) for teeth in references.values())
            done = sum(
                (f"denpar_development_{name}", index + 1) in attempted
                for name, teeth in references.items()
                for index in teeth
            )
            st.progress(done / max(total, 1), text=f"Practice: {done}/{total} reference teeth tried")
            st.caption(f"{len(practice)} practice attempts saved to {PRACTICE.name}.")
        _practice_main(
            data, image_name, record_image_id, tooth_index, bbox, condition,
            apex_at_bottom, mesial_on_left, names, references,
        )
        return
    with st.sidebar:
        with st.expander("Failure-analysis tags"):
            obscured_cej = st.checkbox("Obscured CEJ (restoration/crown)")
            multirooted = st.checkbox("Multi-rooted molar")
            tilted = st.checkbox("Tilted >15° from vertical")
            low_contrast = st.checkbox("Low contrast")
        checkpoints = sorted(WEIGHTS.glob("raw_fold_*.pt"))
        detector_name = st.selectbox(
            "Automatic detector",
            ([LEARNED] if checkpoints else []) + [BASELINE],
            help="See week4/MODEL_CARD.md for measured accuracy and known failure modes.",
        )
        if not checkpoints:
            st.caption("No learned checkpoints in week4/weights — see the README to download them.")
        blind_first = st.toggle(
            "Blind first read",
            help="Place your own five landmarks before the AI suggestion is revealed. "
            "Both are saved, so automation bias can be measured.",
            key="blind_first",
        )
        latest = _latest_manual_records(reviewer_id or None)
        if source_kind == "DenPAR demo":
            prefix = f"denpar_{partition}_"
            completed = sum(
                image_id.startswith(prefix)
                and saved_condition == condition
                and saved_round == round_number
                for image_id, _, saved_condition, saved_round in latest
            )
            total = sum(
                len(_sample_boxes(name, annotation_root)) for name in names
            )
            paired = len(
                {
                    (image_id, tooth_id, saved_condition)
                    for image_id, tooth_id, saved_condition, saved_round in latest
                    if image_id.startswith(prefix)
                    and (image_id, tooth_id, saved_condition, 3 - saved_round) in latest
                }
            )
            st.progress(
                completed / max(total, 1),
                text=f"{partition} · {condition.upper()} R{round_number}: {completed}/{total}",
            )
            st.caption(f"Two-round tooth-condition pairs completed: {paired}")

    try:
        original = load_radiograph(data)
        image = preprocess(original, condition)
    except Exception as exc:
        st.error(str(exc))
        return
    digest = hashlib.sha256(data).hexdigest()
    if st.session_state.get("picking_tooth"):
        _tooth_picker(
            image, digest, condition, image_name,
            boxes if source_kind == "DenPAR demo" else None,
            tooth_index if source_kind == "DenPAR demo" or bbox != (0, 0, 0, 0) else None,
        )
        return
    context = (
        digest,
        partition,
        tooth_index,
        bbox,
        condition,
        round_number,
        apex_at_bottom,
        mesial_on_left,
    )
    _clear_for_context(context)
    _track_history()
    prediction = st.session_state.get("prediction")
    points_ready = set(st.session_state.points) == set(CANVAS_NAMES)

    left_column, summary = st.columns([3, 1])
    with summary:
        st.subheader("AI suggestion")
        st.pyplot(_orientation_preview(image, bbox, apex_at_bottom, mesial_on_left), clear_figure=True, width="content")
        st.caption("Detector view: crown up, mesial (M) left. If it looks wrong, fix the orientation first.")
        if partition == "development" and detector_name == LEARNED:
            st.caption(
                "Development images were used to train the learned models; judge real accuracy "
                "on External test or your own image."
            )

    with left_column:
        confidence = (
            {TO_CANVAS[name]: value for name, value in prediction.landmark_uncertainty_px.items()}
            if prediction else {}
        )
        markers = [
            {
                "id": tooth_index + 1,
                "x": round((bbox[0] + bbox[2]) / 2),
                "y": round((bbox[1] + bbox[3]) / 2),
                "selected": True,
                "saved": False,
            }
        ]
        landmark_canvas(
            image,
            (digest, condition),
            CANVAS_NAMES,
            LABELS,
            1100,
            markers=markers,
            focus=[markers[0]["x"], markers[0]["y"]],
            focus_box=list(bbox),
            confidence=confidence,
        )
        # Every action sits directly under the image, in workflow order.
        run, undo, reset, clear = st.columns([2, 1, 1, 1])
        waiting_for_blind = blind_first and prediction is None and not points_ready
        label = "Reveal AI suggestion" if blind_first else "Run AI suggestion"
        run_clicked = run.button(
            label, type="secondary" if prediction else "primary", width="stretch", disabled=waiting_for_blind,
            help="Blind first read: place all five landmarks yourself first." if waiting_for_blind else None,
        )
        undo.button(
            "↶ Undo", on_click=_undo, width="stretch",
            disabled=not st.session_state.get("point_history"),
        )
        reset.button(
            "Reset to AI", on_click=_reset_to_suggestion, width="stretch",
            disabled=prediction is None,
        )
        clear.button(
            "Clear points", on_click=_clear_points, width="stretch",
            disabled=prediction is not None or not st.session_state.points,
            help="Start the five clicks again. Available before the AI suggestion is shown.",
        )
        status = st.empty()
        if run_clicked:
            try:
                if detector_name == LEARNED:
                    from week4.learned import LearnedHeatmapDetector

                    detector: Any = LearnedHeatmapDetector(
                        checkpoints, apex_at_bottom=apex_at_bottom, mesial_on_left=mesial_on_left
                    )
                else:
                    detector = ClassicalLandmarkDetector(
                        apex_at_bottom=apex_at_bottom, mesial_on_left=mesial_on_left
                    )
                # The learned models apply their own training-time preprocessing.
                with st.spinner("Running AI suggestion…"):
                    prediction = predict_landmarks(
                        original if detector_name == LEARNED else image, bbox, detector=detector
                    )
                st.session_state.blind_read = (
                    dict(st.session_state.points) if blind_first and points_ready else None
                )
                st.session_state.detector_info = {
                    "name": detector_name,
                    "checkpoints": _checkpoint_digest(checkpoints) if detector_name == LEARNED else [],
                }
                st.session_state.started_at = datetime.now(timezone.utc).isoformat()
                _set_prediction(prediction, context)
                st.rerun()
            except Exception as exc:
                status.error(f"Prediction failed safely — measure this tooth manually. ({exc})")
        if prediction is None:
            status.info(
                "Blind first read: place all five landmarks yourself, then reveal the AI suggestion."
                if waiting_for_blind
                else "Step 1: run the AI suggestion. Step 2: drag any marker to correct it. Step 3: save."
            )
            return

    if not points_ready:
        return
    try:
        corrected = _corrected_prediction(st.session_state.points, prediction)
        corrected_result = corrected.result
    except Exception as exc:
        with left_column:
            st.error(f"Correction violates the Week 3 geometric guardrails: {exc}")
        return
    original_record = prediction.to_record(
        image_id=record_image_id,
        tooth_id=tooth_index + 1,
        condition=condition,
        round_number=round_number,
    )
    corrected_record = corrected.to_record(
        image_id=record_image_id,
        tooth_id=tooth_index + 1,
        condition=condition,
        source="manual",
        round_number=round_number,
    )
    original_points = {TO_CANVAS[k]: v for k, v in prediction.landmarks.items()}
    moved_px = {
        FROM_CANVAS[name]: round(
            ((st.session_state.points[name][0] - original_points[name][0]) ** 2
             + (st.session_state.points[name][1] - original_points[name][1]) ** 2) ** 0.5, 1
        )
        for name in CANVAS_NAMES
    }
    blind = st.session_state.get("blind_read")
    started = st.session_state.get("started_at")
    now = datetime.now(timezone.utc)
    bundle = {
        "saved_at_utc": now.isoformat(),
        "annotator_role": "qualified_reviewer",
        "reviewer_id": reviewer_id or None,
        "detector": st.session_state.get("detector_info"),
        "review_flagged": prediction.review_required,
        "review_reasons": list(prediction.review_reasons),
        "moved_px": moved_px,
        "seconds_since_suggestion": (
            round((now - datetime.fromisoformat(started)).total_seconds(), 1) if started else None
        ),
        "blind_first_read": (
            {FROM_CANVAS[name]: list(point) for name, point in blind.items()} if blind else None
        ),
        "review_context": {
            "partition": partition,
            "bbox": list(bbox),
            "apex_at_bottom": apex_at_bottom,
            "mesial_on_left": mesial_on_left,
            "subgroups": {
                "obscured_cej": obscured_cej,
                "multirooted_molar": multirooted,
                "tilted_over_15deg": tilted,
                "low_contrast": low_contrast,
            },
        },
        "original_prediction": original_record,
        "corrected_result": corrected_record,
    }
    with summary:
        confirmed = True
        if prediction.review_required:
            st.warning("Flagged for careful review: " + "; ".join(prediction.review_reasons))
            st.markdown("**Confirm every landmark before saving.**")
            ticks = [
                st.checkbox(
                    label,
                    value=moved_px[FROM_CANVAS[name]] > 2,
                    key=f"confirm_{name}_{st.session_state.epoch}",
                )
                for name, label in zip(CANVAS_NAMES, LABELS)
            ]
            confirmed = all(ticks)
        else:
            st.success("Not flagged by the rejection rule. Still check every landmark.")
        st.subheader("Reviewed result")
        st.metric("Corrected PBL", f"{corrected_result.pbl_max_pct:.1f}%")
        st.metric("Corrected stage", corrected_result.stage)
        st.metric(
            "Change",
            f"{corrected_result.pbl_max_pct - prediction.result.pbl_max_pct:+.1f} pp",
        )
        st.caption(
            f"AI suggestion: {prediction.result.pbl_max_pct:.1f}% · {prediction.result.stage}"
        )
        st.pyplot(
            _stage_bar(prediction.result.pbl_max_pct, prediction.interval),
            clear_figure=True,
            width="stretch",
        )

    with left_column:
        # Say exactly what is missing instead of silently disabling the buttons.
        missing = []
        if not confirmed:
            missing.append("tick all 5 landmarks (right panel)")
        if not reviewer_id:
            missing.append("enter Reviewer ID (sidebar)")
        save, export_json, export_csv = st.columns([2, 1, 1])
        save_clicked = save.button(
            ("Save review & next tooth" if partition != "upload" else "Save review")
            if not missing else "To save: " + " · ".join(missing),
            type="primary",
            width="stretch",
            disabled=bool(missing),
        )
        export_json.download_button(
            "Export JSON",
            json.dumps(bundle, indent=2) + "\n",
            f"{Path(image_name).stem}_tooth_{tooth_index + 1}_review.json",
            "application/json",
            width="stretch",
            disabled=not confirmed,
            help="Original prediction + your correction, Week 3 schema with source/uncertainty.",
        )
        export_csv.download_button(
            "Export CSV",
            _csv_bundle([original_record, corrected_record]),
            f"{Path(image_name).stem}_tooth_{tooth_index + 1}_review.csv",
            "text/csv",
            width="stretch",
            disabled=not confirmed,
        )
        if save_clicked:
            _save_bundle(bundle)
            if partition in {"development", "external_test"}:
                latest = _latest_manual_records(reviewer_id or None)
                next_item = _next_pending(
                    partition, condition, round_number, latest
                )
                if next_item is not None:
                    st.session_state["_next_review_item"] = next_item
                    st.session_state["_review_saved_notice"] = (
                        "Review saved locally. Ready for the next tooth."
                    )
                    st.session_state.pop("prediction", None)
                    st.rerun()
            st.success(f"Saved original and correction to {CORRECTIONS}")


if __name__ == "__main__":
    main()
