from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from week3.study import StudyStore, reading_order

APP = Path(__file__).resolve().parents[1] / "app.py"
POINTS = {
    "mesial.cej": (40, 20),
    "mesial.bc": (40, 40),
    "distal.cej": (60, 20),
    "distal.bc": (60, 50),
    "apex": (50, 120),
}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PBL_STUDY_DB", str(tmp_path / "ui.sqlite3"))


def button(app, label):
    return next(b for b in app.button if b.label == label)


def select(app, label):
    return next(s for s in app.selectbox if s.label == label)


def measured_app(research=True):
    if research:
        store = StudyStore()
        store.configure(store.active(), "research", 15, ["raw", "he", "clahe"], 2)
    app = AppTest.from_file(str(APP)).run(timeout=20)
    button(app, "Confirm midline").click().run()
    app.session_state.points = {"locator": (50, 20)}
    app.run()
    button(app, "Register tooth").click().run()
    next(r for r in app.radio if r.label == "Step").set_value("Measure teeth").run()
    assert not app.exception
    return app


def two_teeth():
    """Register a second tooth; return the app and this reading's tooth order."""
    app = measured_app()
    s = StudyStore()
    sid = s.active()
    s.register(sid, s.teeth(sid)[0]["image"], (300, 20), (2041, 1024))
    # The reading order is fixed once a reading starts, so reset it to see tooth 2.
    app.session_state.reading_context = None
    app.run()
    return app, reading_order([1, 2], f"{sid}:raw:1")


def test_registration_and_saved_location():
    app = measured_app()
    assert select(app, "Registered tooth").value == 1
    assert button(app, "Record tooth").disabled
    assert any("Pending IDs in reading order: 1" in c.value for c in app.caption)
    assert len(StudyStore().teeth(StudyStore().active())) == 1


def test_record_lock_duplicate_and_new_condition():
    app = measured_app()
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    assert not app.exception and len(app.session_state.records) == 1
    assert button(app, "Record tooth").disabled
    assert button(app, "Clear current landmarks").disabled
    select(app, "Image condition").select("he").run()
    assert app.session_state.points == {}
    assert button(app, "Record tooth").disabled
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    assert len(app.session_state.records) == 2


def test_refresh_restores_draft_and_tooth_roster():
    app = measured_app()
    app.session_state.points = {"mesial.cej": (40, 20)}
    app.run()
    fresh = AppTest.from_file(str(APP)).run(timeout=20)
    next(r for r in fresh.radio if r.label == "Step").set_value("Measure teeth").run()
    assert fresh.session_state.points == {"mesial.cej": (40, 20)}
    select(fresh, "Independent reading round").select(2).run()
    assert fresh.session_state.points == {}
    select(fresh, "Independent reading round").select(1).run()
    assert fresh.session_state.points == {"mesial.cej": (40, 20)}


def test_undo_and_invalid_geometry():
    app = measured_app()
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Undo last point").click().run()
    assert list(app.session_state.points) == list(POINTS)[:-1]
    app.session_state.points = {**POINTS, "mesial.bc": (40, 0)}
    app.run()
    assert any("project between" in e.value for e in app.error)
    assert button(app, "Record tooth").disabled


def test_optional_crown_and_blind_results():
    app = measured_app()
    next(c for c in app.checkbox if c.label.startswith("Optional crown")).check().run()
    app.session_state.points = {**POINTS, "crown": (50, 30)}
    app.run()
    assert any("Crown point ignored" in w.value for w in app.warning)
    assert not app.metric
    next(c for c in app.checkbox if c.label.startswith("Blind reading")).uncheck().run()
    assert len(app.metric) == 3
    button(app, "Record tooth").click().run()
    assert len(app.session_state.records) == 1


def test_start_over_is_archived_and_recoverable():
    app = measured_app()
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    old = StudyStore().active()
    button(app, "Start over…").click().run()
    assert StudyStore().active() == old  # Opening the dialog never resets data.
    button(app, "Archive current study and start new").click().run()
    assert not app.exception
    assert app.session_state.records == [] and StudyStore().active() != old
    button(app, "Resume selected study").click().run()
    assert not app.exception
    assert len(app.session_state.records) == 1 and StudyStore().active() == old


def test_next_pending_tooth_follows_reading_order():
    app, order = two_teeth()
    assert select(app, "Registered tooth").value == order[0]
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    button(app, "Next tooth →").click().run()
    assert not app.exception
    assert select(app, "Registered tooth").value == order[1]


def test_saved_first_tooth_can_navigate_second_and_back():
    app, order = two_teeth()
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    assert len(app.session_state.records) == 1
    button(app, "Next tooth →").click().run()
    assert select(app, "Registered tooth").value == order[1]
    assert not button(app, "Clear current landmarks").disabled
    button(app, "Previous tooth").click().run()
    assert select(app, "Registered tooth").value == order[0]
    assert button(app, "Clear current landmarks").disabled
    select(app, "Registered tooth").select(order[1]).run()
    assert select(app, "Registered tooth").value == order[1]
    assert len(app.session_state.records) == 1


