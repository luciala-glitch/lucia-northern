"""Regression checks for Streamlit session-state behavior."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def _element_with_label(elements, label):
    return next(element for element in elements if element.label == label)


def test_round2_summary_stays_revealed_after_another_interaction(monkeypatch):
    week2_dir = Path(__file__).resolve().parent
    monkeypatch.syspath_prepend(str(week2_dir))

    app = AppTest.from_file(str(week2_dir / "app.py")).run(timeout=10)
    _element_with_label(app.toggle, "Blind reading mode").set_value(True).run(
        timeout=10
    )
    _element_with_label(app.selectbox, "Reading session").select(
        "Round 2"
    ).run(timeout=10)
    _element_with_label(
        app.checkbox, "Complete Round 2 and reveal results"
    ).check().run(timeout=10)

    assert not _element_with_label(app.toggle, "Blind reading mode").value
    assert _element_with_label(
        app.checkbox, "Complete Round 2 and reveal results"
    ).value
    assert _element_with_label(app.metric, "Paired teeth").value == "10"

    _element_with_label(app.button, "＋").click().run(timeout=10)

    assert _element_with_label(
        app.checkbox, "Complete Round 2 and reveal results"
    ).value
    assert _element_with_label(app.metric, "Paired teeth").value == "10"


def test_blind_reading_mode_hides_agreement_and_survives_interaction(monkeypatch):
    week2_dir = Path(__file__).resolve().parent
    monkeypatch.syspath_prepend(str(week2_dir))

    app = AppTest.from_file(str(week2_dir / "app.py")).run(timeout=10)
    app.session_state["measurement_points"] = {
        "mesial_cej": (0, 0),
        "mesial_bone_crest": (0, 2),
        "mesial_root_tip": (0, 10),
        "distal_cej": (10, 0),
        "distal_bone_crest": (10, 3),
        "distal_root_tip": (10, 10),
    }
    app.run(timeout=10)

    assert _element_with_label(app.metric, "Mesial PBL").value == "20.0%"
    assert not _element_with_label(app.button, "Save reading").disabled

    _element_with_label(app.toggle, "Blind reading mode").set_value(True).run(
        timeout=10
    )

    assert _element_with_label(app.toggle, "Blind reading mode").value
    assert not any(metric.label == "Mesial PBL" for metric in app.metric)
    assert not any(metric.label == "Paired teeth" for metric in app.metric)
    assert not _element_with_label(app.button, "Save reading").disabled
    assert any("agreement are hidden" in info.value for info in app.info)

    _element_with_label(app.button, "＋").click().run(timeout=10)

    assert _element_with_label(app.toggle, "Blind reading mode").value
    assert not any(metric.label == "Paired teeth" for metric in app.metric)
