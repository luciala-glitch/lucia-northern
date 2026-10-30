from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import week4.app as app_module

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def no_checkpoints(tmp_path, monkeypatch):
    # CI has no weights; the review flow must still work with the baseline.
    monkeypatch.setenv("PBL_WEIGHTS", str(tmp_path))
    monkeypatch.setenv("PBL_CORRECTIONS", str(tmp_path / "corrections.json"))
    monkeypatch.setenv("PBL_PRACTICE", str(tmp_path / "practice.json"))


def run(app: AppTest) -> AppTest:
    return app.run(timeout=60)


def qualified(blind_first: bool = False) -> AppTest:
    app = AppTest.from_file(str(APP))
    app.session_state["reviewer_role"] = app_module.QUALIFIED
    app.session_state["reviewer_id"] = "R-test"
    app.session_state["blind_first"] = blind_first
    return app


def start() -> AppTest:
    return run(qualified())


def test_orientation_defaults_follow_denpar_site_sheet():
    apex, mesial_left, note = app_module._orientation_defaults("external_test", "1.jpg")
    assert apex is True and mesial_left is False and "Right" in note
    assert app_module._orientation_defaults("nowhere", "x.jpg")[:2] == (True, True)


def test_baseline_suggestion_flags_and_gates_export_until_confirmed():
    app = start()
    assert not app.exception
    detector = next(s for s in app.selectbox if s.label == "Automatic detector")
    assert detector.options == [app_module.BASELINE]
    app = run(next(b for b in app.button if b.label == "Run AI suggestion").click())
    assert not app.exception
    labels = [m.label for m in app.metric]
    assert "Corrected stage" in labels
    assert any("AI suggestion:" in caption.value for caption in app.caption)
    assert any("Flagged" in w.value for w in app.warning)
    confirms = [c for c in app.checkbox if c.label in app_module.LABELS]
    assert len(confirms) == 5 and not any(c.value for c in confirms)
    save = next(b for b in app.button if b.label.startswith("To save:"))
    assert save.disabled and "tick all 5 landmarks" in save.label
    for checkbox in confirms:
        checkbox.check()
    app = run(app)
    assert not next(b for b in app.button if b.label == "Save review & next tooth").disabled


def test_blind_first_read_disables_reveal_until_five_points():
    app = run(qualified(blind_first=True))
    button = next(b for b in app.button if b.label == "Reveal AI suggestion")
    assert button.disabled
    assert any("Blind first read" in i.value for i in app.info)


def button(app: AppTest, label: str):
    return next(b for b in app.button if b.label == label)


def test_undo_and_reset_restore_earlier_landmarks():
    app = start()
    assert button(app, "↶ Undo").disabled
    assert button(app, "Reset to AI").disabled
    app = run(button(app, "Run AI suggestion").click())
    suggestion = dict(app.session_state["points"])
    assert button(app, "↶ Undo").disabled
    # A canvas drag arrives as a new points dict before the script reruns.
    moved = dict(suggestion)
    x, y = moved["apex"]
    moved["apex"] = (x + 30, y)
    app.session_state["points"] = moved
    app = run(app)
    assert not button(app, "↶ Undo").disabled
    epoch = app.session_state["epoch"]
    app = run(button(app, "↶ Undo").click())
    assert app.session_state["points"] == suggestion
    assert app.session_state["epoch"] > epoch  # the canvas redraws the restored points
    assert button(app, "↶ Undo").disabled
    app.session_state["points"] = moved
    app = run(app)
    app = run(button(app, "Reset to AI").click())
    assert app.session_state["points"] == suggestion
    app = run(button(app, "↶ Undo").click())
    assert app.session_state["points"] == moved


def test_clear_points_before_suggestion():
    app = run(qualified(blind_first=True))
    assert button(app, "Clear points").disabled
    app.session_state["points"] = {"mesial.cej": (100, 100), "mesial.bc": (100, 140)}
    app = run(app)
    app = run(button(app, "Clear points").click())
    assert app.session_state["points"] == {}
    app = run(button(app, "↶ Undo").click())
    assert app.session_state["points"] == {"mesial.cej": (100, 100), "mesial.bc": (100, 140)}
    assert not app.exception


