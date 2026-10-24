"""Exercise the real legacy-report pipeline without touching saved deliverables."""

from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import pytest
from PIL import Image
from week3 import analyze


def snapshot(paths):
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for directory in paths
        for p in directory.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("custom_output", [True, False])
def test_legacy_report_end_to_end_isolated_and_numerically_verified(
    tmp_path, monkeypatch, custom_output
):
    real_root = analyze.ROOT
    before = snapshot([real_root / "reports", real_root / "exports"])
    if custom_output:
        output = tmp_path / "isolated_report"
        argv = ["analyze", "--output", str(output)]
        export_dir = output / "exports" / "synthetic"
    else:
        # Default paths are exercised too, with ROOT redirected to a sandbox.
        records = analyze.load_legacy()
        sandbox_root = tmp_path / "week3"
        monkeypatch.setattr(analyze, "ROOT", sandbox_root)
        monkeypatch.setattr(analyze, "load_legacy", lambda: records)
        output = sandbox_root / "reports"
        argv = ["analyze"]
        export_dir = sandbox_root / "exports" / "synthetic"
    monkeypatch.setattr(sys, "argv", argv)
    analyze.main()
    stats = json.loads((output / "statistics.json").read_text())
    assert stats["tooth_pairs"] == 10
    assert stats["n"] == 20
    assert stats["icc_2_1"] == pytest.approx(0.7970242466988962, abs=1e-12)
    assert stats["bias"] == pytest.approx(-1.3115348887789557, abs=1e-12)
    assert stats["difference_sd"] == pytest.approx(3.695556390852989, abs=1e-12)
    assert stats["loa_lower"] == pytest.approx(-8.554825414850814, abs=1e-12)
    assert stats["loa_upper"] == pytest.approx(5.931755637292902, abs=1e-12)
    assert stats["weighted_kappa"] is None
    assert stats["tooth_stage_quadratic_kappa"] is None
    assert stats["outside_indices"] == [2]
    for name, count in [
        ("legacy_recomputed_metrics.csv", 20),
        ("surface_agreement.csv", 20),
        ("sensitivity.csv", 600),
        ("sensitivity_summary.csv", 6),
        ("worst_cases.csv", 5),
        ("crest_edge_metrics.csv", 60),
        ("preprocessing_comparison.csv", 3),
        ("error_decomposition.csv", 5),
    ]:
        with (output / name).open() as handle:
            assert len(list(csv.DictReader(handle))) == count
    report = (output / "WEEK3_REPORT.md").read_text()
    assert "10 paired teeth / 20 surfaces" in report
    assert "Only 1 surface is outside" in report
    assert "unknown" in report and "analytic proxy" in report
    assert "undefined (all observations in one category" in report
    # Every image link resolves to a real, decodable generated plot.
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", report)
    assert len(links) == 9
    for link in links:
        with Image.open(output / link) as img:
            assert min(img.size) > 300
            img.verify()
    from week3.exports import csv_import, json_export

    examples = json.loads((export_dir / "measurements.json").read_text())
    assert len(examples) == 90
    assert csv_import((export_dir / "measurements.csv").read_text()) == examples
    assert json.loads(json_export(examples)) == examples
    assert all(r["image_id"].startswith("SYNTHETIC_") for r in examples)
    assert snapshot([real_root / "reports", real_root / "exports"]) == before


def test_legacy_without_paired_rounds_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(analyze, "load_legacy", lambda: [])
    monkeypatch.setattr(sys, "argv", ["analyze", "--output", str(tmp_path)])
    with pytest.raises(ValueError, match="No complete Round 1/2"):
        analyze.main()
    assert not list(tmp_path.iterdir())


def test_legacy_report_handles_all_rejected_perturbations_and_fewer_cases(
    tmp_path, monkeypatch
):
    records = analyze.load_legacy()
    keys = {records[0]["key"], records[1]["key"]}
    monkeypatch.setattr(
        analyze, "load_legacy", lambda: [r for r in records if r["key"] in keys]
    )

    def rejected(_):
        return [
            {
                "landmark": name,
                "direction": direction,
                "shift_px": size * sign,
                "status": "BoneCrestBoundsError",
                "mesial_change_pp": None,
                "distal_change_pp": None,
                "max_change_pp": None,
                "stage_changed": None,
            }
            for name in ("mesial.cej", "mesial.bc", "distal.cej", "distal.bc", "apex")
            for direction in ("parallel", "normal")
            for size in (2, 5, 10)
            for sign in (-1, 1)
        ]

    monkeypatch.setattr(analyze, "sensitivity", rejected)
    monkeypatch.setattr(sys, "argv", ["analyze", "--output", str(tmp_path)])
    analyze.main()
    report = (tmp_path / "WEEK3_REPORT.md").read_text()
    assert "top 2" in report and "13 additional teeth" in report
    assert "N/A | N/A" in report
    assert not (tmp_path / "case_3.png").exists()
    with (tmp_path / "sensitivity_summary.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert all(int(r["trials"]) == int(r["rejected"]) for r in rows)
    assert all(r["max_abs_pbl_change_pp"] == "" for r in rows)
