# Repeatability study

Lucia measured the same 10 teeth twice, keeping observer, image name, and tooth
ID identical so the app could pair the records. The app recorded all six
landmarks, both side-specific PBL values, the worse side, worst PBL, and stage.

The **Intra-reader agreement** section reports:

- mean and maximum absolute change in worst-side PBL percentage points;
- mean signed difference (Round 2 minus Round 1), difference standard
  deviation, and exploratory 95% limits of agreement;
- within-reader repeatability coefficient (`2.77 × within-subject SD`);
- the number of teeth whose stage changed and stage agreement percentage; and
- the average pixel shift for each of the six landmarks, including which
  landmark moved the most.

## Results note

Status: Complete. Both rounds contain the same 10 image and tooth IDs.

- Teeth paired: **10 / 10**
- Mean absolute worst-side PBL change: **3.6 percentage points**
- Maximum absolute worst-side PBL change: **11.2 percentage points**
- Mean absolute mesial PBL change: **3.3 percentage points**
- Mean absolute distal PBL change: **2.6 percentage points**
- Mean signed worst-side PBL change (Round 2 − Round 1): **−1.0 percentage point**
- Standard deviation of signed differences: **4.8 percentage points**
- Exploratory 95% limits of agreement: **−10.5 to +8.4 percentage points**
- Within-subject standard deviation: **3.3 percentage points**
- Repeatability coefficient: **9.2 percentage points**
- Stage agreement: **100%** (**10 / 10** teeth)
- Teeth whose stage changed: **0**
- Teeth whose worse side changed: **3**
- Landmark with the largest average shift: **M-Tip** (**11.6 pixels**)

Observer note: The mesial root tip was the least repeatable landmark. Root
apices were harder to place consistently where the panoramic image was blurred
or overlapped by nearby anatomy.

Study limitation: Both rounds were completed on the same day (16 October,
local time). Round 2 began about 3 minutes after Round 1 ended, and 9 of the 10
teeth were re-measured 12–34 minutes after their first reading. During Round 2
the app hid all Round 1 records, but the current tooth's calculated PBL was
still shown. Memory of the first session may therefore have improved apparent
agreement. These results should be described as a same-day workflow
demonstration, not a fully independent intra-observer repeatability estimate.

All 10 sampled teeth were classified as Stage III/IV in both rounds, with
worst-side PBL values from 38.3% to 60.0%. Therefore, 100% stage agreement in
this small convenience sample does not show how well the reader would agree
for teeth close to a staging boundary. The limits of agreement and
repeatability coefficient are exploratory because there are only 10 paired,
same-day measurements.

The source images are panoramic radiographs. Blur, anatomical overlap, and
geometric distortion can reduce landmark precision compared with dedicated
intraoral/periapical imaging, so these results should not be treated as a
clinical validation study.

The final CSV timestamp is after midnight in UTC but still October 16 in the
local America/Indiana/Indianapolis time zone.

## Future workflow option

For a clearly single-rooted tooth, an optional shared-apex mode could collect
one root-tip point for both surfaces (five clicks total). The submitted app
keeps separate mesial and distal root-tip points because the assignment asks
for three points on both surfaces and that workflow also supports multi-rooted
teeth.
