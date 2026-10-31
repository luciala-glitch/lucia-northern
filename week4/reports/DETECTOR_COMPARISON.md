# Detector comparison: classical baseline vs learned heatmap model

All development numbers are **out-of-fold mean ± SD across the 5
radiograph-level folds** (1,330 teeth, 727 radiographs). Each fold model, and the
baseline's mean shape for that fold, was fitted without the radiographs it is
scored on. Errors are in original image pixels. Along-axis and perpendicular
components use the **manual** long axis *u* (CEJ midpoint → apex). The SDR
thresholds of 2, 5 and 10 px match the Week 3 perturbation study.

**Detectors**

- *Classical baseline* (`predict.ClassicalLandmarkDetector`): the tooth box is
  turned into the canonical crop. CEJs and apex are placed at the training-fold
  mean shape. Each bone crest is the strongest apical dark→bright gradient in the
  interproximal column just outside the root, weighted by a Gaussian prior around
  the mean crest height.
- *Learned*: ImageNet-pretrained ResNet-18 plus a heatmap decoder with 5
  channels, soft-argmax decoding. Augmentation: rotation ±15°, scale ±8%,
  brightness/contrast, random CLAHE. **No horizontal flip**: the canonical crop
  puts mesial on the left using the reader's mesial answer, so labels are never
  silently swapped. Separate models were trained on Raw and on CLAHE inputs.

## Per landmark (development, 5-fold OOF)

| Detector | Landmark | MRE px | SDR@2 | SDR@5 | SDR@10 | Along-axis MAE px | Perpendicular MAE px | MRE % root |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Classical gradient baseline | mesial_cej | 48.1 ± 4.2 | 0.003 ± 0.003 | 0.016 ± 0.009 | 0.075 ± 0.020 | 42.5 ± 3.9 | 16.0 ± 1.1 | 11.6 ± 1.2 |
| Classical gradient baseline | distal_cej | 45.9 ± 5.1 | 0.002 ± 0.002 | 0.016 ± 0.007 | 0.068 ± 0.020 | 39.3 ± 5.4 | 16.7 ± 1.0 | 11.1 ± 1.4 |
| Classical gradient baseline | mesial_bc | 56.0 ± 3.1 | 0.001 ± 0.002 | 0.018 ± 0.004 | 0.081 ± 0.013 | 48.1 ± 3.2 | 19.3 ± 1.0 | 13.5 ± 0.8 |
| Classical gradient baseline | distal_bc | 60.5 ± 4.8 | 0.003 ± 0.003 | 0.015 ± 0.007 | 0.062 ± 0.019 | 51.3 ± 4.3 | 21.6 ± 1.0 | 14.7 ± 1.2 |
| Classical gradient baseline | apex | 105.6 ± 15.3 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.001 ± 0.002 | 81.2 ± 14.8 | 52.4 ± 1.5 | 25.8 ± 4.2 |
| Classical gradient baseline | all | 63.2 ± 4.4 | 0.002 ± 0.002 | 0.013 ± 0.004 | 0.057 ± 0.009 | 52.5 ± 4.3 | 25.2 ± 0.8 | 15.3 ± 1.3 |
| Learned heatmap (Raw) | mesial_cej | 13.1 ± 1.2 | 0.051 ± 0.015 | 0.227 ± 0.026 | 0.537 ± 0.018 | 11.8 ± 0.9 | 3.8 ± 0.7 | 3.2 ± 0.3 |
| Learned heatmap (Raw) | distal_cej | 12.4 ± 0.9 | 0.048 ± 0.012 | 0.234 ± 0.029 | 0.554 ± 0.025 | 10.8 ± 0.4 | 4.3 ± 0.7 | 3.0 ± 0.2 |
| Learned heatmap (Raw) | mesial_bc | 17.1 ± 2.6 | 0.050 ± 0.012 | 0.256 ± 0.022 | 0.597 ± 0.023 | 14.8 ± 2.3 | 5.5 ± 0.8 | 4.2 ± 0.6 |
| Learned heatmap (Raw) | distal_bc | 17.2 ± 1.8 | 0.045 ± 0.017 | 0.239 ± 0.029 | 0.587 ± 0.022 | 14.9 ± 1.7 | 5.6 ± 0.5 | 4.2 ± 0.4 |
| Learned heatmap (Raw) | apex | 17.2 ± 2.5 | 0.049 ± 0.015 | 0.202 ± 0.028 | 0.500 ± 0.029 | 10.9 ± 2.4 | 10.6 ± 1.1 | 4.2 ± 0.6 |
| Learned heatmap (Raw) | all | 15.4 ± 1.6 | 0.049 ± 0.005 | 0.232 ± 0.012 | 0.555 ± 0.015 | 12.6 ± 1.4 | 6.0 ± 0.6 | 3.7 ± 0.4 |
| Learned heatmap (CLAHE) | mesial_cej | 13.2 ± 1.3 | 0.041 ± 0.022 | 0.219 ± 0.022 | 0.526 ± 0.022 | 12.0 ± 1.2 | 3.8 ± 0.6 | 3.2 ± 0.3 |
| Learned heatmap (CLAHE) | distal_cej | 12.5 ± 0.9 | 0.040 ± 0.015 | 0.236 ± 0.038 | 0.541 ± 0.022 | 11.0 ± 0.6 | 4.2 ± 0.5 | 3.0 ± 0.2 |
| Learned heatmap (CLAHE) | mesial_bc | 16.8 ± 1.9 | 0.060 ± 0.009 | 0.256 ± 0.020 | 0.574 ± 0.014 | 14.5 ± 1.7 | 5.4 ± 0.6 | 4.1 ± 0.4 |
| Learned heatmap (CLAHE) | distal_bc | 16.6 ± 1.4 | 0.043 ± 0.012 | 0.232 ± 0.032 | 0.578 ± 0.036 | 14.3 ± 1.5 | 5.5 ± 0.3 | 4.0 ± 0.3 |
| Learned heatmap (CLAHE) | apex | 17.4 ± 1.9 | 0.038 ± 0.018 | 0.198 ± 0.033 | 0.494 ± 0.031 | 11.6 ± 1.9 | 10.2 ± 0.7 | 4.3 ± 0.5 |
| Learned heatmap (CLAHE) | all | 15.3 ± 1.4 | 0.045 ± 0.010 | 0.228 ± 0.012 | 0.542 ± 0.007 | 12.7 ± 1.2 | 5.8 ± 0.4 | 3.7 ± 0.3 |

