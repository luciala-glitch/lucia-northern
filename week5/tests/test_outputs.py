"""The committed Week 5 deliverables are complete, consistent and leakage-free."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from week4.constants import LANDMARK_NAMES
from week5 import reproduce

ROOT = Path(__file__).parents[1]
REPORTS = ROOT / "reports"


def load(name: str):
    return json.loads((REPORTS / name).read_text())


def test_all_required_reports_and_figures_exist_and_link_correctly():
    for name in (
        "ERROR_ANALYSIS.md", "MODEL_COMPARISON.md", "UNCERTAINTY_ANALYSIS.md", "CLINICAL_VALIDATION.md", "TESTING.md",
        "confidence_vs_error.png", "risk_coverage.png", "model_comparison.png", "metrics.json", "calibration.json",
        "clinical_examples/overview.png",
    ):
        assert (REPORTS / name).is_file(), name
    for report in REPORTS.glob("*.md"):
        for target in re.findall(r"\]\(([^)#]+)\)", report.read_text()):
            if not target.startswith("http"):
                assert (report.parent / target).exists(), f"{report.name} links to missing {target}"


def test_at_least_ten_examples_of_every_kind():
    manifest = load("clinical_examples/manifest.json")
    assert len(manifest) >= 10
    assert {case["kind"] for case in manifest} == {"successful", "corrected", "challenging"}
    for case in manifest:
        assert (REPORTS / "clinical_examples" / case["figure"]).is_file()
        if case["kind"] == "successful":
            assert case["auto_stage"] == case["truth_stage"] and not case["flagged"]
        if case["kind"] == "corrected":
            assert case["flagged"] and case["auto_stage"] != case["truth_stage"]
            assert case["stage_after_simulated_review"] == case["truth_stage"]


def test_external_labels_were_not_used_and_every_tooth_is_scored():
    metrics, calibration = load("metrics.json"), load("calibration.json")
    assert metrics["protocol"]["external_labels_used_for_fitting"] is False
    assert calibration["external_labels_used"] is False
    assert metrics["refined_external"]["downstream"]["n_total"] == 327
    assert metrics["refined_development_oof"]["downstream"]["n_total"] == 1330
    assert len(calibration["fold_parameters"]) == 5
    assert {f["held_out_fold"] for f in calibration["fold_parameters"]} == {1, 2, 3, 4, 5}


def test_calibration_is_complete_for_the_app():
    calibration = load("calibration.json")
    assert set(calibration["blend_raw_weight"]) == set(LANDMARK_NAMES)
    assert all(0.25 <= v <= 4 for v in calibration["sigma_scale"].values())
    assert len(calibration["model"]["raw_checkpoints"]) == len(calibration["model"]["clahe_checkpoints"]) == 5
    assert calibration["model"]["tta_margins"]
    policy = calibration["review_policy"]
    assert 0.5 <= policy["min_stage_probability"] < 1


def test_mentor_metrics_are_reported_for_both_models_and_both_sets():
    metrics = load("metrics.json")
    for key in ("week4_raw_external", "refined_external", "week4_raw_development_oof", "refined_development_oof"):
        landmarks = metrics[key]["landmarks"]
        for name in (*LANDMARK_NAMES, "all"):
            for field in ("mre_px", "sdr_2px", "sdr_5px", "sdr_10px", "along_mae_px", "perpendicular_mae_px"):
                assert field in landmarks[name]
        assert {"icc_2_1", "weighted_kappa"} <= set(metrics[key]["downstream"])
    paired = metrics["paired_comparison_refined_minus_week4"]["external"]
    for field in ("mre_px", "sdr_2px", "sdr_5px", "sdr_10px", "along_mae_px", "icc_2_1", "weighted_kappa"):
        low, high = paired[field]["ci95"]
        assert low <= paired[field]["delta"] <= high


def test_ladder_only_keeps_steps_that_improved_development():
    ladder = load("metrics.json")["ladder"]
    best = ladder[0]["dev_mre_px"]
    for step in ladder[1:]:
        assert step["accepted"] == (step["dev_mre_px"] < best)
        if step["accepted"]:
            best = step["dev_mre_px"]


def test_reproduce_refuses_to_run_without_prerequisites(monkeypatch, tmp_path):
    monkeypatch.setattr(reproduce, "REQUIRED_INPUTS", (tmp_path / "absent.json",))
    with pytest.raises(SystemExit, match="absent.json"):
        reproduce.main(["--skip-tests"])


def test_weight_check_refuses_a_manifest_that_omits_a_checkpoint(monkeypatch, tmp_path):
    calibration = load("calibration.json")
    manifest = dict(json.loads(reproduce.MANIFEST.read_text()))
    dropped = calibration["model"]["clahe_checkpoints"][0]
    del manifest[dropped]
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "calibration.json").write_text(json.dumps(calibration))
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(reproduce, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(reproduce, "MANIFEST", tmp_path / "MANIFEST.json")
    with pytest.raises(SystemExit, match="no digest for " + re.escape(dropped)):
        reproduce.check_weights()


def test_review_rule_report_separates_in_sample_from_held_out_targets():
    from week5.report import uncertainty_report

    metrics = load("metrics.json")
    text = uncertainty_report(metrics)
    assert "≥ **none**" not in text
    assert ("P(Stage III/IV) ≥" in text) == (metrics["uncertainty"]["policy"]["severe_guard"] is not None)
    assert "targets met:" not in text
    assert "held-out folds (cross-fitted)" in text
    held_out = metrics["uncertainty"]["policy"]["target_check"]["development_cross_fitted"]
    if not held_out["accepted_severe_miss_rate_met"]:
        assert "**not met**" in text

    policy = dict(metrics["uncertainty"]["policy"], severe_guard=0.05)
    guarded = uncertainty_report({**metrics, "uncertainty": {**metrics["uncertainty"], "policy": policy}})
    assert "P(Stage III/IV) ≥ **5%**" in guarded
