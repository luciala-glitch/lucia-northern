# Testing and reproducibility

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull request. It lints `week3`–`week5`,
type-checks the PBL calculator, and runs the Week 3, Week 4 and Week 5 suites. Week 5 has its own coverage
gate: ≥ 90% branch coverage of `week5.uncertainty`, `week5.refinement`, `week5.review` and `week5.stats`
(currently 99%). CI needs no model weights or DenPAR images. A weight-free fake of the Raw/CLAHE checkpoint
ensemble (`week5/tests/fakes.py`) drives the real refined pipeline and the real Streamlit App end to end.

## What the Week 5 tests prove

| Requirement | Test |
|---|---|
| Missing file, corrupted bytes, truncated PNG, image too small | `test_workflow.py::test_bad_images_fail_before_inference`, `::test_truncated_png_is_reported_as_corrupted` (the detector is never called) |
| Invalid landmarks: missing, NaN, outside the image, anatomically impossible | `test_workflow.py::test_failed_or_invalid_detector_output_is_rejected`, `::test_anatomically_impossible_prediction_is_rejected` |
| Failed prediction: missing checkpoint, missing or corrupt calibration | `test_workflow.py::test_refined_detector_reports_missing_weights`, `::test_corrupted_or_missing_calibration_is_not_ready` |
| Every output follows the standard JSON schema | `test_workflow.py::test_refined_prediction_carries_stage_probabilities_and_valid_schema` (measurement schema), `::test_bundle_schema_rejects_overwritten_or_mismatched_records` (review-bundle schema) |
| Manual corrections never overwrite the automatic prediction | `test_workflow.py::test_correction_recalculates_immediately_and_never_touches_the_original` (frozen record, deep-compared before and after; re-save replaces only the same reviewer's slot); the schema forces `source: auto` for the original and `source: manual` for the correction |
| Correction recalculates PBL% and stage immediately | same test (Stage I → III/IV), `test_app_refined.py::test_refined_workflow_from_suggestion_to_saved_correction` (through the real App) |
| Full auto-detect → review → correct → recalculate → save in the App | `test_app_refined.py` (refined detector selected, stage probabilities shown, comparison table, corrected stage, validated bundle with 10 checkpoint digests) |
| Boundary warning after a correction | `test_app_refined.py::test_boundary_warning_after_a_correction_near_15_percent` |
| Orientation self-check | `test_workflow.py::test_orientation_self_check_switches_and_always_flags` |
| Monte Carlo interval identical to Week 4; stage probabilities; invalid inputs | `test_uncertainty.py` |
| Split-conformal PBL interval reaches 95% coverage | `test_uncertainty.py::test_conformal_factor_reaches_the_requested_coverage` |
| σ scaling reaches nominal coverage; TTA variance; AUROC; paired bootstrap finds real effects and not null ones | `test_evaluate.py` |
| Review-policy fitting meets both clinical targets with the least review | `test_evaluate.py::test_fit_policy_meets_targets_with_least_review` |
| Correction simulator is exact without noise and leaves accepted teeth alone | `test_evaluate.py::test_correction_simulation_is_exact_without_reader_noise_and_leaves_accepted_teeth_alone` |
| External labels never used; every tooth scored; ladder rule obeyed; ≥ 10 examples of each kind; report links resolve | `test_outputs.py` |
| Reproduction stops on missing prerequisites | `test_outputs.py::test_reproduce_refuses_to_run_without_prerequisites` |

Week 4's suite (`week4/tests`) still covers decoding, schema export, the classical baseline, data loading,
split integrity and the original App. It runs unchanged, so the Week 5 changes to `week4/app.py` and
`week4/predict.py` are regression-tested there.

## Commands

```bash
source .venv/bin/activate
python -m ruff check week5 week4 week3/pbl_calculator.py
python -m pytest -q week3/tests week4/tests week5/tests
python -m week5.reproduce                  # saved predictions → every report, figure and example
python -m week5.reproduce --from-weights   # re-run inference from the checkpoints first
```

`week5.reproduce` stops if any input is missing: the Week 4 split and landmarks, the DenPAR images,
the screen, or the per-tooth predictions. It then regenerates calibration, metrics, figures, the 12
examples and the four reports, runs the Week 5 tests, and checks that
external labels were never fitted, that all 1,330 development and 327 external teeth were scored, and
that every example figure exists. With `--from-weights` it first checks every checkpoint against
`week5/weights/MANIFEST.json` and against the split hash stored inside the checkpoint.
