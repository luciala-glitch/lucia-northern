"""End-to-end Streamlit check of auto-detect -> review -> correct -> recalculate -> save."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import week4.app as app_module
from week5.review import validate_bundle

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def review_app(fake_refined, tmp_path, monkeypatch):
    monkeypatch.setenv("PBL_WEIGHTS", str(tmp_path / "no_week4_weights"))
    monkeypatch.setenv("PBL_CORRECTIONS", str(tmp_path / "corrections.json"))
    monkeypatch.setenv("PBL_PRACTICE", str(tmp_path / "practice.json"))
    monkeypatch.setattr(app_module, "CORRECTIONS", tmp_path / "corrections.json")
    app = AppTest.from_file(str(APP))
    app.session_state["reviewer_role"] = app_module.QUALIFIED
    app.session_state["reviewer_id"] = "R-week5"
    app.session_state["blind_first"] = False
    return app


def run(app: AppTest) -> AppTest:
    app = app.run(timeout=60)
    assert not app.exception, app.exception
    return app


def button(app: AppTest, label: str):
    return next(b for b in app.button if b.label == label)


def test_refined_workflow_from_suggestion_to_saved_correction(review_app, tmp_path):
    app = run(review_app)
    assert any("Week 5" in m.value for m in app.markdown)
    detector = next(s for s in app.selectbox if s.label == "Automatic detector")
    assert detector.options[0] == app_module.REFINED and detector.value == app_module.REFINED

    app = run(button(app, "Run AI suggestion").click())
    prediction = app.session_state["prediction"]
    assert prediction.stage_probabilities is not None
    assert any(c.value.startswith("AI stage probability") for c in app.caption)
    assert any(e.label.startswith("Compare AI suggestion") for e in app.expander)
    auto_stage = next(m for m in app.metric if m.label == "Corrected stage").value
    auto_points = dict(app.session_state["points"])

    # A canvas drag: both crests moved 40% of the root length apically.
    moved = dict(auto_points)
    root = abs(moved["apex"][1] - moved["mesial.cej"][1])
    for name in ("mesial.bc", "distal.bc"):
        moved[name] = (moved[name][0], moved[name][1] + round(0.4 * root) * (1 if moved["apex"][1] > moved[name][1] else -1))
    app.session_state["points"] = moved
    app = run(app)
    corrected_stage = next(m for m in app.metric if m.label == "Corrected stage").value
    assert corrected_stage == "III/IV" != auto_stage
    change = next(m for m in app.metric if m.label == "Change").value
    assert change.startswith("+")

    for checkbox in [c for c in app.checkbox if c.label in app_module.LABELS]:
        checkbox.check()
    app = run(app)
    app = run(button(app, "Save review & next tooth").click())
    saved = json.loads((tmp_path / "corrections.json").read_text())
    assert len(saved) == 1
    bundle = saved[0]
    validate_bundle(bundle)
    assert bundle["detector"]["name"] == app_module.REFINED
    assert len(bundle["detector"]["checkpoints"]) == 10
    assert bundle["original_prediction"]["metrics"]["stage"] == auto_stage
    assert bundle["corrected_result"]["metrics"]["stage"] == "III/IV"
    assert bundle["moved_px"]["mesial_bc"] > 10 and bundle["moved_px"]["apex"] == 0
    assert set(bundle["auto_stage_probabilities"]) == {"I", "II", "III/IV"}


def test_boundary_warning_after_a_correction_near_15_percent(review_app):
    app = run(review_app)
    app = run(button(app, "Run AI suggestion").click())
    points = dict(app.session_state["points"])
    assert not any("Boundary case" in i.value for i in app.info)
    cej_y = (points["mesial.cej"][1] + points["distal.cej"][1]) / 2
    root = points["apex"][1] - cej_y
    for name in ("mesial.bc", "distal.bc"):
        points[name] = (points[name][0], round(cej_y + 0.14 * root))
    app.session_state["points"] = points
    app = run(app)
    pbl = float(next(m for m in app.metric if m.label == "Corrected PBL").value.rstrip("%"))
    assert abs(pbl - 15) < app_module.BOUNDARY_WARNING_PP
    assert any("Boundary case" in i.value for i in app.info)
