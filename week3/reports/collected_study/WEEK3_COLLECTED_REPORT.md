# Week 3: Repeatability and Image Contrast in the PBL Calculator

## Introduction

For Week 3, I continued working on the PBL calculator from Week 2. I wanted to see how much my measurements changed when I marked the same teeth again, and whether Raw, global histogram equalization (HE) or CLAHE affected landmark placement. I also added checks for invalid geometry and a way to export the measurements.

I measured the same 15 teeth on one panoramic image in two rounds under all three conditions. This gave 90 tooth readings and 180 surface observations. The [JSON](exports/measurements.json) and [CSV](exports/measurements.csv) contain the same readings, with no missing or duplicate tooth/condition/round combinations.

## Methods

### Measurements and reading order

Each reading used a mesial CEJ, mesial bone crest, distal CEJ, distal bone crest and one shared anatomical apex. Coordinates stayed in the original 2041 × 1024 image grid. Global HE used `equalizeHist`; CLAHE used a clip limit of 2.0 and an 8 × 8 tile grid. I interpreted the assignment's “tile grid = 88” as 8 × 8.

I restarted RAW Round 1 after I had placed mesial and distal on the wrong image side for eight teeth: T4–T7 and T12–T15, on the image-left side of the dental midline. The [earlier readings](protocol_history/excluded_raw_round1.json) were archived and excluded from the analysis. The [history record](protocol_history/history_evidence.json) preserves the reason and timing evidence.

The analyzed rounds were about 13 hours apart on 23 October 2026. Round 1 was bounded by study creation at 04:26 UTC and the completed backup at 04:49 UTC; Round 2 saves ran from 17:47 to 18:00 UTC. Both rounds followed Raw → HE → CLAHE. The second round took about 13 minutes from first to last save. Its tooth order matched the program's shuffled order; the first-round tooth order could not be verified.

### Calculation

The unit axis runs from the midpoint of the two CEJs toward the apex:

```text
m = (CEJ_mesial + CEJ_distal) / 2
u = (apex − m) / ||apex − m||
d_k = (BC_k − CEJ_k) · u
L_k = (apex − CEJ_k) · u
PBL_k = 100 × |d_k| / |L_k|
PBL_max = max(PBL_mesial, PBL_distal)
```

The engine checks `L_k > 0` and `0 ≤ d_k ≤ L_k` before taking absolute values. Undefined axes, invalid coordinates and out-of-range crests raise specific errors. Collinear points are allowed when the axis and projected lengths remain valid. The worse side determines the assignment stage: I below 15%, II from 15% to 33% inclusive, and III/IV above 33%.

I compared rounds with ICC(2,1), quadratic weighted kappa and Bland–Altman plots. Differences are Round 2 minus Round 1, in percentage points (pp). The LoA are mean bias ± 1.96 × sample SD (`ddof=1`). Kappa uses the ordered classes I, II and III/IV with disagreement weights `(i−j)²/4`.

## Results

### Agreement between rounds

Each condition contains 15 paired teeth, or 30 paired surfaces.

| Condition | Surface ICC(2,1) | Surface weighted κ | Tooth weighted κ | Bias (pp) | 95% LoA (pp) |
| --- | --- | --- | --- | --- | --- |
| RAW | 0.722 | 0.563 | 0.444 | -0.261 | -10.761 to 10.238 |
| HE | 0.786 | 0.816 | 0.865 | -0.627 | -11.510 to 10.256 |
| CLAHE | 0.825 | 0.718 | 0.609 | +0.199 | -10.996 to 11.395 |

CLAHE had the highest observed ICC, while HE had the highest stage kappa. The mean differences were small, but the limits of agreement were still roughly ±11 pp. This means that the average change alone did not describe how much individual readings could differ.

![Raw Bland–Altman](raw/bland_altman.png)

![HE Bland–Altman](he/bland_altman.png)

![CLAHE Bland–Altman](clahe/bland_altman.png)

I also compared whole-tooth PBLmax and resampled whole teeth 10,000 times (seed 20261023), keeping both surfaces and rounds together. The last column below is the clustered interval for the **surface ICC**, not the tooth PBLmax ICC.

| Condition | PBLmax ICC | Tooth bias (pp) | Tooth 95% LoA (pp) | Clustered surface ICC 95% interval |
| --- | --- | --- | --- | --- |
| RAW | 0.689 | +0.323 | -10.255 to 10.900 | 0.489 to 0.819 |
| HE | 0.742 | -1.353 | -12.078 to 9.373 | 0.595 to 0.882 |
| CLAHE | 0.792 | +1.065 | -10.753 to 12.884 | 0.640 to 0.878 |

