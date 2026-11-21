"""End-to-end checks of the Streamlit reporting app (headless)."""

from __future__ import annotations

import copy

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from week7.cases import build_demo_cases  # noqa: E402
from week7.edge_cases import build_edge_cases  # noqa: E402
from week7.report import build_case_report  # noqa: E402

APP = "week7/app.py"
EDGE_KEYS = ["[edge] EDGE-missing-apex", "[edge] EDGE-one-surface", "[edge] EDGE-invalid-correction",
             "[edge] no case id"]


def _app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    return at


def _select(at: AppTest, case_id: str, simulated: bool = True) -> None:
    at.sidebar.selectbox[0].set_value(case_id).run()
    box = at.sidebar.checkbox[0]
    if box.value != simulated:
        (box.check() if simulated else box.uncheck()).run()
    assert not at.exception


def _case(at: AppTest, case_id: str, simulated: bool = True) -> dict:
    return at.session_state["cases"][f"demo|{case_id}|{simulated}"]


def _save_button(at: AppTest):
    return [b for b in at.button if b.label.startswith("Save correction for ")][0]


def _save(at: AppTest, reviewer: str) -> None:
    at.text_input[0].input(reviewer)
    _save_button(at).click().run()
    assert not at.exception


def _pick_tooth(at: AppTest, row: int) -> None:
    at.selectbox(key=[w.key for w in at.selectbox if w.key and w.key.startswith("tooth|")][0]).set_value(row).run()
    assert not at.exception


def test_app_values_match_report_for_every_demo_case():
    at = _app()
    for case in build_demo_cases():
        _select(at, case["case_id"])
        report = build_case_report(case)
        table = at.dataframe[0].value
        assert len(table) == len(report["teeth"])
        for (_, row), t in zip(table.iterrows(), report["teeth"]):
            assert row["PBL (worse) %"] == pytest.approx(round(t["final"]["pbl_max_pct"], 1))
            assert row["Mesial %"] == pytest.approx(round(t["final"]["mesial"]["pbl_pct"], 1))
            assert row["Distal %"] == pytest.approx(round(t["final"]["distal"]["pbl_pct"], 1))
            assert row["Stage"] == t["final"]["stage"]
            assert row["AI PBL %"] == pytest.approx(round(t["auto"]["measurement"]["pbl_max_pct"], 1))


@pytest.mark.parametrize("key", EDGE_KEYS)
def test_edge_cases_render_without_crash(key):
    at = _app()
    _select(at, key)
    assert {d.label for d in at.get("download_button")} == {"PDF case report", "CSV (tooth-level)", "JSON (complete case)"}
    text = " ".join(m.value for m in at.markdown)
    assert "0.0%" not in text  # a missing value is never shown as zero


def test_switching_cases_does_not_carry_coordinates_over():
    """Regression: edit case 5 without saving, switch to case 68, save -> case 68 must keep its own points."""
    at = _app()
    _select(at, "DENPAR-TEST-5")
    at.number_input[0].set_value(123.45).run()
    _select(at, "DENPAR-TEST-68")
    before = dict(_case(at, "DENPAR-TEST-68")["teeth"][0]["manual"]["landmarks"])
    _save(at, "reviewer-B")
    after = _case(at, "DENPAR-TEST-68")["teeth"][0]["manual"]["landmarks"]
    assert after == before
    assert all(123.45 not in p for p in after.values() if p)
    assert _case(at, "DENPAR-TEST-5")["teeth"][0].get("manual") is None or \
        _case(at, "DENPAR-TEST-5")["teeth"][0]["manual"]["landmarks"]["mesial_cej"][0] != 123.45


def test_correction_history_and_trace():
    at = _app()
    _select(at, "DENPAR-TEST-68", simulated=False)
    assert at.metric[4].value == "0"
    apex_y = at.number_input[9]
    apex_y.set_value(apex_y.value + 60).run()
    _save(at, "reviewer-A")
    at.number_input[9].set_value(at.number_input[9].value + 20).run()
    _save(at, "reviewer-B")
    tooth = _case(at, "DENPAR-TEST-68", simulated=False)["teeth"][0]
    assert [e["reviewer_id"] for e in tooth["correction_history"]] == ["reviewer-A", "reviewer-B"]
    assert tooth["manual"]["reviewer_id"] == "reviewer-B"
    assert tooth["manual"]["landmarks"]["mesial_cej"] == tooth["auto"]["landmarks"]["mesial_cej"]  # untouched point kept exactly
    assert at.metric[4].value == "1"
    assert at.dataframe[0].value.iloc[0]["Reported from"] == "Reviewer correction (reviewer-B)"
    report = build_case_report(_case(at, "DENPAR-TEST-68", simulated=False))
    assert len(report["teeth"][0]["correction_history"]) == 2
    # removal is recorded too
    at.text_input(key=[w.key for w in at.text_input if w.key.endswith("|remover")][0]).input("reviewer-C")
    [b for b in at.button if b.label == "Remove correction for T1"][0].click().run()
    tooth = _case(at, "DENPAR-TEST-68", simulated=False)["teeth"][0]
    assert tooth["manual"] is None
    assert [e["action"] for e in tooth["correction_history"]] == ["save", "save", "remove"]
    assert at.dataframe[0].value.iloc[0]["Reported from"] == "Automated"


