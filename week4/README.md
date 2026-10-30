# Week 4: landmark detection with rejection, not blind automation

A pretrained heatmap detector predicts five landmarks per tooth (mesial/distal
CEJ, mesial/distal bone crest, apex) and feeds them to the Week 3
`pbl_calculator.py`. It is compared with a classical baseline on DenPAR
(1,657 teeth, CC BY 4.0) using radiograph-level 5-fold cross-validation and an
untouched external test set. My own Week 3 two-round readings are the human
reference.

| Report | What it answers |
| --- | --- |
| [Dataset & split](reports/DATASET.md) | Source, license, ground-truth construction, exclusions, saved split |
| [Detector comparison](reports/DETECTOR_COMPARISON.md) | MRE, SDR@2/5/10 px, along-axis vs perpendicular error, baseline vs learned |
| [Downstream agreement](reports/DOWNSTREAM_AGREEMENT.md) | ICC(2,1), weighted κ, Bland–Altman, stage confusion, comparison with my own repeatability |
| [Uncertainty & rejection](reports/UNCERTAINTY_REJECTION.md) | Uncertainty–error correlation, PBL intervals, risk–coverage, rejection rule |
| [Failure & robustness](reports/FAILURE_ROBUSTNESS.md) | 5 worst cases, subgroups, degradation curves, Raw vs CLAHE |
| [Model card](MODEL_CARD.md) | Intended use, limits, what clinical use would require |

**Headline (external test, 327 teeth):** PBL ICC 0.94, stage κ 0.89, LoA
−14.3 to +10.8 pp, against −10.3 to +10.9 pp for my own round-to-round
readings. Errors lean toward under-calling the stage. The rejection rule keeps
the cases that are far from a stage boundary.

## Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r week4/requirements.txt          # App, tests, CI
python -m pip install -r week4/requirements-model.txt    # + torch 2.8.0 / torchvision 0.23.0
```

Tested with Python 3.13 on an Apple M4 (MPS). CUDA and CPU also work. All
seeds are fixed (`week4/constants.py`, seed 20261027).

## Weights

The ten checkpoints (`raw_fold_{1..5}.pt`, `clahe_fold_{1..5}.pt`, 53 MB each)
are not stored in git. Either:

- download them from the repository's **Releases** page (tag `week4-weights`)
  into `week4/weights/` and verify them with
  `python -m week4.weights_manifest --check --strict`, or
- retrain them with `PYTHON=python ./week4/train_all.sh` (about 2 h on an M4).
  Retraining on other hardware is not bit-identical. The manifest check reports
  differences instead of failing.

## Reproduce

```bash
make reproduce PYTHON=python
```

This downloads and verifies DenPAR, rebuilds `data/denpar_landmarks.json` and
the saved split, trains only the checkpoints that are missing, runs
`python -m week4.benchmark` (all tables and figures in `reports/results/`, about
25 min), and runs the tests. With the released weights in place, nothing is
retrained.

## App: auto-detect → review → correct → export

```bash
python -m streamlit run week4/app.py
```

The sidebar first asks **who is reading**. The two modes never share data.

**Practice / calibration (default, not ground truth).** For readers without
dental training, and for learning the five landmarks:

- Only Development images, and only the 40 of 90 tooth boxes with a complete
  five-point DenPAR reference, are offered. Boxes without one (e.g. 10.jpg box 1,
  whose distal crest is not annotated) are hidden and named in the sidebar.
- Place all five points blind, then **Submit & show expert reference**. The read
  locks, white rings show the reference, and the app reports per-landmark
  distance (px) and your PBL/stage against the reference PBL/stage.
- Every attempt is appended to the git-ignored `week4/data/practice.json`, tagged
  `"purpose": "practice"`, `"not_ground_truth": true`. Nothing is written to
  `corrections.json`. No AI suggestion, External test or R1/R2 here.
- The reference is the single official DenPAR annotation assigned to each tooth
  by `week4/denpar.py` (crest = most coronal point of the official crest line on
  each side): a teaching reference, not a second expert.

**Qualified dental reviewer.** Requires a Reviewer ID and is the only mode that
can open External test, run the AI suggestion and save to `corrections.json`.
Expert references are never shown in this mode.

1. Choose a DenPAR demo radiograph (prefer **External test**: the learned models
   saw the development images in training) or upload your own. Pick the tooth on
   the image: **Select tooth on image**, then click inside a numbered DenPAR
   tooth; on an upload, click two opposite corners around the whole tooth
   (**Add another tooth on image** for more).
2. Check the orientation. Defaults come from DenPAR's arch/site sheet; on
   anterior films the mesial side flips across the midline per tooth box. A
   thumbnail shows exactly what the detector will see (crown up, mesial left).
3. Optional: turn on **Blind first read** to place your own landmarks before the
   AI suggestion is revealed.
4. Press **Run AI suggestion** (all actions sit under the image). Dashed circles show 1-SD landmark uncertainty. A stage bar
   shows the PBL estimate, its 95% interval, and the 15%/33% boundaries.
5. Drag any landmark to correct it. A flagged tooth needs all five landmarks
   confirmed before export; saving also needs a Reviewer ID, and the disabled
   Save button says which is missing.
6. Export JSON/CSV or save locally. Each export holds the untouched prediction
   (`"source": "auto"`), the corrected result (`"source": "manual"`), both with
   `uncertainty.landmark_px` and `uncertainty.pbl_ci95`, plus an audit block:
   detector and checkpoint hashes, pixels moved per landmark, time since the
   suggestion, the blind read if any, the rejection reasons, and
   `annotator_role`/`reviewer_id`. Local saves go to the git-ignored
   `week4/data/corrections.json` (one slot per reviewer, image, tooth, condition
   and round), which can later become training data.

## Code map

| File | Role |
| --- | --- |
| `denpar.py` | Official DenPAR annotations → five-landmark teeth (mask-based association) |
| `denpar_split.py`, `split.py`, `dataset.py` | Radiograph-level folds and leakage checks; Week 3 round consolidation |
| `predict.py` | Validated inference, typed errors, classical baseline, schema-valid records |
| `training.py`, `model.py`, `train.py`, `train_all.sh` | Canonical crop, augmentation, ResNet-18 heatmap model, training |
| `learned.py` | Checkpoint ensemble inference with heatmap-spread uncertainty |
| `uncertainty.py` | 1,000-draw Monte Carlo PBL interval and the review rule |
| `benchmark.py` | Every metric, table and figure |
| `download.py`, `weights_manifest.py`, `reproduce.py` | Data download and checksums, weight digests, readiness summary |
