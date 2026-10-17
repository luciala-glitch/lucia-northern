# Repeatability study

I measured the same 10 teeth twice, keeping reader, image name, and tooth ID
identical so the app could pair the records. The app recorded all six
landmarks, both side-specific PBL values, the worse side, worst PBL, and stage.

## Summary

Across 10 paired teeth, worst-side PBL changed by a mean of 3.6 percentage
points (bias −1.0 percentage point, indicating little average directional
difference in this sample), and all teeth kept the same stage. CEJ landmarks
were the most stable at about 7 pixels; root apices were less stable, with
M-Tip showing the largest average shift at 11.6 pixels. Because the repeat was
same-day, these results should be treated as a workflow demonstration rather
than a final repeatability estimate.

## Results

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

The bias, limits of agreement, and repeatability coefficient follow
[Bland and Altman's measurement-error guidance](https://www.bmj.com/content/312/7047/1654).

Observer note: The mesial root tip was the least repeatable landmark. Root
apices were harder to place consistently where the panoramic image was blurred
or overlapped by nearby anatomy.

## Limitations

- **Same-day repeat:** Round 2 began about 3 minutes after Round 1; 9 of the 10
  teeth were re-read 12–34 minutes later. Round 1 records were hidden, but the
  current PBL was visible, so memory may have improved apparent agreement. This
  is a same-day workflow demonstration, not a fully independent
  intra-observer repeatability estimate.
- **No near-boundary teeth:** All teeth were Stage III/IV, with worst-side PBL
  values from 38.3% to 60.0%, so 100% stage agreement does not test boundary
  cases.
- **Small sample:** The limits of agreement and repeatability coefficient are
  exploratory (`n = 10`).
- **Panoramic images:** Blur, anatomical overlap, and geometric distortion can
  limit landmark precision compared with dedicated intraoral/periapical
  imaging. This is not a clinical validation study.
- **Timestamp:** The final CSV timestamp is October 17 in UTC but October 16 in
  the local America/Indiana/Indianapolis time zone.

## What I changed as a result

- Round 2 now starts in blind mode automatically and hides the current result.
- Re-saved readings are appended as versions instead of overwriting earlier
  records.
- New rows record the CLAHE state and app version.
- Next step: repeat Round 2 several days later using the new blind mode.

An optional shared-apex mode for confirmed single-rooted teeth remains a future
workflow idea; the submitted app retains the assignment's six-point workflow.
