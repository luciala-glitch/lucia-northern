# Repeatability study

Use the app to measure the same 10 teeth twice. Select **Round 1** for the
first session, then wait a few days and repeat them as **Round 2** without
looking at the first measurements. Keep observer, image name, and tooth ID
identical so the app can pair the records.

The app writes every point, both side-specific PBL values, the worse side,
worst PBL, and stage to `measurements.csv`. Once both rounds exist, the
Repeatability section reports:

- mean and maximum absolute change in worst-side PBL percentage points;
- the number of teeth whose stage changed; and
- stage agreement percentage; and
- the average pixel shift for each of the six landmarks, including which
  landmark moved the most.

## How to complete the deliverable

1. Measure 10 teeth in **Round 1** and save every result in the app.
2. A few days later, measure the same image/tooth IDs in **Round 2** without
   viewing Round 1.
3. Tick **I've finished Round 2** in the app to reveal the comparison.
4. Download the completed CSV and replace `week2/measurements.csv` with it.
5. Replace the placeholders below with the values shown in the app.

## Results note

Status: Complete. Lucia measured the same 10 teeth in both rounds using the
same image and tooth IDs.

- Teeth paired: **10 / 10**
- Mean absolute worst-side PBL change: **3.6 percentage points**
- Maximum absolute worst-side PBL change: **11.2 percentage points**
- Mean absolute mesial PBL change: **3.3 percentage points**
- Mean absolute distal PBL change: **2.6 percentage points**
- Stage agreement: **100%** (**10 / 10** teeth)
- Teeth whose stage changed: **0**
- Teeth whose worse side changed: **3**
- Landmark with the largest average shift: **M-Tip** (**11.6 pixels**)

Observer note: The mesial root tip was the least repeatable landmark. Root
apices were harder to place consistently where the panoramic image was blurred
or overlapped by nearby anatomy.

Study limitation: Both rounds were completed on the same day rather than a few
days apart. Round 2 used the app's blind mode, but the short interval may still
allow memory of the first session to improve apparent agreement. These results
should therefore be described as a same-day workflow demonstration, not a
fully independent intra-observer repeatability estimate.
