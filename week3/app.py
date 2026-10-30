"""A recoverable study workflow: locate once, measure independently, record once."""

from __future__ import annotations
from dataclasses import replace
from io import BytesIO
import hashlib
import json
from pathlib import Path
import warnings
import sqlite3
from PIL import Image, ImageOps, UnidentifiedImageError
import streamlit as st
import jsonschema
from week3.canvas import landmark_canvas
from week3.exports import make_record, json_export, csv_export
from week3.image_processing import preprocess
from week3.study import StudyStore, reading_order
from week3.orientation import (
    estimate_midline,
    is_panoramic,
    mesial_side,
    swapped_surfaces,
)
from datetime import datetime, timezone
from week3.pbl_calculator import (
    ToothLandmarks,
    SideLandmarks,
    calculate_tooth_pbl,
    AnatomicalPlausibilityWarning,
    DegenerateGeometryError,
    PBLValidationError,
)

POINTS = ("mesial.cej", "mesial.bc", "distal.cej", "distal.bc", "apex")
LABELS = (
    "Mesial CEJ",
    "Mesial bone crest",
    "Distal CEJ",
    "Distal bone crest",
    "Shared anatomical apex",
)
SAMPLES = Path(__file__).resolve().parents[1] / "week2" / "sample_xrays"


def clear_points():
    st.session_state.points = {}
    st.session_state.epoch = st.session_state.get("epoch", 0) + 1
    st.session_state.canvas_revision = 0


def undo_point():
    if st.session_state.points:
        st.session_state.points.popitem()
        st.session_state.epoch += 1
        st.session_state.canvas_revision = 0


def select_tooth(tid):
    st.session_state.selected_tooth = tid


def reopen_reading(store, sid, tid, condition, rnd, reason_key):
    try:
        store.reopen(sid, tid, condition, rnd, st.session_state.get(reason_key))
        # Reload as an empty, unlocked reading: old points are not prefilled.
        st.session_state.pop("context", None)
        st.session_state.pop(reason_key, None)
        st.session_state.pop("save_error", None)
    except ValueError as exc:
        st.session_state.save_error = str(exc)


def save_measurement(store, sid, record):
    try:
        store.save(sid, record)
        st.session_state.pop("save_error", None)
    except ValueError as exc:
        st.session_state.save_error = str(exc)


@st.cache_data(show_spinner=False, max_entries=8)
def load_images(data: bytes, condition: str):
    original = ImageOps.exif_transpose(Image.open(BytesIO(data)))
    return original, preprocess(original, condition), hashlib.sha256(data).hexdigest()


@st.cache_data(show_spinner=False, max_entries=16)
def suggest_midline(digest: str, _image: Image.Image):
    return estimate_midline(_image)


def side_labels(side):
    """Landmark prompts that say which image side is mesial for this tooth."""
    if side is None:
        return LABELS
    toward = "image right →" if side == "right" else "← image left"
    away = "← image left" if side == "right" else "image right →"
    return (
        f"Mesial CEJ — side facing the midline ({toward})",
        f"Mesial bone crest ({toward})",
        f"Distal CEJ — side away from the midline ({away})",
        f"Distal bone crest ({away})",
        LABELS[4],
    )


def elapsed_text(created):
    seconds = (
        datetime.now(timezone.utc)
        - datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    ).total_seconds()
    if seconds < 3600:
        return f"{max(0, round(seconds / 60))} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


def change_context(context, points=None):
    if st.session_state.get("context") != context:
        clear_points()
        st.session_state.pop("save_error", None)
        st.session_state.points = {k: tuple(v) for k, v in (points or {}).items()}
        st.session_state.context = context


def restart_dialog(store, sid):
    st.warning("Start over safely")
    st.write(
        "Your current records, tooth locations and drafts will be archived. A new study starts with an empty tooth list. Nothing is deleted."
    )
    st.caption("You can return to the old study using Resume archived study.")
    if st.button("Archive current study and start new", type="primary"):
        store.restart(sid)
        st.session_state.show_restart = False
        st.session_state.pop("context", None)
        st.session_state.pop("selected_tooth", None)
        st.session_state.next_workflow = "Register teeth"
        st.session_state.records = []
        st.rerun()
    if st.button("Keep current study"):
        st.session_state.show_restart = False
        st.rerun()


