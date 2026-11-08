# Week 5: Model Refinement and Clinical Review

For Week 5, I refined the five-landmark model from Week 4 and tested where it
still fails. I kept the same radiograph-level split. I fitted all settings on
development out-of-fold predictions and used the 327-tooth external set only
for the final evaluation. I also improved the review workflow so a clinician
can see the uncertainty, correct the landmarks, and keep both the original and
corrected results.

## Headline (external test, 327 teeth, paired against Week 4)

| Metric | Week 4 | Week 5 | Paired Δ [95% CI] |
|---|---:|---:|---|
| MRE (px), external, teeth valid under both models¹ | 13.33 | **12.95** | −0.38 [−0.79, +0.01], not significant |
| MRE (px), development OOF (1,330 teeth) | 14.31 | **13.11** | **−1.20 [−1.62, −0.84]**, significant |
| ICC(2,1) PBL% / weighted κ, external | 0.939 / 0.886 | **0.948 / 0.892** | CIs include 0 |
| Weighted κ / stage accuracy, development | 0.852 / 83.2% | **0.873 / 85.5%** | both significant |
| Stage III/IV called I/II, external | 9 / 83 | **7 / 84** | |
| 95% PBL interval actually covers truth, external | 87.4% | **97.9%** (dev 95.2%) | nominal 95% |
| AUROC for detecting a wrong stage, dev | 0.60 (max σ) | **0.80** (1 − P(stage)); external 0.83 | |
| Stage accuracy among auto-accepted teeth, external | 94.3% at 25% review | **98.8% at 51% review** | safer, not cheaper |

¹ Over all landmarks of all teeth the external MRE is 13.45 → 13.02 px (per-landmark table in the
[model comparison](reports/MODEL_COMPARISON.md)). The paired test uses only teeth that both models measured validly.

The Week 5 model improved clearly on development data. The external result also
moved in the right direction, but the change was not statistically significant
and stage accuracy did not improve. The new intervals had 97.9% coverage on the
external set, close to the intended 95%. The review rule accepted fewer teeth
than Week 4, but the accepted results were more accurate. It met the accuracy
target on held-out data and narrowly missed the severe-miss target: 2/315
(0.63%) instead of 0.5%. The full results are in the
[model comparison](reports/MODEL_COMPARISON.md) and
[uncertainty report](reports/UNCERTAINTY_ANALYSIS.md).

## Deliverables

