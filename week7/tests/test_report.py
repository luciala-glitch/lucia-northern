"""Report calculations: independent recomputation, traceability, missing/incomplete data."""

from __future__ import annotations

import copy
import math

import pytest

from week3.pbl_calculator import SideLandmarks, ToothLandmarks, calculate_tooth_pbl
from week7.cases import build_demo_cases, reference_values
from week7.edge_cases import build_edge_cases
from week7.report import build_case_report, measure

CASES = build_demo_cases()
CASE_IDS = [c["case_id"] for c in CASES]


def _independent(lm):
    return calculate_tooth_pbl(ToothLandmarks(
        SideLandmarks(lm["mesial_cej"], lm["mesial_bc"]),
        SideLandmarks(lm["distal_cej"], lm["distal_bc"]),
        lm["apex"],
    ))


def test_at_least_ten_representative_cases():
    assert len(CASES) >= 10
    stages = {t["auto"]["stage_probabilities"] and max(t["auto"]["stage_probabilities"], key=t["auto"]["stage_probabilities"].get)
              for c in CASES for t in c["teeth"]}
    assert stages == {"I", "II", "III/IV"}
    assert any(t["manual"] for c in CASES for t in c["teeth"])
    assert any(t["manual"] is None for c in CASES for t in c["teeth"])


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_reported_values_match_independent_calculation(case):
    report = build_case_report(case)
    for tin, t in zip(case["teeth"], report["teeth"]):
        src = t["final"]["source"]
        assert src in ("auto", "manual")
        lm = tin["manual"]["landmarks"] if src == "manual" else tin["auto"]["landmarks"]
        exp = _independent(lm)
        assert t["final"]["mesial"]["pbl_pct"] == pytest.approx(exp.mesial.pbl_pct, abs=1e-9)
        assert t["final"]["distal"]["pbl_pct"] == pytest.approx(exp.distal.pbl_pct, abs=1e-9)
        assert t["final"]["pbl_max_pct"] == pytest.approx(exp.pbl_max_pct, abs=1e-9)
        assert t["final"]["stage"] == exp.stage


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_automated_values_match_week5_saved_predictions(case):
    ref = reference_values()
    report = build_case_report(case)
    for t in report["teeth"]:
        saved = ref[(report["case_id"], t["tooth_id"])]
        assert t["auto"]["measurement"]["pbl_max_pct"] == pytest.approx(saved["auto_pbl_saved"], abs=1e-9)
        assert t["auto"]["measurement"]["stage"] == saved["auto_stage_saved"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_correction_never_overwrites_automated_record(case):
    original = copy.deepcopy(case)
    report = build_case_report(case)
    assert case == original  # input untouched
    for tin, t in zip(case["teeth"], report["teeth"]):
        assert t["auto"]["landmarks"] == tin["auto"]["landmarks"]
        if tin["manual"] is not None:
            assert t["manual"]["landmarks"] == tin["manual"]["landmarks"]
            assert t["final"]["source"] == "manual"
            assert t["manual"]["reviewer_id"] and t["manual"]["saved_at_utc"] and t["manual"]["method"]
            moved = {n for n, d in t["manual"]["moved_px"].items() if d and d > 1e-6}
            assert moved == set(t["manual"]["changed_landmarks"])
        else:
            assert t["final"]["source"] == "auto"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_flag_logic_and_stage_change_warning(case):
    report = build_case_report(case)
    for t in report["teeth"]:
        p = t["auto"]["stage_probability"]
        assert t["review_flagged"] == (p < 0.94 or t["auto"]["orientation_switched"])
        codes = {w["code"] for w in t["warnings"]}
        changed = t["manual"] and t["manual"]["measurement"]["stage"] != t["auto"]["measurement"]["stage"]
        assert ("STAGE_CHANGED_BY_CORRECTION" in codes) == bool(changed)
        if t["final"]["pbl_max_pct"] is not None:
            near = any(abs(t["final"]["pbl_max_pct"] - b) <= 3.0 for b in (15, 33))
            assert ("NEAR_STAGE_BOUNDARY" in codes) == near


def test_case_summary_counts():
    for case in CASES:
        r = build_case_report(case)
        s = r["summary"]
        assert sum(s["stage_counts"].values()) == s["teeth_staged"] == len(r["teeth"])
        order = ["I", "II", "III/IV"]
        assert s["highest_tooth_stage"] == max((t["final"]["stage"] for t in r["teeth"]), key=order.index)


@pytest.mark.parametrize("value,stage", [(14.99, "I"), (15.0, "II"), (33.0, "II"), (33.01, "III/IV")])
def test_stage_boundaries(value, stage):
    # Vertical tooth: CEJ y=0, apex y=100, so crest y == PBL %.
    lm = {"mesial_cej": [0, 0], "distal_cej": [10, 0], "mesial_bc": [0, value], "distal_bc": [10, 1],
          "apex": [5, 100]}
    m = measure(lm)
    assert m["status"] == "ok"
    assert m["pbl_max_pct"] == pytest.approx(value)
    assert m["stage"] == stage


def test_missing_apex_gives_no_stage():
    r = build_case_report(build_edge_cases()[0])
    t = r["teeth"][0]
    assert t["final"]["source"] == "none"
    assert t["final"]["stage"] is None and t["final"]["pbl_max_pct"] is None
    codes = {w["code"] for w in t["warnings"]}
    assert {"MISSING_LANDMARKS", "FLAGGED_NOT_REVIEWED"} <= codes
    assert t["review_flagged"]
    assert r["summary"]["teeth_not_staged"] == 1


def test_one_surface_reports_minimum_stage_only():
    r = build_case_report(build_edge_cases()[1])
    t = r["teeth"][1]
    assert t["final"]["status"] == "partial"
    assert t["final"]["stage"] is None
    assert t["final"]["distal"] is None
    assert t["final"]["minimum_stage"] == "II"  # mesial 17.1%
    assert "SINGLE_SURFACE_ONLY" in {w["code"] for w in t["warnings"]}


def test_invalid_correction_is_not_reported():
    r = build_case_report(build_edge_cases()[2])
    t = r["teeth"][2]
    assert t["manual"]["measurement"]["status"] == "invalid"
    assert t["final"]["source"] == "none" and t["final"]["stage"] is None
    assert t["auto"]["measurement"]["status"] == "ok"  # automated record still kept
    assert "CORRECTION_INVALID" in {w["code"] for w in t["warnings"]}


def test_incomplete_case_data():
    r = build_case_report(build_edge_cases()[3])
    codes = {w["code"] for w in r["case_warnings"]}
    assert {"MISSING_CASE_ID", "NO_IMAGE", "DUPLICATE_TOOTH_ID"} <= codes
    assert r["case_id"] == "UNIDENTIFIED"
    assert all(t["final"]["stage"] is None for t in r["teeth"])
    assert r["summary"]["highest_tooth_stage"] is None
    empty = build_case_report({"case_id": "X", "teeth": []})
    assert "NO_TEETH" in {w["code"] for w in empty["case_warnings"]}


@pytest.mark.parametrize("bad", [None, [1], ["a", 2], [math.nan, 1], [1, math.inf], "1,2", [True, 20], ["10", 20]])
def test_bad_coordinates_treated_as_missing(bad):
    lm = {"mesial_cej": bad, "distal_cej": [10, 0], "mesial_bc": [0, 20], "distal_bc": [10, 20], "apex": [5, 100]}
    m = measure(lm)
    assert m["status"] == "missing"
    assert m["missing_landmarks"] == ["mesial_cej"]


# ---- review fixes (GPT review, 2026-11-20) ----------------------------------------
from week7.report import _stage_rule  # noqa: E402

BASE = {"mesial_cej": [0, 0], "distal_cej": [10, 0], "mesial_bc": [0, 20], "distal_bc": [10, 10], "apex": [5, 100]}


def _tooth(manual=None, history=None):
    t = {"tooth_id": 1, "label": "T1", "auto": {"landmarks": dict(BASE), "stage_probabilities": {"I": 0, "II": 1, "III/IV": 0}},
         "manual": manual}
    if history is not None:
        t["correction_history"] = history
    return t


@pytest.mark.parametrize("value,stage", [(14.99, "I"), (14.999, "I"), (15.0, "II"), (33.0, "II"), (33.01, "III/IV"), (33.004, "III/IV")])
def test_stage_sentence_never_contradicts_stage(value, stage):
    text = _stage_rule(value, stage)
    shown = float(text.split("%")[0] if stage != "II" else text.split("≤ ")[1].split("%")[0])
    lo, hi = 15, 33
    assert {"I": shown < lo, "II": lo <= shown <= hi, "III/IV": shown > hi}[stage], text


def test_tiny_move_added_and_removed_landmarks_are_recorded():
    man = dict(BASE, mesial_bc=[0, 20.1], apex=None)
    r = build_case_report({"case_id": "X", "teeth": [_tooth({"landmarks": man, "reviewer_id": "a", "saved_at_utc": "t", "method": "m"})]})
    m = r["teeth"][0]["manual"]
    assert m["changed_landmarks"] == ["mesial_bc"]
    assert m["removed_landmarks"] == ["apex"]
    t = _tooth({"landmarks": dict(BASE), "reviewer_id": "a", "saved_at_utc": "t", "method": "m"})
    t["auto"]["landmarks"]["apex"] = None
    r = build_case_report({"case_id": "X", "teeth": [t]})
    assert r["teeth"][0]["manual"]["added_landmarks"] == ["apex"]


def test_anonymous_correction_is_kept_but_not_reported():
    man = dict(BASE, mesial_bc=[0, 40])
    r = build_case_report({"case_id": "X", "teeth": [_tooth({"landmarks": man, "reviewer_id": "", "method": "m"})]})
    t = r["teeth"][0]
    w = {x["code"]: x for x in t["warnings"]}
    assert w["CORRECTION_PROVENANCE_MISSING"]["severity"] == "high"
    assert "reviewer_id" in w["CORRECTION_PROVENANCE_MISSING"]["message"]
    assert t["manual"]["traceable"] is False
    assert t["manual"]["measurement"]["pbl_max_pct"] == pytest.approx(40)  # kept in the record
    assert t["final"]["source"] == "auto" and t["final"]["pbl_max_pct"] == pytest.approx(20)
    ok = build_case_report({"case_id": "X", "teeth": [_tooth({"landmarks": man, "reviewer_id": "A", "saved_at_utc": "t", "method": "m"})]})
    assert ok["teeth"][0]["final"]["source"] == "manual" and ok["teeth"][0]["manual"]["traceable"] is True


def test_upload_key_uses_content_not_name_or_size():
    from week7.report import upload_key
    a = b'{"case_id": "CASE-A", "teeth": []}'
    b = b'{"case_id": "CASE-B", "teeth": []}'
    assert len(a) == len(b)
    assert upload_key(a) != upload_key(b)
    assert upload_key(a) == upload_key(bytes(a))
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "case_key = upload_key(raw)" in app and "up.size" not in app


def test_correction_history_is_kept():
    a = {"action": "save", "landmarks": dict(BASE, mesial_bc=[0, 30]), "reviewer_id": "A", "saved_at_utc": "t1", "method": "m"}
    b = {"action": "save", "landmarks": dict(BASE, mesial_bc=[0, 40]), "reviewer_id": "B", "saved_at_utc": "t2", "method": "m"}
    rm = {"action": "remove", "reviewer_id": "C", "saved_at_utc": "t3", "method": "m"}
    r = build_case_report({"case_id": "X", "teeth": [_tooth(None, [a, b, rm])]})
    h = r["teeth"][0]["correction_history"]
    assert [e["reviewer_id"] for e in h] == ["A", "B", "C"]
    assert [e["action"] for e in h] == ["save", "save", "remove"]
    assert h[0]["pbl_max_pct"] == pytest.approx(30) and h[1]["pbl_max_pct"] == pytest.approx(40)
    assert r["teeth"][0]["final"]["source"] == "auto"
    assert r["summary"]["correction_events"] == 3


def test_missing_image_file_is_warned():
    r = build_case_report({"case_id": "X", "image": {"path": "no/such/file.jpg"}, "teeth": [_tooth()]})
    assert "IMAGE_NOT_FOUND" in {w["code"] for w in r["case_warnings"]}
    ok = build_case_report(CASES[0])
    assert not {w["code"] for w in ok["case_warnings"]} & {"IMAGE_NOT_FOUND", "NO_IMAGE"}
