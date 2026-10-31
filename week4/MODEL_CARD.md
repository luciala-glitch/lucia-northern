# Model card: PBL five-landmark heatmap detector

**Research prototype, not a diagnostic device.** Do not use it to diagnose,
stage, or rule out periodontitis. A qualified clinician must review every
output.

## Intended use and model

The model accepts an intraoral periapical radiograph, a reader-drawn tooth box,
and the tooth orientation. It suggests five landmarks: mesial/distal CEJ,
mesial/distal bone crest, and apex. The Week 3 engine converts them to long-axis
PBL%, a 95% interval, and a Stage I / II / III–IV suggestion; the review app
requires correction and confirmation. Intended users are researchers and
dental students studying measurement workflows, not patients or unsupervised
clinical users.

An ImageNet-pretrained ResNet-18 encoder and five-channel heatmap decoder operate
on an orientation-normalized 160 × 320 tooth crop. Coordinates use soft-argmax;
uncertainty combines heatmap spread and disagreement among five fold models.
Training details and reproduction steps are in the [README](README.md).

## Data

Training and validation use DenPAR v3 (CC BY 4.0): 1,330 teeth from 727
radiographs in five radiograph-level folds. External testing uses 327 teeth from
180 DenPAR test images. Ground truth is DenPAR's single official annotation.
Patient IDs are unavailable, so patient-level leakage between folds cannot be
excluded. The data represent one population, annotating team, and device set;
restorations and crowns are not labelled. See the [dataset report](reports/DATASET.md).

## Performance

Development results are out-of-fold mean ± SD; external confidence intervals
resample whole radiographs.

| Metric | Development | External test |
| --- | ---: | ---: |
| Landmark MRE | 15.4 ± 1.6 px (3.7% root) | 13.5 px (3.3%) |
| PBLmax ICC(2,1) | 0.905 ± 0.016 | 0.939 (0.903–0.964) |
| Weighted stage κ | 0.851 ± 0.024 | 0.886 |
| Stage accuracy | 0.831 ± 0.029 | 0.865 |
| III/IV called lower | 39/309 (12.6%) | 9/83 (10.8%) |

External subgroup results (MRE / stage accuracy): multi-rooted teeth 12.1 px /
0.836, tilted teeth 16.4 px / 0.810, and low-contrast teeth 11.5 px / 0.900.

## Limitations and failure modes

Incorrect orientation is the largest observed failure: rotated images produced
extreme errors. Tilted teeth also perform worse. Predictions systematically
under-call disease (external: 34 lower-stage versus 10 higher-stage errors), the
clinically dangerous direction. Heavy image noise degrades accuracy. Uncertainty
ranks difficult cases but is over-confident: nominal 95% PBL intervals covered
the manual value only 80% in development and 87% externally. Performance on
obscured CEJs is unknown. Full subgroup results and confidence intervals are in
the [failure and robustness report](reports/FAILURE_ROBUSTNESS.md).

## Required before clinical use

- External multi-centre, multi-device validation with patient-level separation.
- Multi-rater consensus labels, including restorations, crowns, overlap, and
  other clinically difficult findings.
- Calibrated uncertainty and a prospectively validated rejection rule.
- Reliable automatic orientation checks and severe-disease subgroup safety
  analysis.
- A prospective reader study of time, correction, and automation bias.
- Regulatory review and post-deployment monitoring.