| Mentor checklist item | Where |
|---|---|
| Week 5 summary: methods, main improvements, figures, limitations and conclusion | [reports/WEEK5_REPORT.md](reports/WEEK5_REPORT.md) |
| Error analysis: three main Week 4 weaknesses, worst five, landmark-level errors, planned fixes | [reports/ERROR_ANALYSIS.md](reports/ERROR_ANALYSIS.md) |
| Refined model and configuration, compared with Week 4 on the same split (MRE per landmark, SDR@2/5/10, along/perpendicular, ICC(2,1), weighted κ) | [reports/MODEL_COMPARISON.md](reports/MODEL_COMPARISON.md), [`calibration.json`](reports/calibration.json) |
| Uncertainty calibration: confidence-vs-error plot, Monte Carlo PBL intervals, revised rejection thresholds | [reports/UNCERTAINTY_ANALYSIS.md](reports/UNCERTAINTY_ANALYSIS.md) |
| Clinical validation: stage errors, Stage III/IV false negatives, tooth-type and image-condition analysis, correction study, 12 annotated examples | [reports/CLINICAL_VALIDATION.md](reports/CLINICAL_VALIDATION.md), [clinical_examples/](reports/clinical_examples/) |
| Updated application: upload → auto-detect → review → correct → recalculate → compare → export | [App](#review-app) below |
| Expanded tests, CI and reproducibility | [reports/TESTING.md](reports/TESTING.md) |
| Machine-readable results | [`metrics.json`](reports/metrics.json), [`refined_predictions.json`](reports/refined_predictions.json), [`results/`](reports/results/) |

## What I changed

I tested each change on development data and kept it only when the cross-fitted
development MRE decreased.

| Step | Dev MRE px | Addresses |
|---|---:|---|
| Week 4 Raw (shipped) | 15.39 | — |
| + Raw/CLAHE 50/50 ensemble (beat learned per-landmark weights) | 14.83 | crest/CEJ placement variance |
| + multi-margin test-time augmentation (box margin 5/8/11%) | 14.62 | sensitivity to the reader's box |
| + **orientation self-check** (run both apex directions; switch and flag) | 14.23 | gross failures from wrong apex direction, Week 4's worst cases |
| + re-trained `strong_aug` weights (rotation ±25°, scale ±15%, gamma/blur/noise) | **13.99** | tilted and poor-quality films |

I screened six settings on development fold 1. These included two learning
rates, a coordinate-loss term, sharper heatmaps, stronger augmentation, and a
same-seed Week 4 rerun to estimate GPU variation. Stronger augmentation gave
the best result. The lower learning rate and sharper heatmaps were worse.

I also made three changes after prediction:

- **Uncertainty calibration:** I rescaled the landmark uncertainty and used
  1,000 Monte Carlo draws for the stage probabilities. I also calibrated the
  PBL interval against held-out development predictions.
- **Review rule:** The app flags a result when the automatic stage probability
  is below 0.94, the orientation check changes the direction, or no valid
  measurement is available. On held-out folds, accepted-stage accuracy was
  95.1%, while the severe-miss rate was 0.63%. On the external set, these were
  98.8% and 1.2%. The accuracy target was met, but the 0.5% severe-miss target
  was not. See the [uncertainty report](reports/UNCERTAINTY_ANALYSIS.md#revised-review-rule).
- **Review app:** I added stage probabilities, a comparison of automatic and
  corrected results, a warning near stage boundaries, and export validation.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r week5/requirements.txt        # App, tests, report generation
python -m pip install -r week4/requirements-model.txt  # + PyTorch, for live inference and --from-weights
python -m week4.download && python -m week4.denpar     # DenPAR images (141 MB) for figures and examples
```

**Weights.** The refined model uses ten checkpoints, about 53 MB each:
`week5/weights/strong_aug_{raw,clahe}_fold_{1..5}.pt`, except fold-1 Raw, which lives in
`week5/weights/screen/`. They are too large for git. Either:

- download them from the [`week5-weights` release](https://github.com/luciala-glitch/lucia-northern/releases/tag/week5-weights),
  putting `strong_aug_raw_fold_1.pt` in `week5/weights/screen/` and the other nine in `week5/weights/`; or
- re-train them with `./week5/screen.sh` and `CONFIG=strong_aug ./week5/train_all.sh` (about 3 h on an M4).
  Re-training on other hardware is not bit-identical.

`python -m week5.reproduce --from-weights` checks every checkpoint against
`week5/weights/MANIFEST.json` and the saved split hash. It stops if a file is
missing or does not match.

**Without the weights.** The reports, figures, examples, and tests use the
saved predictions in `reports/results/`. Live Week 5 inference needs the model
weights. If they are missing, the app can use the Week 4 detector or the
classical baseline.

The 15 training logs are in `week5/weights/logs/`: six screening runs and nine
additional `strong_aug` runs. Each log includes the loss for every epoch and
the run time. Inference does not print a log; its outputs are the per-tooth
prediction files in `reports/results/`.

## Reproduce

```bash
python -m week5.reproduce                 # ~3 min: saved predictions → every table, figure, example; tests; checks
python -m week5.reproduce --from-weights  # first re-run inference from the checkpoints (~40 min on an M4)
make reproduce-week5 PYTHON=.venv/bin/python
```

The full experiment, from scratch:

```bash
./week5/screen.sh                                     # six configurations on development fold 1 (~1 h)
python -m week5.experiments screen                    # score the screen; writes results/screening.json
CONFIG=<selected> ./week5/train_all.sh                # only if a configuration beat Week 4
python -m week5.experiments predict --config week4 --tta
python -m week5.reproduce
```

## Review App

```bash
python -m streamlit run week5/app.py
```

Choose **Week 5 refined Raw + CLAHE ensemble** in the sidebar. It is the default
when the checkpoints and `calibration.json` are available.

1. **Upload** a radiograph (JPG/PNG/TIFF) or pick a DenPAR image, and draw or click the tooth box. Check
   the orientation preview: crown up, mesial left.
2. **Run AI suggestion.** The five landmarks are overlaid on the original image, each with its calibrated
   uncertainty circle. The side panel shows the PBL%, the calibrated 95% interval on a stage bar, the
   Monte Carlo stage probabilities, and any review reasons (low stage support, possible missed Stage III/IV,
   orientation self-check, failed guardrails).
3. **Drag** any landmark. PBL% and stage are recalculated instantly by the Week 3 calculator. A boundary
   warning appears if the corrected PBL is within 3 pp of 15% or 33%.
4. **Compare**: a table lists the AI and corrected positions of each landmark, the AI's 95% radius, how far
   you moved it and whether that was outside the radius, plus the PBL/stage change.
5. **Export JSON/CSV** or **Save**. The bundle holds the untouched automatic record (`source: auto`) and the
   correction (`source: manual`) as separate records, with reviewer ID, timing, per-landmark movement,
   review reasons, stage probabilities and checkpoint digests. Every bundle is validated against
   [`review_bundle.schema.json`](review_bundle.schema.json) and the Week 4 measurement schema before
   it can be saved or exported.

The app is a research prototype, not a diagnostic device. As in Week 4,
practice readings are kept separate from qualified-reviewer data.

## Known limitations

- **Not a medical device.** This is a research prototype on a single dataset (DenPAR). Other sensors,
  populations and projection geometries are untested.
- **The external gain is not significant.** The MRE gain on the external test is −0.38 px, with a CI that
  touches zero, and external stage accuracy did not improve. The external set (327 teeth, 180 images) is
  too small to confirm a gain of this size.
- **More review.** The review rule refers about half of all teeth. That is the price of ≥ 95% accepted accuracy and
  few unflagged severe misses. It is not more efficient than Week 4's rule at equal burden.
- **The severe-miss target is not met on held-out data.** It was ≤ 0.5% of Stage III/IV teeth. Held-out
  development gives 0.63% (2/315) and external gives 1.2% (1/84). With so few events, one tooth moves the
  rate by 0.3 pp on development and 1.2 pp on the external test, so the target is a fitting criterion, not
  a guarantee.
- **Confident failures remain.** Some teeth are confidently wrong (see the uncertainty report), so every
  automatic result is still shown to the clinician.
- **Orientation self-check.** It switched 84 development teeth, 70 of them truly mis-oriented; 14 were false
  switches, all flagged for review.
- **Simulated correction study.** The reviewer is simulated, with noise taken from Week 3 test–retest
  readings by a non-specialist. It shows that correction resolves about 70% of flagged errors and can flip
  correct boundary cases. Real clinician speed, usability and inter-reader agreement need a reader study,
  which the App already logs data for.
- **Tooth type.** Tooth type is approximated by multi-rooted/single-rooted and anterior/posterior; DenPAR
  has no complete FDI numbering.

## Files

| File | Role |
|---|---|
| `train.py`, `screen.sh`, `train_all.sh` | Configurable re-training (Week 4 loop plus augmentation, learning rate, loss and target options) |
| `experiments.py` | Fold-1 screen, test-time augmentation, both-orientation inference |
| `refinement.py` | The refined detector used by the App: ensemble, TTA, orientation self-check, calibration, review hook |
| `uncertainty.py` | Monte Carlo stage probabilities, the review policy, the split-conformal PBL interval |
| `evaluate.py`, `report.py`, `stats.py` | Cross-fitted evaluation, paired radiograph-clustered bootstrap, figures, examples, reports |
| `review.py`, `review_bundle.schema.json` | Export validation and the AI-vs-corrected comparison |
| `reproduce.py` | One-command reproduction with prerequisite, checksum and output checks |
