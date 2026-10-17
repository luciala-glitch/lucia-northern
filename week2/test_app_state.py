"""Regression checks for Streamlit session-state behavior."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from week2.repeatability import POINT_NAMES, make_measurement_row, save_measurement


POINTS = {
    name: (100, 100 + index * 10)
    for index, name in enumerate(POINT_NAMES)
}


def _element_with_label(elements, label):
    return next(element for element in elements if element.label == label)


def _write_paired_measurements(path: Path) -> None:
    """Create a tiny deterministic CSV so UI tests never use study data."""
    for round_name, pbl in (("Round 1", 20), ("Round 2", 22)):
        save_measurement(
            path,
            make_measurement_row(
                observer="Lucia",
                round_name=round_name,
                image_id="xray-1",
                tooth_id="T1",
                image_size=(100, 100),
                points=POINTS,
                mesial_pbl=pbl - 1,
                distal_pbl=pbl,
                worst_side="Distal",
                worst_pbl=pbl,
                stage="Stage II",
                app_version="test-version",
            ),
        )


def _load_app(monkeypatch, tmp_path):
    week2_dir = Path(__file__).resolve().parent
    measurements_path = tmp_path / "measurements.csv"
    _write_paired_measurements(measurements_path)
    monkeypatch.setenv("PBL_MEASUREMENTS_PATH", str(measurements_path))
    monkeypatch.setenv("PBL_APP_VERSION", "test-version")
    monkeypatch.syspath_prepend(str(week2_dir))
    return AppTest.from_file(str(week2_dir / "app.py")).run(timeout=10)


def test_round2_is_blind_until_completed_and_completion_persists(
    monkeypatch, tmp_path
):
    app = _load_app(monkeypatch, tmp_path)

    _element_with_label(app.selectbox, "Reading session").select(
        "Round 2"
    ).run(timeout=10)

    assert _element_with_label(app.toggle, "Blind reading mode").value
    assert not any(metric.label == "Paired teeth" for metric in app.metric)

    _element_with_label(
        app.checkbox, "Complete Round 2 and reveal results"
    ).check().run(timeout=10)

    assert not _element_with_label(app.toggle, "Blind reading mode").value
    assert _element_with_label(
        app.checkbox, "Complete Round 2 and reveal results"
    ).value
    assert _element_with_label(app.metric, "Paired teeth").value == "1"

    # Completion is durable even if the conditional checkbox is unmounted.
    _element_with_label(app.selectbox, "Reading session").select(
        "Round 1"
    ).run(timeout=10)
    _element_with_label(app.selectbox, "Reading session").select(
        "Round 2"
    ).run(timeout=10)

    assert _element_with_label(
        app.checkbox, "Complete Round 2 and reveal results"
    ).value
    assert not _element_with_label(app.toggle, "Blind reading mode").value
    assert _element_with_label(app.metric, "Paired teeth").value == "1"

    _element_with_label(app.button, "＋").click().run(timeout=10)
    assert _element_with_label(
        app.checkbox, "Complete Round 2 and reveal results"
    ).value
    assert _element_with_label(app.metric, "Paired teeth").value == "1"


def test_blind_reading_mode_hides_agreement_and_survives_interaction(
    monkeypatch, tmp_path
):
    app = _load_app(monkeypatch, tmp_path)
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
