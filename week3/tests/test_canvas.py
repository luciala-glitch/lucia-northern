"""Guard coordinate correctness across asynchronous canvas updates and undo/reset."""

from types import SimpleNamespace
import pytest
from week3 import canvas

NAMES = ("mesial.cej", "mesial.bc", "distal.cej", "distal.bc", "apex")


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def test_canvas_accepts_ordered_original_pixels_and_latest_revision(monkeypatch):
    state = State(epoch=3, points={}, canvas_revision=0)
    monkeypatch.setattr(canvas, "st", SimpleNamespace(session_state=state))
    state["canvas"] = {"epoch": 3, "revision": 1, "points": {"mesial.cej": [796, 597]}}
    canvas.accept_canvas_event("canvas", NAMES, (2041, 1024))
    assert state.points == {"mesial.cej": (796, 597)}
    assert state.canvas_revision == 1
    # A batched rapid click event can supersede intermediate acknowledgements.
    state["canvas"] = {
        "epoch": 3,
        "revision": 3,
        "points": {
            "mesial.cej": [796, 597],
            "mesial.bc": [759, 694],
            "distal.cej": [722, 584],
        },
    }
    canvas.accept_canvas_event("canvas", NAMES, (2041, 1024))
    assert len(state.points) == 3
    assert state.canvas_revision == 3


@pytest.mark.parametrize(
    "event",
    [
        None,
        {"epoch": 2, "revision": 9, "points": {}},
        {"epoch": 3, "revision": 1, "points": {}},
        {"epoch": 3, "revision": True, "points": {}},
    ],
)
def test_canvas_ignores_stale_events_without_losing_points(monkeypatch, event):
    state = State(epoch=3, points={"mesial.cej": (20, 20)}, canvas_revision=1)
    monkeypatch.setattr(canvas, "st", SimpleNamespace(session_state=state))
    state["canvas"] = event
    canvas.accept_canvas_event("canvas", NAMES, (2041, 1024))
    assert state.points == {"mesial.cej": (20, 20)}
    assert state.canvas_revision == 1
    assert state.epoch == 3


@pytest.mark.parametrize(
    "points",
    [
        [],
        {"apex": [5, 5]},
        {"mesial.cej": [2041, 10]},
        {"mesial.cej": [-1, 10]},
        {"mesial.cej": [2.2, 10]},
        {"mesial.cej": [True, 10]},
        {"mesial.cej": [2]},
        {"mesial.cej": "2,3"},
    ],
)
def test_canvas_resyncs_browser_after_invalid_current_event(monkeypatch, points):
    state = State(epoch=3, points={"mesial.cej": (20, 20)}, canvas_revision=1)
    monkeypatch.setattr(canvas, "st", SimpleNamespace(session_state=state))
    state["canvas"] = {"epoch": 3, "revision": 2, "points": points}
    canvas.accept_canvas_event("canvas", NAMES, (2041, 1024))
    assert state.points == {"mesial.cej": (20, 20)}
    # New epoch makes the browser discard its unaccepted markers.
    assert state.epoch == 4
    assert state.canvas_revision == 0


def test_image_ack_removes_large_payload_and_reload_can_request_it(monkeypatch):
    import json
    from PIL import Image

    state = State(epoch=1, points={}, canvas_revision=0)
    monkeypatch.setattr(canvas, "st", SimpleNamespace(session_state=state))
    payloads = []
    monkeypatch.setattr(canvas, "_canvas", lambda **kwargs: payloads.append(kwargs))
    source = "data:image/png;base64," + "a" * 1_300_000
    monkeypatch.setattr(canvas, "image_source", lambda *args: source)
    image = Image.new("L", (2041, 1024))

    def render(source_key=("image-digest", "raw")):
        canvas.landmark_canvas(image, source_key, NAMES, NAMES, 1100)
        return payloads[-1]

    first = render()
    assert first["src"] == source
    state[first["key"]] = {"type": "image_ready", "image_id": first["image_id"]}
    first["on_change"]()
    after = render()
    assert after["src"] is None
    # Measure the serialized component arguments, excluding its Python callback.
    wire = lambda p: len(
        json.dumps(
            {k: v for k, v in p.items() if k not in ("on_change", "default")}
        ).encode()
    )
    assert wire(after) < 1024
    assert wire(after) < wire(first) / 1000
    state[first["key"]] = {
        "type": "points",
        "image_id": first["image_id"],
        "epoch": 1,
        "revision": 1,
        "points": {"mesial.cej": [796, 597]},
    }
    after["on_change"]()
    assert state.points == {"mesial.cej": (796, 597)}
    assert render()["src"] is None
    # A reloaded iframe lacks the decoded image even though Python has an ack.
    state[first["key"]] = {"type": "image_needed", "image_id": first["image_id"]}
    after["on_change"]()
    assert render()["src"] == source
    assert render(("image-digest", "clahe"))["src"] == source
    assert state.points == {"mesial.cej": (796, 597)}


def test_old_image_messages_cannot_change_current_image_or_landmarks(monkeypatch):
    state = State(
        epoch=2,
        points={"mesial.cej": (20, 20)},
        canvas_revision=1,
        canvas_image_ack="current",
    )
    monkeypatch.setattr(canvas, "st", SimpleNamespace(session_state=state))
    for kind in ("image_ready", "image_needed", "points"):
        state["canvas"] = {
            "type": kind,
            "image_id": "old",
            "epoch": 2,
            "revision": 99,
            "points": {"mesial.cej": [99, 99]},
        }
        canvas.accept_canvas_event("canvas", NAMES, (2041, 1024), "current")
        assert state.canvas_image_ack == "current"
        assert state.points == {"mesial.cej": (20, 20)}
        assert state.canvas_revision == 1


def test_recorded_canvas_rejects_late_point_event_but_accepts_image_ack(monkeypatch):
    state = State(epoch=3, points={}, canvas_revision=0)
    monkeypatch.setattr(canvas, "st", SimpleNamespace(session_state=state))
    state["canvas"] = {
        "type": "points",
        "image_id": "current",
        "epoch": 3,
        "revision": 9,
        "points": {"mesial.cej": [20, 20]},
    }
    canvas.accept_canvas_event("canvas", NAMES, (2041, 1024), "current", locked=True)
    assert state.points == {} and state.canvas_revision == 0
    state["canvas"] = {"type": "image_ready", "image_id": "current"}
    canvas.accept_canvas_event("canvas", NAMES, (2041, 1024), "current", locked=True)
    assert state.canvas_image_ack == "current"