def test_missing_landmark_stays_missing_when_saving():
    at = _app()
    _select(at, "[edge] EDGE-one-surface")
    _pick_tooth(at, 1)
    _save(at, "reviewer-A")
    tooth = at.session_state["cases"]["demo|[edge] EDGE-one-surface|True"]["teeth"][1]
    assert tooth["manual"]["landmarks"]["distal_bc"] is None
    report = build_case_report(at.session_state["cases"]["demo|[edge] EDGE-one-surface|True"])
    assert report["teeth"][1]["final"]["status"] == "partial"


def test_reviewer_id_required():
    at = _app()
    _select(at, "DENPAR-TEST-68", simulated=False)
    _save_button(at).click().run()
    assert any("Reviewer ID is required" in e.value for e in at.error)
    assert at.metric[4].value == "0"


def test_edge_case_list_matches_builder():
    assert len(build_edge_cases()) == len(EDGE_KEYS)


def _text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [e.value for e in at.success] + [e.value for e in at.info] + [e.value for e in at.error]
    return "\n".join(parts)


def test_case68_t4_review_scenario():
    """Acceptance: Case 68 -> T4 once -> see AI 31.2% -> simulated 35.0%, moved points, editing T4, export T4."""
    at = _app()
    _select(at, "DENPAR-TEST-68")
    assert any(h.value == "Case DENPAR-TEST-68" for h in at.subheader)
    _pick_tooth(at, 3)
    text = _text(at)
    assert "**Reported from:** Simulated correction" in text
    assert "31.2% · Stage II" in text and "35.0% · Stage III/IV" in text
    assert "**Stage set by:** distal surface (35.0%)" in text
    assert "moved Distal CEJ, Distal bone crest" in text
    assert "#### Edit landmarks · T4" in text
    assert _save_button(at).label == "Save correction for T4"
    others_before = [copy.deepcopy(t) for i, t in enumerate(_case(at, "DENPAR-TEST-68")["teeth"]) if i != 3]
    apex_y = at.number_input[9]
    apex_y.set_value(apex_y.value + 40).run()
    _save(at, "Lucia")
    teeth = _case(at, "DENPAR-TEST-68")["teeth"]
    assert teeth[3]["manual"]["reviewer_id"] == "Lucia"
    assert [t for i, t in enumerate(teeth) if i != 3] == others_before   # only T4 changed
    assert any(e.value.startswith("Saved for T4 by Lucia. The report now uses this correction") for e in at.success)
    report = build_case_report(_case(at, "DENPAR-TEST-68"))
    assert report["teeth"][3]["final"]["source"] == "manual"
    assert at.dataframe[0].value.iloc[3]["Reported from"] == "Reviewer correction (Lucia)"
    assert at.metric[4].value == str(report["summary"]["teeth_reported_from_manual"])


def test_unattributed_correction_not_counted_and_explained():
    case = copy.deepcopy(next(c for c in build_demo_cases() if c["case_id"] == "DENPAR-TEST-68"))
    case["teeth"][0]["manual"]["reviewer_id"] = None
    r = build_case_report(case)
    assert r["summary"]["teeth_reported_from_manual"] == 3
    assert r["summary"]["teeth_manually_corrected"] == 4


def test_discard_needs_confirmation():
    at = _app()
    _select(at, "DENPAR-TEST-68", simulated=False)
    _save(at, "reviewer-A")
    assert at.metric[4].value == "1"
    discard = [b for b in at.sidebar.button if b.label == "Discard my edits for this case"][0]
    discard.click().run()
    assert at.metric[4].value == "1"  # nothing cleared yet
    assert any("T1" in w.value for w in at.sidebar.warning)
    [b for b in at.sidebar.button if b.label == "Confirm discard"][0].click().run()
    assert at.metric[4].value == "0"
    assert _case(at, "DENPAR-TEST-68", simulated=False)["teeth"][0].get("manual") is None


@pytest.mark.parametrize("key", ["[edge] no case id", "[edge] EDGE-missing-apex"])
def test_review_panel_works_without_image_or_landmarks(key):
    at = _app()
    _select(at, key)
    for row in range(len(at.selectbox(key=[w.key for w in at.selectbox if w.key and w.key.startswith("tooth|")][0]).options)):
        _pick_tooth(at, row)
        assert "#### Edit landmarks · " in _text(at)