def study_tools(store, sid, records):
    with st.sidebar:
        st.divider()
        st.subheader("Study tools")
        st.caption(f"Study {sid[:8]} · saved locally on this computer")
        if st.button("Start over…", width="stretch"):
            st.session_state.show_restart = True
        if st.session_state.get("show_restart"):
            restart_dialog(store, sid)
        archives = store.archives()
        if archives:
            with st.expander("Resume archived study"):
                chosen = st.selectbox(
                    "Archived study",
                    [r["id"] for r in archives],
                    format_func=lambda x: next(
                        f"{r['created']} · {r['count']} records · {x[:8]}"
                        for r in archives
                        if r["id"] == x
                    ),
                )
                st.caption(
                    "Resuming archives the current study, so both remain recoverable."
                )
                if st.button("Resume selected study"):
                    store.resume(chosen)
                    st.session_state.pop("context", None)
                    st.session_state.pop("selected_tooth", None)
                    st.session_state.records = []
                    st.rerun()
        with st.expander("Restore measurement JSON"):
            st.caption(
                "Imports preserve existing records. Imported tooth locations need visual confirmation before new measurements."
            )
            upload = st.file_uploader("Measurement JSON array", type=["json"])
            if upload and st.button("Import records"):
                try:
                    store.migrate(sid, json.load(upload))
                    st.rerun()
                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    jsonschema.ValidationError,
                ) as exc:
                    st.error(f"Cannot import: {exc}")


def protocol_settings(store, sid, teeth):
    config = store.settings(sid)
    with st.sidebar.expander("Measurement settings"):
        st.caption(
            "Routine: one measurement per registered tooth. Research: choose a target, conditions and repeated readings."
        )
        mode = st.radio(
            "Workflow type",
            ["routine", "research"],
            index=["routine", "research"].index(config["mode"]),
            format_func=lambda x: (
                "Routine measurement" if x == "routine" else "Research protocol"
            ),
            key=f"mode_{sid}",
        )
        target = None
        conditions = ["raw"]
        rounds = 1
        if mode == "research":
            goal = st.checkbox(
                "Set a target tooth count",
                value=config["target"] is not None,
                key=f"goal_{sid}",
            )
            if goal:
                target = st.number_input(
                    "Target teeth",
                    min_value=1,
                    value=config["target"] or max(len(teeth), 1),
                    step=1,
                    key=f"target_{sid}",
                )
            conditions = st.multiselect(
                "Included image conditions",
                ["raw", "he", "clahe"],
                default=config["conditions"],
                key=f"conditions_{sid}",
            )
            rounds = st.number_input(
                "Reading rounds",
                min_value=1,
                value=config["rounds"],
                step=1,
                key=f"rounds_{sid}",
            )
        st.caption(
            "Changing settings preserves every existing record and tooth location. A target is a progress goal, not a registration limit."
        )
        if st.button("Apply settings"):
            try:
                store.configure(sid, mode, target, conditions, int(rounds))
                st.session_state.notice = "Measurement settings updated. Existing records and drafts are preserved."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    return config