Tooth-level plots: [Raw](raw/tooth_bland_altman.png), [HE](he/tooth_bland_altman.png), [CLAHE](clahe/tooth_bland_altman.png). Full results are in [supplementary_statistics.json](supplementary_statistics.json).

### Stage agreement

No tooth was Stage I in either round, so the observed tooth comparisons only distinguished II and III/IV. The table shows Round 1 → Round 2 counts; the [full three-class matrices](tooth_stage_confusion.csv) include the zero Stage I cells.

| Condition | II → II | II → III/IV | III/IV → II | III/IV → III/IV | Disagreements / 15 |
| --- | --- | --- | --- | --- | --- |
| RAW | 7 | 2 | 2 | 4 | 4 |
| HE | 8 | 0 | 1 | 6 | 1 |
| CLAHE | 5 | 0 | 3 | 7 | 3 |

The differences between conditions involved only a few teeth. Eleven of the 180 surface observations, covering eight distinct tooth surfaces, were within 1 pp of a stage boundary. Small changes near 15% or 33% could therefore change a category. The engine's furcation/vertical-defect review flag was raised for 42/90 readings above 33%.

### Landmark placement across conditions

| Condition | Coordinate RMSD vs Raw (px) | Round-to-round RMSD (px) | Coordinate variance (px²) |
| --- | --- | --- | --- |
| RAW | Reference | 8.154 | 33.240 |
| HE | 7.462 | 7.019 | 24.633 |
| CLAHE | 7.972 | 7.722 | 29.813 |

There were 30 complete tooth/round groups with all three conditions. Coordinate RMSD is `sqrt(mean(dx²+dy²))` across the five landmarks. With two rounds, the reported coordinate variance equals RMSD²/2, so those two columns describe the same variation. HE had the lowest observed round-to-round displacement.

I separated landmark displacement into its mean drift and centered residual. The full CSV files also contain parallel and normal components.

| Condition | Landmark | Mean drift (px) | Centered residual RMS (px) |
| --- | --- | --- | --- |
| RAW | mesial.cej | 2.121 | 5.862 |
| RAW | mesial.bc | 1.365 | 5.053 |
| RAW | distal.cej | 0.483 | 6.285 |
| RAW | distal.bc | 3.049 | 7.135 |
| RAW | apex | 3.541 | 12.396 |
| HE | mesial.cej | 0.890 | 8.013 |
| HE | mesial.bc | 1.489 | 7.270 |
| HE | distal.cej | 1.417 | 5.898 |
| HE | distal.bc | 0.992 | 5.593 |
| HE | apex | 1.271 | 7.456 |
| CLAHE | mesial.cej | 1.440 | 6.511 |
| CLAHE | mesial.bc | 1.954 | 7.775 |
| CLAHE | distal.cej | 0.911 | 5.030 |
| CLAHE | distal.bc | 2.401 | 6.545 |
| CLAHE | apex | 5.594 | 9.131 |

The apex had the largest RMS displacement in Raw and CLAHE, while the mesial CEJ had the largest in HE. The CLAHE apex moved an average of about 5.5 px parallel to the axis toward the root, which was worth reviewing even though the overall PBL bias was small.

### Sensitivity to point placement

I moved one landmark at a time by ±2, ±5 or ±10 px, parallel or normal to the starting axis, and recalculated the axis and both percentages. The 45 Round 1 geometries produced 2,700 simulated trials, kept separate from the saved readings. Invalid placements would be recorded as rejected trials.

| Shift (px) | Direction | Mean absolute ΔPBLmax (pp) | Maximum absolute ΔPBLmax (pp) | Rejected / trials |
| --- | --- | --- | --- | --- |
| 2 | parallel | 0.571 | 1.826 | 0 / 450 |
| 2 | normal | 0.036 | 0.268 | 0 / 450 |
| 5 | parallel | 1.425 | 4.566 | 0 / 450 |
| 5 | normal | 0.091 | 0.716 | 0 / 450 |
| 10 | parallel | 2.834 | 9.132 | 0 / 450 |
| 10 | normal | 0.187 | 1.580 | 0 / 450 |

### Five cases with the largest differences

I ranked each tooth by its largest absolute bias-centered surface difference across conditions. The five figures below show the responsible condition, both rounds' PBL values, the saved axis and crest projections. Cyan is Round 1, orange is Round 2, and arrows show the observed displacement.

Only four surface differences were outside their condition-specific LoA: RAW T7 / distal (-12.59 pp); RAW T9 / distal (-12.37 pp); HE T7 / mesial (+10.71 pp); CLAHE T14 / mesial (+13.96 pp). The five ranked teeth are therefore review cases, not five claimed outliers.

The combined table shows the maximum absolute change in PBLmax, in pp, across five one-landmark **parallel** trials at each signed shift. All 200 case-level ±5/±10 px trials, including normal shifts and both surface changes, remain in [case_sensitivity.csv](case_sensitivity.csv).