def test_routine_uses_registered_count_and_no_research_controls():
    app = measured_app(research=False)
    assert not any(
        s.label in ("Image condition", "Independent reading round")
        for s in app.selectbox
    )
    assert any(m.value == "1 teeth registered" for m in app.caption)
    assert app.get("progress")[0].proto.text == "0 / 1 teeth recorded"
    app.session_state.points = dict(POINTS)
    app.run()
    assert len(app.metric) == 3
    button(app, "Record tooth").click().run()
    assert len(app.metric) == 3
    assert len(app.session_state.records) == 1


def test_configure_research_in_ui_without_losing_saved_records():
    app = measured_app(research=False)
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    next(r for r in app.radio if r.label == "Workflow type").set_value("research").run()
    next(c for c in app.checkbox if c.label == "Set a target tooth count").check().run()
    next(n for n in app.number_input if n.label == "Target teeth").set_value(5).run()
    app.multiselect[0].set_value(["raw", "clahe"]).run()
    next(n for n in app.number_input if n.label == "Reading rounds").set_value(3).run()
    button(app, "Apply settings").click().run()
    assert not app.exception
    assert StudyStore().settings(StudyStore().active()) == dict(
        mode="research", target=5, conditions=["raw", "clahe"], rounds=3
    )
    assert len(app.session_state.records) == 1
    assert select(app, "Independent reading round").options == ["1", "2", "3"]
    next(r for r in app.radio if r.label == "Workflow type").set_value("routine").run()
    button(app, "Apply settings").click().run()
    assert len(app.session_state.records) == 1
    assert not any(s.label == "Image condition" for s in app.selectbox)


def test_save_keeps_current_points_and_refreshes_workspace_export():
    app = measured_app()
    app.session_state.points = dict(POINTS)
    app.run()
    epoch = app.session_state.epoch
    button(app, "Record tooth").click().run()
    assert not app.exception
    assert app.session_state.points == POINTS
    assert app.session_state.epoch == epoch
    assert app.get("progress")[0].proto.text == "RAW · Round 1: 1 / 15 teeth recorded"
    assert app.session_state.records == StudyStore().records(StudyStore().active())


def test_near_image_next_requires_save_and_moves_to_next_tooth():
    app, order = two_teeth()
    near = lambda: next(b for b in app.button if b.key == "next-tooth-near-image")
    assert near().disabled
    assert sum(b.label.startswith("Next") for b in app.button) == 1
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    assert not near().disabled
    near().click().run()
    assert not app.exception and select(app, "Registered tooth").value == order[1]


def test_midline_is_optional_and_suggested():
    app = AppTest.from_file(str(APP)).run(timeout=20)
    assert any("Suggested from left–right symmetry" in c.value for c in app.caption)
    app.session_state.points = {"locator": (50, 20)}
    app.run()
    button(app, "Register tooth").click().run()
    store = StudyStore()
    assert len(store.teeth(store.active())) == 1  # no midline required
    next(r for r in app.radio if r.label == "Step").set_value("Measure teeth").run()
    assert any("side hints are off" in c.value for c in app.caption)
    next(r for r in app.radio if r.label == "Step").set_value("Register teeth").run()
    button(app, "Confirm midline").click().run()
    assert 0 <= store.midline(store.active(), "kaggle_dental_xray_1.jpg") < 2041


def test_mesial_side_prompt_and_swap_warning():
    # Tooth 1 sits left of the panoramic midline, so its mesial side is image right.
    app = measured_app()
    assert any("Mesial side for this tooth: image right" in c.value for c in app.caption)
    app.session_state.points = dict(POINTS)  # mesial CEJ placed image-left: swapped
    app.run()
    assert any("Check mesial/distal" in w.value for w in app.warning)
    app.session_state.points = {
        "mesial.cej": (60, 20),
        "mesial.bc": (60, 50),
        "distal.cej": (40, 20),
        "distal.bc": (40, 40),
        "apex": (50, 120),
    }
    app.run()
    assert not any("Check mesial/distal" in w.value for w in app.warning)


def test_round_two_shows_time_since_round_one():
    app = measured_app()
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    select(app, "Independent reading round").select(2).run()
    assert any("Round 1 of RAW was last recorded" in c.value for c in app.caption)


def test_amend_reopens_reading_and_keeps_original():
    app = measured_app()
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    button(app, "Reopen for re-marking").click().run()
    assert any("short reason" in e.value for e in app.error)
    assert len(app.session_state.records) == 1
    next(t for t in app.text_input if t.label == "Reason").input(
        "misclicked the distal crest"
    ).run()
    button(app, "Reopen for re-marking").click().run()
    assert not app.exception
    store = StudyStore()
    sid = store.active()
    assert store.records(sid) == []
    log = store.amendments(sid)
    assert log[0]["reason"] == "misclicked the distal crest"
    assert log[0]["original_record"]["landmarks"]["apex"] == [50, 120]
    assert app.session_state.points == {}  # re-mark from scratch, no prefill
    app.session_state.points = dict(POINTS)
    app.run()
    button(app, "Record tooth").click().run()
    assert len(store.records(sid)) == 1
    assert len(store.amendments(sid)) == 1
