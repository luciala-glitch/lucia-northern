"""Persistent image canvas: browser draws markers without reloading the X-ray."""

from __future__ import annotations
import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from PIL import Image
import streamlit as st
import streamlit.components.v1 as components

_canvas = components.declare_component(
    "pbl_landmark_canvas_v6", path=str(Path(__file__).with_name("landmark_canvas"))
)


@st.cache_data(show_spinner=False, max_entries=16)
def image_source(source_key: tuple[str, str], _image: Image.Image) -> str:
    """PNG data URL cached by (image digest, condition); no re-encode per click."""
    buffer = BytesIO()
    _image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(
        "ascii"
    )


def _resync() -> None:
    """Force the browser to redraw from the server's accepted points."""
    st.session_state.epoch += 1
    st.session_state.canvas_revision = 0


def accept_canvas_event(
    key: str,
    names: tuple[str, ...],
    size: tuple[int, int],
    image_id: str | None = None,
    locked: bool = False,
) -> None:
    """Validate original-pixel coordinates, sequence, epoch and event ordering."""
    event = st.session_state.get(key)
    if not isinstance(event, dict):
        return
    if event.get("type") in ("image_ready", "image_needed"):
        # An acknowledgement is valid only for the image currently being rendered.
        if image_id is not None and event.get("image_id") == image_id:
            st.session_state.canvas_image_ack = (
                image_id if event["type"] == "image_ready" else None
            )
        return
    if locked:
        return
    if event.get("epoch") != st.session_state.epoch:
        return
    if image_id is not None and event.get("image_id") != image_id:
        return
    revision = event.get("revision")
    if type(revision) is not int or revision <= st.session_state.get(
        "canvas_revision", 0
    ):
        return
    incoming = event.get("points")
    if (
        not isinstance(incoming, dict)
        or len(incoming) > len(names)
        or list(incoming) != list(names[: len(incoming)])
    ):
        _resync()
        return
    checked = {}
    for name, xy in incoming.items():
        if (
            not isinstance(xy, list)
            or len(xy) != 2
            or any(type(v) is not int for v in xy)
            or not (0 <= xy[0] < size[0] and 0 <= xy[1] < size[1])
        ):
            # A current event with a bad payload would otherwise leave the browser
            # showing markers the server never accepted.
            _resync()
            return
        checked[name] = tuple(xy)
    st.session_state.points = checked
    st.session_state.canvas_revision = revision
    if image_id is not None:
        # Point events also acknowledge the loaded image if the load event coalesced.
        st.session_state.canvas_image_ack = image_id


def landmark_canvas(
    image: Image.Image,
    source_key: tuple[str, str],
    names: tuple[str, ...],
    labels: tuple[str, ...],
    width: int,
    *,
    markers: list | None = None,
    locked: bool = False,
    focus: list | None = None,
    focus_box: list | None = None,
    midline: int | None = None,
    midline_confirmed: bool = True,
    confidence: dict[str, float] | None = None,
    reference: dict[str, list[float]] | None = None,
    locked_message: str | None = None,
) -> None:
    key = "landmark-canvas-v6"
    image_id = hashlib.sha256(json.dumps(source_key).encode()).hexdigest()
    # Once the browser confirms decoding this image, subsequent updates carry only
    # the small geometry payload. A new/reloaded iframe can explicitly request it.
    src = (
        None
        if st.session_state.get("canvas_image_ack") == image_id
        else image_source(source_key, image)
    )
    _canvas(
        markers=markers or [],
        locked=locked,
        focus=focus,
        focus_box=focus_box,
        midline=midline,
        midline_confirmed=midline_confirmed,
        confidence=confidence or {},
        reference=reference or {},
        locked_message=locked_message,
        src=src,
        image_id=image_id,
        image_width=image.width,
        image_height=image.height,
        display_width=width,
        names=list(names),
        labels=list(labels),
        points={name: list(xy) for name, xy in st.session_state.points.items()},
        epoch=st.session_state.epoch,
        revision=st.session_state.get("canvas_revision", 0),
        key=key,
        default=None,
        on_change=lambda: accept_canvas_event(key, names, image.size, image_id, locked),
    )