| Tooth | Condition | −10 px | −5 px | +5 px | +10 px |
| --- | --- | --- | --- | --- | --- |
| T14 | CLAHE | 4.581 | 3.854 | 3.854 | 7.708 |
| T7 | RAW | 6.908 | 3.454 | 3.454 | 6.908 |
| T9 | RAW | 8.108 | 4.054 | 4.054 | 8.108 |
| T11 | CLAHE | 6.827 | 4.293 | 4.293 | 8.586 |
| T15 | HE | 5.165 | 3.994 | 4.566 | 9.132 |

![T14 CLAHE](case_1.png)

![T7 RAW](case_2.png)

![T9 RAW](case_3.png)

![T11 CLAHE](case_4.png)

![T15 HE](case_5.png)

T7's ranked figure uses Raw. Its HE mesial reading was also outside LoA, so I included [that condition's overlay](he_t7_flag.png) separately.

### Image gradients near the bone crest

I kept the Raw Round 1 crest locations fixed across transforms and sampled ±10 px perpendicular to the line joining the two crests. This line was an approximate tangent. I also checked the restricted ±3 px region because the strongest gradient could be away from the selected crest.

| Condition | Mean full-window peak (gray/px) | Mean ±3 px peak (gray/px) | Full peak at ≥8 px / 30 |
| --- | --- | --- | --- |
| RAW | 4.225 | 3.526 | 6 |
| HE | 6.962 | 5.796 | 6 |
| CLAHE | 7.674 | 6.489 | 6 |

HE and CLAHE stretched the grayscale range, so a larger unnormalized gradient was expected and could include noise. I used this as a contrast comparison, rather than evidence of a more accurately located bone boundary.

![Fixed-location crest profile](crest_profile.png)

### Radiographic examples

The [image appendix](radiographic_cases/RADIOGRAPHIC_CASES.md) shows a restoration affecting CEJ identification (Week 2 img10-T3), an upper molar with partly superimposed root outlines (current T9), and an angulated tooth (current T7). The vectors use saved coordinates. The restoration example retains its older six-point format and is outside the main statistics.

I also used separate synthetic examples to show the effects of a shifted CEJ, a different apex selection and lateral displacement in a tilted tooth. In the first example, mesial PBL changes even though the worse-side maximum stays the same.

![Synthetic geometry examples](synthetic_failure_cases.png)

## Discussion and Limitations

The tooth-cluster bootstrap intervals for mean surface bias included zero in all conditions, so I did not find clear evidence of an overall directional PBL shift in this sample. Mean landmark drift was smaller than the centered residual variation. This suggests that much of the change varied from tooth to tooth, but it does not establish that the error was purely random; the CLAHE apex drift still needed attention.

This was a small study with one reader and one image. The earlier RAW attempt, short interval and fixed condition order could introduce practice or recall effects, so the condition differences cannot be attributed to enhancement alone. The two surfaces also share a tooth and apex. No acceptable difference was set in advance, and expert reference landmarks were unavailable. The image-case labels are visual interpretations. These results are not clinical validation.

The optional crown point enables a warning for root-to-crown ratios below 1.0 or above 2.5, but it is not saved in the required five-landmark export. These records therefore cannot verify a measured root-to-crown ratio. Future work could use more images and readers, a planned interval and rotated condition order, with expert review of difficult landmarks.

## Software and Reproduction

The checks dated 2026-10-23 passed 142 Week 3 Python tests, 217 project Python tests and 14 frontend tests. The PBL engine covered 28/28 branches (100%).

Saved evidence: [Week 3 tests](week3_test_results.txt), [project tests](project_test_results.txt), [frontend tests](frontend_test_results.txt) and [coverage](full_coverage.json). Setup and report-generation commands are in the [Week 3 README](../../README.md).

## Conclusion

I completed the two-round, three-condition measurements and used them to examine agreement, landmark displacement and sensitivity to small placement changes. CLAHE had the highest observed ICC, while HE had the highest stage agreement and lowest coordinate variation. Individual differences remained larger than the small mean bias suggested. The study helped identify areas for improving the measurement process, but did not establish which enhancement was most accurate or provide clinical validation.

GitHub and the current PR: [my submission links](SUBMISSION.md).

## References

- [ICC definitions](https://pingouin-stats.org/generated/pingouin.intraclass_corr.html)
- [Quadratic weighted kappa](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html)
- [OpenCV histogram equalization and CLAHE](https://docs.opencv.org/4.13.0/d5/daf/tutorial_py_histogram_equalization.html)
- [Sample image attribution](../../../week2/sample_xrays/README.md)
- [Week 3 assignment](ASSIGNMENT_REQUIREMENTS.txt)
