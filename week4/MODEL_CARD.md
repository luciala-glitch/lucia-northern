# Model card: PBL five-landmark heatmap detector

**Research prototype, not a diagnostic device.** It must not be used to
diagnose, stage, or rule out periodontitis. Every output needs review by a
qualified clinician.

## Intended use

Given an intraoral periapical radiograph, a reader-drawn tooth box, and the
reader's answers to "apex up or down?" and "mesial left or right?", the model
suggests the mesial/distal CEJ, mesial/distal bone crest, and apex. The Week 3
engine turns these into long-axis PBL% and a Stage I / II / III–IV suggestion,
with a 95% interval. The App then asks a person to check and correct the
landmarks. Intended users are researchers and dental students studying
measurement workflows. It is not intended for patients, triage, or unsupervised
use.

## Model and training

ImageNet-pretrained ResNet-18 encoder and a 5-channel heatmap decoder. Input is
a 160 × 320 crop of the tooth box (8% margin), flipped so the apex is at the
bottom and mesial is on the left. Vertical flips never swap labels; horizontal
flips are applied only together with the reader's mesial answer. Coordinates
come from a soft-argmax over a spatial softmax, and uncertainty is the
heatmap's spatial SD, combined with the spread between the five fold models.
Training: 30 epochs, AdamW with one-cycle LR, cross-entropy to Gaussian targets,
seed 20261027. Augmentation: rotation ±15°, scale ±8%, brightness/contrast
±15%, random CLAHE (p = 0.35), no horizontal flips.

## Training data and its limits

DenPAR v3 (CC BY 4.0), 1,330 teeth from 727 radiographs, in 5 radiograph-level
folds. Ground truth is DenPAR's **single** official annotation, associated to
teeth by `week4/denpar.py` ([details](reports/DATASET.md)). Limits:

- One annotating team, one population, one set of imaging devices. No patient
  IDs, so patient-level leakage between folds cannot be ruled out.
- No repeat reading, so annotation noise is not measured on these data.
- No restoration or crown labels, so performance on obscured CEJs is unknown.
- Mesial/distal naming is approximate for anterior images (stage is unaffected).

## Performance

Development = out-of-fold mean ± SD over 5 folds. External = DenPAR Testing
(327 teeth, 180 images), averaging the five fold models. CI = 95% interval from
resampling whole radiographs.

| Metric | Development (OOF) | External test | My own R1 vs R2 (15 teeth, RAW) |
| --- | --- | --- | --- |
| MRE, all landmarks | 15.4 ± 1.6 px (3.7% of root) | 13.5 px (3.3%) | inter-round distance 6.6 px (4.5% of root) |
| Along-axis MAE | 12.6 ± 1.4 px | 11.1 px | — |
| ICC(2,1), PBLmax | 0.905 ± 0.016 | 0.939 (0.903–0.964) | 0.689 |
| Weighted κ, stage | 0.851 ± 0.024 | 0.886 | 0.444 |
| Bias (pred − manual) | −1.23 ± 0.37 pp | −1.77 pp | +0.32 pp |
| 95% LoA width | 31.8 ± 4.4 pp | 25.1 pp (19.1–31.3) | 21.2 pp |
| Stage accuracy | 0.831 ± 0.029 | 0.865 | — |
| III/IV called lower | 39 / 309 (12.6%) | 9 / 83 (10.8%) | — |
| Anatomically invalid output | 2.0% | 0.6% | — |

The comparison with my own readings is indirect: those 15 teeth are on a
different (panoramic) image with no Stage I teeth, and their LoA rest on only
15 pairs.

**By subgroup** (external test, n teeth / images; see the
[failure report](reports/FAILURE_ROBUSTNESS.md) for CIs):

| Subgroup | n | MRE px | Stage accuracy |
| --- | --- | ---: | ---: |
| All | 327 / 180 | 13.5 | 0.865 |
| Multi-rooted (≥2 apices) | 122 / 97 | 12.1 | 0.836 |
| Tilted >15° | 85 / 62 | 16.4 | 0.810 |
| Low contrast (bottom quartile) | 80 / 50 | 11.5 | 0.900 |
| Orientation metadata wrong (>45°) | 5 / 2 | 60.0 (n too small; development: 84 teeth, 37.7 px, accuracy 0.72) | — |
| Obscured CEJ (restoration/crown) | not estimable — no labels | | |

## Known failure modes

1. **Wrong orientation input.** Three of the 5 worst development predictions
   (MRE 180–350 px) are on radiographs stored rotated 90°. "Apex up/down" cannot
   describe that, so the crop is wrong. Across the 84 development teeth whose
   arch label contradicts the visible orientation, MRE is 37.7 px against 13.9
   px otherwise. The App shows the detector's crown-up/mesial-left view so the
   reader can catch this.
   The other two worst cases were partially visible teeth with diffuse heatmaps.
   All five had a maximum landmark σ ≥ 148 px, against a median of 11 px.
2. **Systematic under-calling.** Errors lean toward a lower stage (34 lower vs
   10 higher on the external test). The predicted crest sits about 2 px coronal
   to DenPAR's, on average. Under-calling III/IV is the clinically dangerous
   direction.
3. **Tilted teeth** (>15°) have 20–40% higher MRE (external 16.4 vs 13.5 px; development 21.1 vs 15.4 px).
4. **Heavy noise**: at σ = 20 gray levels, MRE doubles and ICC falls to 0.71. Blur
   and halved resolution have little effect, because the crop is downsampled to
   160 × 320 anyway.
5. **Uncertainty is informative but over-confident.** Spearman ρ between
   landmark σ and error is 0.39–0.42, but the nominal 95% PBL interval contains
   the manual value only 80% (development) and 87% (external) of the time. It
   should be read as a ranking, not a calibrated probability.

## Before any clinical use, at least

- Multi-centre, multi-device periapical data with **patient IDs** and external
  validation at sites not seen in training.
- **Multi-rater consensus** ground truth, with measured inter-rater agreement,
  and labelled restorations, crowns, furcations, and overlap.
- Calibrated intervals (for example conformal), and a rejection rule validated
  prospectively.
- Automatic orientation detection, or a hard check, for rotated or flipped
  images.
- A severe-disease safety analysis with enough III/IV cases per subgroup to give
  tight intervals.
- A prospective reader study: time, correction rate, automation bias with and
  without the AI suggestion.
- Regulatory review as software as a medical device, plus post-deployment
  monitoring.