def main():
    st.set_page_config(page_title="PBL · Tooth measurements", layout="wide")
    st.markdown(
        "<style>.block-container{padding-top:2rem;padding-bottom:1rem}h1{font-size:2rem!important}[data-testid=stMain]{overflow-anchor:none;scroll-behavior:auto!important}.st-key-measurement-workspace{min-height:1100px}</style>",
        unsafe_allow_html=True,
    )
    st.title("PBL · Tooth measurements")
    st.caption(
        "Register teeth → place landmarks → record measurements. Educational research tool."
    )
    st.session_state.setdefault("points", {})
    st.session_state.setdefault("epoch", 0)
    store = StudyStore()
    sid = store.active()
    # The first upgrade rerun preserves the old in-memory study before any UI changes.
    if not st.session_state.get("durable_migrated"):
        legacy = st.session_state.get("records", [])
        if legacy:
            store.migrate(sid, legacy)
        st.session_state.durable_migrated = True
    records = store.records(sid)
    st.session_state.records = records
    teeth = store.teeth(sid)
    config = store.settings(sid)
    research = config["mode"] == "research"
    conditions = config["conditions"]
    rounds = list(range(1, config["rounds"] + 1))
    target = max(config["target"] or 0, len(teeth))
    planned = target * len(conditions) * len(rounds)
    if notice := st.session_state.pop("notice", None):
        st.success(notice)
    with st.sidebar:
        st.header("Measurement workflow")
        workflow = st.radio("Step", ["Register teeth", "Measure teeth"], key="workflow")
        st.caption(
            f"{len(teeth)} teeth registered"
            + (f" · {planned} planned measurements" if research else "")
        )
        if research:
            condition = st.selectbox(
                "Image condition", conditions, disabled=workflow == "Register teeth"
            )
            rnd = st.selectbox(
                "Independent reading round",
                rounds,
                disabled=workflow == "Register teeth",
            )
            blind = st.checkbox(
                "Blind reading: hide results", value=True, key=f"blind_{sid}_research"
            )
        else:
            condition, rnd, blind = "raw", 1, False
        if research:
            st.caption(
                "Repeat the same registered teeth in every image condition and round."
            )
        crown = st.checkbox(
            "Optional crown landmark for ratio check",
            disabled=workflow == "Register teeth",
        )
        zoom = st.slider("Image width (pixels)", 600, 1800, 1100, 100)
        st.caption(
            "Use Pan image to move without marking."
            + (
                " Re-mark each condition independently; use a washout interval between rounds."
                if research
                else ""
            )
        )
    if workflow == "Register teeth":
        with st.sidebar:
            upload = st.file_uploader(
                "Add X-ray", type=["jpg", "jpeg", "png", "tif", "tiff"]
            )
            sample = st.selectbox(
                "Or sample X-ray", sorted(p.name for p in SAMPLES.glob("*.jpg"))
            )
    st.session_state.active_condition = condition
    st.session_state.active_round = rnd
    study_tools(store, sid, records)
    protocol_settings(store, sid, teeth)
    if workflow == "Register teeth":
        st.subheader("1 · Register the teeth you want to measure")
        st.caption(
            "Click the centre of a clearly identifiable tooth crown, then Register tooth. This is a location reminder, not a measurement landmark. Register each physical tooth only once."
        )
        image_id = upload.name if upload else sample
        data = upload.getvalue() if upload else (SAMPLES / sample).read_bytes()
        try:
            original, prepared, digest = load_images(data, "raw")
            store.image(sid, image_id, data)
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            st.error(f"Cannot add image: {exc}")
            return
        change_context((sid, "register", image_id, digest))
        registration_panel(store, sid, prepared, digest, image_id, teeth, zoom, config)
    elif not teeth:
        st.info("First choose Register teeth and create your fixed tooth list.")
    else:
        # Keep the outer workspace footprint while a fragment is being reconciled.
        with st.container(key="measurement-workspace"):
            measurement_workspace(store, sid, config, blind, zoom, crown)


