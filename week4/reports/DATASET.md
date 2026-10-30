# Dataset, ground truth and leakage-safe split

## Sources

| Source | Use | Teeth | Images | Ground truth |
| --- | --- | ---: | ---: | --- |
| My Week 3 study (`kaggle_dental_xray_1.jpg`) | Human repeatability reference only | 15 | 1 | Mean of my two rounds; inter-round distance kept as noise |
| DenPAR v3 Training + Validation | 5-fold development (train / out-of-fold test) | 1,330 | 727 | Official DenPAR annotation (single reading) |
| DenPAR v3 Testing | External test; never trained on or used to tune anything | 327 | 180 | Official DenPAR annotation (single reading) |

**DenPAR**: *Annotated Intra-Oral Periapical Radiographs Dataset for Machine
Learning*, v3, Rasnayaka et al., 2025. Dataset DOI
[10.5281/zenodo.16645076](https://doi.org/10.5281/zenodo.16645076); article DOI
[10.1038/s41597-025-05906-9](https://doi.org/10.1038/s41597-025-05906-9).
License **CC BY 4.0**, which permits this research use with attribution. The
141 MB archive is downloaded and checked against a fixed SHA-256 by
`python -m week4.download`; it is not committed. The 40 images in
`week4/demo_denpar/` are unmodified copies kept for the App.

My own readings stay out of training because 15 teeth on one panoramic image
cannot form five independent groups, and because panoramic and periapical
images differ in scale and appearance.

## From DenPAR annotations to five landmarks

DenPAR stores CEJ and apex points per radiograph, alveolar crest as polylines,
and one mask per tooth. `week4/denpar.py` builds one five-landmark record per
tooth:

1. Each CEJ and apex point is assigned to the tooth whose **mask** lies within 15 px
   of it (bounding boxes overlap, masks do not).
2. A tooth needs at least two CEJs (the outermost pair across the tooth is used)
   and at least one apex. With several apices (multi-rooted), the apex is their
   mean and the tooth is tagged `multirooted`.
3. The bone crest on each side is the most coronal crest-polyline point within
   10 px of that side of the mask and between the CEJ and apex levels. Crests drawn
   up to 25 px coronal to the CEJ (111 teeth) are moved to the CEJ level, which
   means 0% bone loss on that side.
4. Mesial direction comes from DenPAR's arch/site sheet (labial view: patient-right
   teeth have mesial on the image right). For anterior images, the midline is
   estimated from the visible FDI teeth (210 teeth), or from the image centre when
   the counts do not match (182 teeth). **This is approximate**, but PBLmax and
   stage take the worse side and do not depend on which side is called mesial.
5. Every record is passed through the Week 3 `calculate_tooth_pbl`. Any record it
   rejects is excluded.

Of 4,402 tooth masks, **1,657 teeth were kept**. Exclusions are counted, not
hidden:

| Reason | Teeth |
| --- | ---: |
| Fewer than two CEJs (mostly teeth cut off at the film edge) | 2,119 |
| No crest touching the left / right side | 221 / 174 |
| Crest outside the CEJ–apex range, left / right | 51 / 23 |
| No apex visible | 156 |
| Mask missing from the release (image 803) | 1 |

A random sample of 12 kept teeth was overlaid and checked visually before any
model was trained. The stage mix is 763 I / 495 II / 399 III/IV.

**Limits of this ground truth.** It is one annotation by the dataset authors,
not a mean of two independent readings, so it carries an unknown amount of
annotation noise. My Week 3 inter-round differences are the only repeatability
estimate. In 89 teeth (5%) the arch label disagrees with the visible tooth
orientation by more than 45°. These teeth are kept and reported as a failure
subgroup.

## Split

- **Unit: radiograph.** DenPAR publishes no patient IDs, so teeth from the same
  image always stay together. Different images of the same patient could still
  fall in different folds. That residual leakage risk cannot be checked with
  this dataset.
- `week4/denpar_split.py` calls `make_group_folds` (seed `20261027`) on the 727
  development radiographs. `validate_split` checks that no radiograph is in both
  train and test, and that each one is tested exactly once. Fold test sizes:
  275 / 263 / 269 / 261 / 262 teeth.
- The split is saved at [`week4/data/denpar_split_5fold.json`](../data/denpar_split_5fold.json)
  together with the SHA-256 of the dataset it was built from. The tooth dataset is
  [`week4/data/denpar_landmarks.json`](../data/denpar_landmarks.json) (COCO-style
  keypoints plus per-tooth tags).
- Every development metric is **out-of-fold**: fold *k*'s model, and the
  baseline's mean shape for fold *k*, are fitted only on the other four folds.
  External-test metrics average the five fold models. The external set was used
  only after all settings were fixed.
- One exception, stated openly: the classical baseline's three search settings
  were chosen by a small grid search on all development teeth, not inside each
  fold. That makes its development numbers slightly optimistic. Its
  external-test numbers are unaffected.