## External test (DenPAR Testing: 327 teeth, 180 radiographs; mean of 5 fold models)

| Detector | MRE px | SDR@2 | SDR@5 | SDR@10 | Along-axis MAE px | Perpendicular MAE px | MRE % root |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Classical baseline | 56.9 | 0.001 | 0.013 | 0.054 | 45.6 | 26.0 | 13.7 |
| Learned (Raw) | 13.5 | 0.049 | 0.265 | 0.590 | 11.1 | 5.2 | 3.3 |
| Learned (CLAHE) | 13.4 | 0.051 | 0.253 | 0.592 | 11.1 | 5.1 | 3.3 |

## Reading the numbers

- **The learned model is about 4× more accurate than the baseline** (development
  MRE 15.4 ± 1.6 vs 63.2 ± 4.4 px). Across folds, the SD of the learned model
  (1.6 px) is far smaller than the gap between the two detectors. The baseline is
  only a little better than placing the mean shape. Without the gradient search,
  crest along-axis error on development is 59 px; with it, 46 px.
- **Along-axis error dominates, for both detectors.** For the learned model the
  along-axis MAE is 12.6 px and the perpendicular MAE 6.0 px; for the crests,
  14.8–14.9 vs 5.5–5.6 px. In the Week 3 sensitivity study (2,700 trials), a 10 px
  shift along the axis changed PBLmax by 2.83 pp on average (up to 9.1 pp), and the
  same shift perpendicular by 0.19 pp (up to 1.6 pp). So the error that matters is also the
  largest one. The apex is the only landmark with similar along and perpendicular
  error (10.9 vs 10.6 px), because its lateral position is ill-defined on rounded
  or multi-rooted apices.
- **SDR is low in absolute terms.** Only 23% of learned landmarks fall within 5 px,
  and 56% within 10 px. These periapicals have a median size of 1,168 × 886 px,
  with a median root length of 411 px. In relative terms, MRE is 3.7% of root length.
- **Comparison with my own repeatability.** In Week 3 my two readings of the same
  landmark were on average 6.6 px apart on a panoramic image (4.5% of root
  length). With independent errors, that corresponds to about 4.7 px (3.2%) of
  error per reading. The model's 3.7% of root against DenPAR is the same order as
  one human reading, but the images, scale and reference differ. This is context,
  not an equivalence claim.
- **Raw vs CLAHE input makes no measurable difference to landmark error**
  (15.4 ± 1.6 vs 15.3 ± 1.4 px). See the [failure report](FAILURE_ROBUSTNESS.md#raw-vs-clahe)
  for the systematic crest shift CLAHE introduces.

Reproduce: `python -m week4.benchmark`. Full numbers are in
[`results/metrics.json`](results/metrics.json) under
`detector_development_mean_sd_across_folds` and `landmarks_external`.