@st.fragment
def measurement_workspace(store, sid, config, blind, zoom, crown):
    records = store.records(sid)
    st.session_state.records = records
    teeth = store.teeth(sid)
    research = config["mode"] == "research"
    conditions = config["conditions"]
    rounds = list(range(1, config["rounds"] + 1))
    target = max(config["target"] or 0, len(teeth))
    condition = st.session_state.get("active_condition", conditions[0])
    rnd = st.session_state.get("active_round", rounds[0])
    st.subheader("2 · Measure registered teeth")
    if research and rnd > 1:
        previous = [
            created
            for (_, c, r), created in store.record_times(sid).items()
            if c == condition and r == rnd - 1 and created
        ]
        if previous:
            st.caption(
                f"Round {rnd - 1} of {condition.upper()} was last recorded "
                f"{elapsed_text(max(previous))} ago. Repeat readings are only independent "
                "if you no longer remember the earlier clicks. Published reader studies often "
                "use about 2–4 weeks; no fixed minimum is mandated, so follow your protocol."
            )
    saved = {
        r["tooth_id"]
        for r in records
        if r["condition"] == condition and r["round"] == rnd
    }
    ids = [t["id"] for t in teeth]
    if research:
        # A different, reproducible order per reading so sequence cannot cue recall.
        ids = reading_order(ids, f"{sid}:{condition}:{rnd}")
    pending = [i for i in ids if i not in saved]
    st.progress(
        min(len(saved) / max(target, 1), 1.0),
        text=(f"{condition.upper()} · Round {rnd}: " if research else "")
        + f"{len(saved)} / {target} teeth recorded",
    )
    st.caption(
        ("Pending IDs in reading order: " if research else "Pending IDs: ")
        + (", ".join(map(str, pending)) or "None among registered teeth")
        + (
            f" · Target remaining to register: {max(0, (config['target'] or 0) - len(teeth))}"
            if config["target"]
            else ""
        )
    )
    if st.session_state.get("reading_context") != (sid, condition, rnd):
        st.session_state.reading_context = (sid, condition, rnd)
        st.session_state.selected_tooth = (pending or ids)[0]
    elif st.session_state.get("selected_tooth") not in ids:
        st.session_state.selected_tooth = ids[0]
    picker, previous = st.columns([3, 1])
    with picker:
        tid = st.selectbox(
            "Registered tooth",
            ids,
            key="selected_tooth",
            format_func=lambda x: f"Tooth {x:02d}",
        )
    with previous:
        st.button(
            "Previous tooth",
            disabled=tid == ids[0],
            width="stretch",
            on_click=select_tooth,
            args=(ids[max(0, ids.index(tid) - 1)],),
        )
    position = ids.index(tid)
    candidates = [i for i in ids[position + 1 :] + ids[:position] if i in pending]
    next_id = (candidates or [tid])[0]
    tooth = next(t for t in teeth if t["id"] == tid)
    image_id = tooth["image"]
    data = store.image_data(sid, image_id)
    if data is None and image_id in {p.name for p in SAMPLES.glob("*.jpg")}:
        data = (SAMPLES / image_id).read_bytes()
        store.image(sid, image_id, data)
    if data is None:
        st.warning(
            f"Add the original image {image_id} in Register teeth to continue this imported study."
        )
        return
    original, prepared, digest = load_images(data, condition)
    context = (sid, "measure", tid, condition, rnd, crown)
    locked = tid in saved
    change_context(
        context,
        (
            {}
            if locked
            else {
                k: v
                for k, v in store.draft(sid, tid, condition, rnd).items()
                if k in POINTS or (crown and k == "crown")
            }
        ),
    )
    st.caption(
        f"Tooth {tid:02d} · {image_id} · "
        + (f"{condition.upper()} · Round {rnd} · " if research else "")
        + ("RECORDED" if locked else "NOT RECORDED")
    )
    measurement_panel(
        store,
        sid,
        prepared,
        digest,
        tooth,
        teeth,
        condition,
        rnd,
        blind,
        zoom,
        crown,
        locked,
        next_id,
        bool(candidates),
        records,
    )
    with st.expander("Tooth checklist"):
        st.caption(
            "Results stay hidden in blind mode; completion status remains visible."
        )
        rows = []
        for t in teeth:
            row = {"Tooth": t["id"], "Image": t["image"]}
            for c in conditions:
                for n in rounds:
                    row[f"{c.upper()} R{n}" if research else "Measurement"] = (
                        "Recorded"
                        if any(
                            r["tooth_id"] == t["id"]
                            and r["condition"] == c
                            and r["round"] == n
                            for r in records
                        )
                        else "Pending"
                    )
            rows.append(row)
        st.dataframe(rows, hide_index=True, width="stretch")
    if records:
        with st.expander("Export measurements"):
            st.download_button(
                "Export measurements JSON",
                json_export(records),
                "measurements.json",
                "application/json",
            )
            st.download_button(
                "Export measurements CSV",
                csv_export(records),
                "measurements.csv",
                "text/csv",
            )
            if amendments := store.amendments(sid):
                st.download_button(
                    f"Export amendment log ({len(amendments)})",
                    json.dumps(amendments, indent=2) + "\n",
                    "amendments.json",
                    "application/json",
                )
    if not blind and records:
        with st.expander("Review exported records"):
            st.json(records)


