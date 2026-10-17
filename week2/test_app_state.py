"""Regression checks for Streamlit session-state behavior."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def _element_with_label(elements, label):
    return next(element for element in elements if element.label == label)


def test_round2_summary_stays_revealed_after_another_interaction(monkeypatch):
    week2_dir = Path(__file__).resolve().parent
    monkeypatch.syspath_prepend(str(week2_dir))

    app = AppTest.from_file(str(week2_dir / "app.py")).run()
    _element_with_label(app.selectbox, "Measurement round").select(
        "Round 2"
    ).run()
    _element_with_label(
        app.checkbox, "I've finished Round 2 — show results"
    ).check().run()

    assert _element_with_label(app.checkbox, "I've finished Round 2 — show results").value
    assert _element_with_label(app.metric, "Paired teeth").value == "10"

    _element_with_label(app.button, "＋").click().run()

    assert _element_with_label(app.checkbox, "I've finished Round 2 — show results").value
    assert _element_with_label(app.metric, "Paired teeth").value == "10"
