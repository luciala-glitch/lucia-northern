"""Exported PDF / CSV / JSON agree with the in-app report and with each other."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import jsonschema
import pytest
from pypdf import PdfReader

from week7.build_reports import FIXED_TIME, OUT, export_case
from week7.cases import build_demo_cases
from week7.edge_cases import build_edge_cases
from week7.export import CSV_DIGITS, to_csv, to_json
from week7.report import build_case_report

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "case_report.schema.json").read_text())
CASES = build_demo_cases()
ALL = CASES + build_edge_cases()
IDS = [str(c["case_id"]) for c in ALL]


def _num(text):
    return None if text == "" else float(text)


@pytest.mark.parametrize("case", ALL, ids=IDS)
def test_csv_matches_report(case):
    report = build_case_report(case)
    rows = list(csv.DictReader(io.StringIO(to_csv(report))))
    assert len(rows) == len(report["teeth"])
    for row, t in zip(rows, report["teeth"]):
        f = t["final"]
        assert row["reported_source"] == f["source"]
        assert row["reported_stage"] == (f["stage"] or "")
        exp = None if f["pbl_max_pct"] is None else round(f["pbl_max_pct"], CSV_DIGITS)
        assert _num(row["reported_pbl_max_pct"]) == exp
        for side in ("mesial", "distal"):
            exp = None if not f[side] else round(f[side]["pbl_pct"], CSV_DIGITS)
            assert _num(row[f"reported_{side}_pbl_pct"]) == exp
        if t["auto"] and t["auto"]["measurement"]["pbl_max_pct"] is not None:
            assert _num(row["auto_pbl_max_pct"]) == round(t["auto"]["measurement"]["pbl_max_pct"], CSV_DIGITS)
        if t["manual"]:
            assert row["manual_reviewer_id"] == (t["manual"]["reviewer_id"] or "")
            assert row["manual_changed_landmarks"].split(";") == (t["manual"]["changed_landmarks"] or [""])
        assert row["warning_codes"] == ";".join(w["code"] for w in t["warnings"])


@pytest.mark.parametrize("case", ALL, ids=IDS)
def test_json_is_complete_and_valid(case):
    report = build_case_report(case, generated_at=FIXED_TIME)
    payload = json.loads(to_json(report, case))
    jsonschema.validate(payload, SCHEMA)
    assert payload["input_case"] == json.loads(json.dumps(case))
    payload.pop("input_case")
    assert payload == json.loads(json.dumps(report))


@pytest.mark.parametrize("case", CASES[:12], ids=IDS[:12])
def test_pdf_contains_reported_values(case, tmp_path):
    report = export_case(case, tmp_path)
    folder = tmp_path / report["case_id"]
    text = " ".join(p.extract_text() for p in PdfReader(folder / f"{report['case_id']}.pdf").pages)
    text = " ".join(text.split())
    assert report["case_id"] in text
    assert "not an independent clinical diagnosis" in text
    for t in report["teeth"]:
        f = t["final"]
        assert f"{f['pbl_max_pct']:.1f}%" in text
        assert f"{t['auto']['measurement']['pbl_max_pct']:.1f}%" in text
        if t["manual"]:
            assert "SIMULATED" in text
    for suffix in (".csv", ".json", "_annotated.png"):
        assert (folder / f"{report['case_id']}{suffix}").is_file()


@pytest.mark.parametrize("case", CASES, ids=IDS[: len(CASES)])
def test_committed_exports_are_current(case):
    """The files in week7/reports/cases were produced by this code from these inputs."""
    report = build_case_report(case, generated_at=FIXED_TIME)
    folder = OUT / "cases" / report["case_id"]
    assert (folder / f"{report['case_id']}.csv").read_text(encoding="utf-8") == to_csv(report)
    saved = json.loads((folder / f"{report['case_id']}.json").read_text(encoding="utf-8"))
    assert saved == json.loads(to_json(report, case))


@pytest.mark.parametrize("case_id,slug", [("DENPAR-TEST-5", "DENPAR-TEST-5"), ('a/b:c*?"<>|', "a_b_c"), ("...", "case"), (None, "None")])
def test_safe_slug(case_id, slug):
    from week7.export import safe_slug
    assert safe_slug(case_id) == slug


def test_odd_case_id_exports(tmp_path):
    case = dict(build_edge_cases()[0], case_id='CASE:01/<x>')
    report = export_case(case, tmp_path)
    folder = tmp_path / "CASE_01_x"
    assert report["case_id"] == 'CASE:01/<x>'
    assert (folder / "CASE_01_x.pdf").is_file() and (folder / "CASE_01_x.csv").is_file()


def test_csv_lists_full_correction_history():
    case = build_demo_cases()[0]
    tooth = case["teeth"][0]
    auto = tooth["auto"]["landmarks"]
    tooth["correction_history"] = [
        {"action": "save", "landmarks": auto, "reviewer_id": "B", "saved_at_utc": "t1", "method": "m"},
        {"action": "remove", "reviewer_id": "C", "saved_at_utc": "t2", "method": "m"},
    ]
    tooth["manual"] = None
    row = next(csv.DictReader(io.StringIO(to_csv(build_case_report(case)))))
    assert row["correction_events"] == "2"
    assert row["correction_history"].startswith("save by B at t1 -> ")
    assert row["correction_history"].endswith("remove by C at t2")