@st.fragment
def registration_panel(store, sid, prepared, digest, image_id, teeth, zoom, config):
    local = [t for t in teeth if t["image"] == image_id]
    width = prepared.width
    confirmed = store.midline(sid, image_id)
    suggestion = (
        suggest_midline(digest, prepared) if is_panoramic(prepared.size) else None
    )
    with st.expander("Dental midline for this image", expanded=confirmed is None):
        st.caption(
            "Mesial means the tooth surface that faces the dental midline (the line "
            "between the two central incisors); distal faces away from it. Which image "
            "side is mesial therefore changes from tooth to tooth."
        )
        where_options = ["inside", "left", "right"]
        where = st.radio(
            "Where is the dental midline?",
            where_options,
            index=(
                0
                if confirmed is not None and 0 <= confirmed < width
                else 1 if confirmed == -1
                else 2 if confirmed == width
                else 0 if suggestion
                else None
            ),
            format_func=lambda x: {
                "inside": "Inside this image (panoramic)",
                "left": "Beyond the left edge",
                "right": "Beyond the right edge",
            }[x],
            horizontal=True,
            key=f"midline_where_{digest}",
        )
        preview = None
        if where == "inside":
            default = (
                confirmed
                if confirmed is not None and 0 <= confirmed < width
                else suggestion[0] if suggestion else width // 2
            )
            preview = int(
                st.number_input(
                    "Midline column (original pixels)",
                    min_value=0,
                    max_value=width - 1,
                    value=default,
                    step=5,
                    key=f"midline_x_{digest}",
                )
            )
            if suggestion:
                st.caption(
                    f"Suggested from left–right symmetry: x = {suggestion[0]} "
                    f"(score {suggestion[1]:.2f}). This is a guess to check, not "
                    "detection: confirm the pink line passes between the upper central "
                    "incisors, and use the R/L marker to check orientation."
                )
        elif where is not None:
            preview = -1 if where == "left" else width
            st.caption(
                "For a periapical or bitewing: choose the edge that faces the front "
                "of the mouth (toward the incisors and canines)."
            )
        if st.button(
            "Confirm midline",
            disabled=preview is None or preview == confirmed,
        ):
            store.set_midline(sid, image_id, preview, width)
            st.rerun()
        if confirmed is not None and preview == confirmed:
            st.caption("Midline confirmed for this image.")
    landmark_canvas(
        prepared,
        (digest, "raw"),
        ("locator",),
        ("Tooth crown centre",),
        zoom,
        markers=local,
        midline=preview,
        midline_confirmed=preview is not None and preview == confirmed,
    )
    a, b = st.columns(2)
    a.button("Clear location", on_click=clear_points)
    if confirmed is None:
        st.caption(
            "Optional: confirm the dental midline to get mesial/distal side hints."
        )
    if b.button(
        "Register tooth",
        type="primary",
        disabled="locator" not in st.session_state.points,
    ):
        try:
            tid = store.register(
                sid, image_id, st.session_state.points["locator"], prepared.size
            )
            clear_points()
            st.session_state.notice = f"Tooth {tid:02d} registered. Its number and location stay fixed in every condition and round."
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    st.caption(
        f"{len(teeth)} teeth registered. Numbered boxes show existing locations. Register as many teeth as needed; visually check that each ID is a different tooth."
    )
    if teeth:
        st.dataframe(
            [
                {
                    "Tooth": t["id"],
                    "Image": t["image"],
                    "Location": f"({t['x']}, {t['y']})",
                    "Status": (
                        "Registered"
                        if t["confirmed"]
                        else "Imported · confirm location"
                    ),
                }
                for t in teeth
            ],
            hide_index=True,
        )