def test_save_advances_on_the_next_rerun_without_widget_state_error(tmp_path):
    app = start()
    app = run(button(app, "Run AI suggestion").click())
    for checkbox in [c for c in app.checkbox if c.label in app_module.LABELS]:
        checkbox.check()
    app = run(app)
    app = run(button(app, "Save review & next tooth").click())
    assert not app.exception
    assert app.session_state["demo_image"] == "10.jpg"
    assert app.session_state["tooth_box"] == 1
    saved = json.loads((tmp_path / "corrections.json").read_text())
    assert len(saved) == 1
    assert saved[0]["annotator_role"] == "qualified_reviewer"
    assert saved[0]["reviewer_id"] == "R-test"


def test_qualified_save_needs_reviewer_id():
    app = qualified()
    app.session_state["reviewer_id"] = ""
    app = run(button(run(app), "Run AI suggestion").click())
    for checkbox in [c for c in app.checkbox if c.label in app_module.LABELS]:
        checkbox.check()
    app = run(app)
    save = next(b for b in app.button if b.label.startswith("To save:"))
    assert save.disabled and "Reviewer ID" in save.label


def test_two_reviewers_keep_separate_slots(tmp_path, monkeypatch):
    path = tmp_path / "corrections.json"
    monkeypatch.setattr(app_module, "CORRECTIONS", path)
    result = {"image_id": "image.jpg", "tooth_id": 1, "condition": "raw", "round": 1}
    app_module._save_bundle({"reviewer_id": "A", "corrected_result": result})
    app_module._save_bundle({"reviewer_id": "B", "corrected_result": result})
    assert len(json.loads(path.read_text())) == 2
    assert len(app_module._latest_manual_records("A")) == 1


def test_resaving_same_review_slot_replaces_it(tmp_path, monkeypatch):
    path = tmp_path / "corrections.json"
    monkeypatch.setattr(app_module, "CORRECTIONS", path)
    result = {"image_id": "image.jpg", "tooth_id": 1, "condition": "raw", "round": 1}
    first = {"saved_at_utc": "first", "corrected_result": result}
    second = {"saved_at_utc": "second", "corrected_result": result}
    app_module._save_bundle(first)
    app_module._save_bundle(second)
    saved = json.loads(path.read_text())
    assert len(saved) == 1
    assert saved[0]["saved_at_utc"] == "second"


def test_anterior_orientation_flips_across_the_midline():
    boxes = app_module._sample_boxes(
        "10.jpg", app_module.DEMO_ROOT / "development" / "official_annotations" / "keypoints"
    )
    # 10.jpg is a lower anterior film: box 2 lies right of the midline, box 3 left of it.
    assert app_module._orientation_defaults("development", "10.jpg", boxes, 1, 885)[1] is True
    assert app_module._orientation_defaults("development", "10.jpg", boxes, 2, 885)[1] is False
    references = app_module._development_references()
    assert references["10.jpg"][1]["mesial_on_left"] is True
    assert references["10.jpg"][2]["mesial_on_left"] is False


def test_practice_lists_only_reference_teeth_and_hides_external_test():
    app = run(AppTest.from_file(str(APP)))
    assert not app.exception
    assert app.session_state["reviewer_role"] == app_module.TRAINEE
    assert not any(r.label == "DenPAR partition" for r in app.radio)
    assert not any(t.label == "Blind first read" for t in app.toggle)
    tooth = next(s for s in app.selectbox if s.label.startswith("Tooth"))
    assert tooth.options == ["Tooth 2 of 6 on this image", "Tooth 3 of 6 on this image"]
    assert any("2 of the 6 teeth on this image can be practised" in c.value for c in app.caption)
    # 40 of the 90 Development demo boxes have a complete five-point reference.
    assert any("0/40 reference teeth" in str(p.proto) for p in app.get("progress"))


def test_practice_submit_reveals_reference_saves_separately_and_advances(tmp_path):
    app = run(AppTest.from_file(str(APP)))
    submit = button(app, "Submit & show expert reference")
    assert submit.disabled
    reference = app_module._development_references()["10.jpg"][1]["landmarks"]
    app.session_state["points"] = {
        app_module.TO_CANVAS[name]: (round(x) + 3, round(y) + 4) for name, (x, y) in reference.items()
    }
    app = run(app)
    app = run(button(app, "Submit & show expert reference").click())
    assert not app.exception
    saved = json.loads((tmp_path / "practice.json").read_text())
    assert len(saved) == 1
    record = saved[0]
    assert record["purpose"] == "practice" and record["not_ground_truth"] is True
    assert (record["image_id"], record["tooth_id"]) == ("denpar_development_10.jpg", 2)
    assert all(3 <= error <= 6 for error in record["error_px"].values())
    assert not (tmp_path / "corrections.json").exists()
    assert any(m.label == "Expert PBL" for m in app.metric)
    # After submitting, only the next/retry actions remain under the image.
    assert not any(b.label in {"Clear my points", "↶ Undo last change"} for b in app.button)
    app = run(button(app, "Next reference tooth →").click())
    assert not app.exception
    assert app.session_state["tooth_box"] == 2
    assert "practice_result" not in app.session_state


def test_practice_retry_clears_the_locked_read(tmp_path):
    app = run(AppTest.from_file(str(APP)))
    reference = app_module._development_references()["10.jpg"][1]["landmarks"]
    app.session_state["points"] = {
        app_module.TO_CANVAS[name]: (round(x), round(y)) for name, (x, y) in reference.items()
    }
    app = run(button(run(app), "Submit & show expert reference").click())
    app = run(button(app, "↺ Try this tooth again").click())
    assert app.session_state["points"] == {}
    assert button(app, "Submit & show expert reference").disabled


def test_ui_test_records_do_not_count_as_practice(tmp_path, monkeypatch):
    path = tmp_path / "legacy_practice.json"
    monkeypatch.setattr(app_module, "PRACTICE", path)
    legacy = {"purpose": "ui_test", "image_id": "denpar_development_10.jpg", "tooth_id": 2}
    path.write_text(json.dumps([legacy]))
    references = app_module._development_references()
    names = ["10.jpg", "101.jpg"]
    assert app_module._next_practice(names, references, ("101.jpg", 1)) == ("10.jpg", 1)
    app_module._append_practice({**legacy, "purpose": "practice"})
    assert app_module._next_practice(names, references, ("101.jpg", 1)) == ("10.jpg", 2)


def test_box_at_picks_the_smallest_box_containing_the_click():
    boxes = [[0, 0, 100, 100], [40, 40, 60, 60], [200, 0, 300, 100]]
    assert app_module._box_at((50, 50), boxes) == 1
    assert app_module._box_at((10, 10), boxes) == 0
    assert app_module._box_at((150, 50), boxes) is None


def test_reviewer_selects_tooth_by_clicking_the_image():
    app = start()
    app = run(button(app, "👆 Select tooth on image").click())
    assert app.session_state["picking_tooth"] is True
    assert any("Select a tooth" in m.value for m in app.markdown)
    # 10.jpg box 3 spans x 234-456: a click inside it selects that tooth.
    app.session_state["points"] = {"locator": (300, 600)}
    app = run(app)
    assert not app.exception
    assert app.session_state["picking_tooth"] is False
    assert app.session_state["tooth_box"] == 2
    assert app.session_state["points"] == {}


def test_click_outside_every_tooth_asks_again():
    app = start()
    app = run(button(app, "👆 Select tooth on image").click())
    app.session_state["points"] = {"locator": (5, 5)}
    app = run(app)
    assert app.session_state["picking_tooth"] is True
    assert any("not inside any tooth box" in w.value for w in app.warning)
    app = run(button(app, "Cancel — keep the current tooth").click())
    assert app.session_state["picking_tooth"] is False