def measurement_panel(
    store,
    sid,
    prepared,
    digest,
    tooth,
    teeth,
    condition,
    rnd,
    blind,
    zoom,
    crown,
    locked,
    next_id,
    has_next,
    records,
):
    tid = tooth["id"]
    midline = store.midline(sid, tooth["image"])
    side = mesial_side(tooth["x"], midline)
    names = POINTS + (("crown",) if crown else ())
    labels = side_labels(side) + (
        ("Crown tip / incisal midpoint",) if crown else ()
    )
    points = st.session_state.points
    if not locked:
        store.draft(sid, tid, condition, rnd, points)
    saved_here = {
        r["tooth_id"]
        for r in records
        if r["condition"] == condition and r["round"] == rnd
    }
    markers = [
        dict(t, selected=t["id"] == tid, saved=t["id"] in saved_here)
        for t in teeth
        if t["image"] == tooth["image"]
    ]
    left, right = st.columns([3, 1])
    with left:
        landmark_canvas(
            prepared,
            (digest, condition),
            names,
            labels,
            zoom,
            markers=markers,
            locked=locked,
            focus=[tooth["x"], tooth["y"]],
            midline=midline,
        )
        a, b = st.columns(2)
        a.button("Clear current landmarks", on_click=clear_points, disabled=locked)
        b.button("Undo last point", on_click=undo_point, disabled=locked)
    with right:
        st.subheader(f"Tooth {tid:02d}")
        record_button = st.empty()
        st.button(
            "Next tooth →",
            key="next-tooth-near-image",
            disabled=not has_next or not locked,
            on_click=select_tooth,
            args=(next_id,),
            width="stretch",
        )
        st.caption(
            "Save this tooth before moving on."
            if not locked
            else (
                "Saved. Continue with Next tooth."
                if has_next
                else "Saved. All registered teeth in this reading are complete."
            )
        )
        if locked:
            record_button.button(
                "Record tooth", key="record-tooth-action", disabled=True
            )
            st.success("Recorded · saved locally")
            if not blind:
                saved_record = next(
                    r
                    for r in records
                    if r["tooth_id"] == tid
                    and r["condition"] == condition
                    and r["round"] == rnd
                )
                metrics = saved_record["metrics"]
                st.metric("Mesial PBL", f"{metrics['mesial_pbl_pct']:.2f}%")
                st.metric("Distal PBL", f"{metrics['distal_pbl_pct']:.2f}%")
                st.metric("Worse-side stage", metrics["stage"])
            with st.expander("Amend this reading"):
                st.caption(
                    "Reopens this tooth for this condition and round so you can mark "
                    "it again from scratch. The original reading and your reason are "
                    "kept in the amendment log."
                )
                reason_key = f"amend_reason_{tid}_{condition}_{rnd}"
                st.text_input(
                    "Reason",
                    key=reason_key,
                    placeholder="e.g. misclicked the distal crest",
                )
                st.button(
                    "Reopen for re-marking",
                    on_click=reopen_reading,
                    args=(store, sid, tid, condition, rnd, reason_key),
                )
                if error := st.session_state.get("save_error"):
                    st.error(error)
            st.caption(
                (
                    "Use Next tooth beside the image. Other conditions and rounds remain independent."
                    if has_next
                    else "All registered teeth in this reading are saved. Export a copy before starting the next reading."
                )
            )
            return
        if not tooth["confirmed"]:
            st.warning(
                "Imported location: visually check the numbered box against the original tooth before measuring."
            )
            if st.button("Confirm imported tooth location"):
                store.confirm(sid, tid)
                st.rerun()
        st.caption(f"{len(points)} / {len(names)} landmarks · Draft saved locally")
        if side is None:
            st.caption(
                "No dental midline confirmed for this image, so mesial/distal side "
                "hints are off (optional: set it in Register teeth)."
            )
        else:
            st.caption(
                f"Mesial side for this tooth: {'image right →' if side == 'right' else '← image left'}"
            )
        if swapped := swapped_surfaces(points, side):
            parts = " and ".join(
                "CEJ" if s == "cej" else "bone crest" for s in swapped
            )
            st.warning(
                f"Check mesial/distal: the mesial {parts} is on the distal side of its "
                "partner. Undo and re-place unless the tooth is strongly tilted or rotated."
            )
        record = None
        if len(points) == len(names):
            try:
                if any(
                    not (0 <= x < prepared.width and 0 <= y < prepared.height)
                    for x, y in points.values()
                ):
                    raise PBLValidationError("Landmarks must be inside the image")
                lm = ToothLandmarks(
                    SideLandmarks(points["mesial.cej"], points["mesial.bc"]),
                    SideLandmarks(points["distal.cej"], points["distal.bc"]),
                    points["apex"],
                )
                result = calculate_tooth_pbl(lm)
                record = make_record(tooth["image"], tid, condition, rnd, lm)
                st.info("Ready to record · review your landmarks")
                st.caption("Geometry checks do not verify anatomical accuracy.")
                if not blind:
                    st.metric("Mesial PBL", f"{result.mesial.pbl_pct:.2f}%")
                    st.metric("Distal PBL", f"{result.distal.pbl_pct:.2f}%")
                    st.metric("Worse-side stage", result.stage)
                if "crown" in points:
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter(
                                "ignore", AnatomicalPlausibilityWarning
                            )
                            crowned = calculate_tooth_pbl(
                                replace(lm, crown=points["crown"])
                            )
                        if not blind:
                            st.write(
                                f"Root-to-crown ratio: {crowned.root_to_crown_ratio:.3f}"
                            )
                            for msg in crowned.warnings:
                                st.warning(msg)
                    except DegenerateGeometryError as exc:
                        st.warning(f"Crown point ignored: {exc}")
            except (PBLValidationError, jsonschema.ValidationError) as exc:
                st.error(str(exc))
        if error := st.session_state.get("save_error"):
            st.error(error)
        record_button.button(
            "Record tooth",
            key="record-tooth-action",
            type="primary",
            disabled=record is None or not tooth["confirmed"],
            on_click=save_measurement,
            args=(store, sid, record),
        )


if __name__ == "__main__":
    if "next_workflow" in st.session_state:
        st.session_state.workflow = st.session_state.pop("next_workflow")
    try:
        main()
    except (sqlite3.Error, OSError, ValueError) as exc:
        st.error(
            f"Cannot save or load this study: {exc}. Your existing stored data has not been cleared."
        )
