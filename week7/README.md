# Week 7: Clinical Reporting

In Weeks 4 and 5 I built and refined the landmark model. This week I did not
change the model. Instead, I turned its measurements into case reports that a
dentist can review. For each radiograph, the report shows the image with the
landmarks, the mesial and distal PBL of each tooth, the stage, how the stage was
calculated, and any warnings. It also keeps the AI result and any manual
correction side by side, so every change can be traced. Each case can be
exported as a PDF, a CSV and a JSON file.

This is still a research prototype. The reports are meant to support review by a
dental professional. They are not a diagnosis.

## Results

| | Result |
|---|---|
| Demo cases | 19 DenPAR test radiographs, 36 teeth (8 Stage I, 15 Stage II, 13 Stage III/IV as reported) |
| Edge cases | 4 broken inputs: missing apex, one missing crest, invalid correction, no case ID or image |
| Flagged by the Week 5 review rule | 17 of 36 teeth |
| AI stage = DenPAR reference | 28 / 36 |
| Reported stage = DenPAR reference | 34 / 36 (after simulated corrections, so this number is optimistic) |
| Automated tests | 203 passed |

The App, PDF, CSV and JSON show the same numbers for every tooth. The tests
check this, and I also recalculated three teeth by hand from their coordinates.

## Deliverables

| Mentor checklist item | Where |
|---|---|
| Clinical PBL reporting module | [`report.py`](report.py), [`app.py`](app.py) |
| Tooth-level measurement summaries | tooth table in the App and every PDF and CSV |
| Annotated radiograph | [`figures.py`](figures.py), e.g. [DENPAR-TEST-68](reports/cases/DENPAR-TEST-68/DENPAR-TEST-68_annotated.png) |
| Stage interpretation and warnings | the explanation and [warnings](#warnings) for each tooth |
| PDF, CSV and JSON export | [`export.py`](export.py), [`case_report.schema.json`](case_report.schema.json) |
| AI vs manually corrected tracking | `auto`, `manual`, `correction_history` and `final.source` for every tooth |
| Testing on at least 10 cases | [`reports/cases/`](reports/cases/) (19 cases), [`reports/edge_cases/`](reports/edge_cases/), [TESTING.md](TESTING.md) |
| Documentation | this README, [TESTING.md](TESTING.md) |
| Demonstration | [DEMO.md](DEMO.md) |

## What I built

**1. The report.** `report.py` takes a case (an image and its teeth) and builds
one report dictionary. For each tooth it:

- calculates mesial and distal PBL with the Week 3 calculator, so the numbers
  match earlier weeks;
- takes the stage from the worse surface: below 15% is Stage I, 15–33% is
  Stage II, above 33% is Stage III/IV;
- writes a short explanation. For DENPAR-TEST-68 T4 it says: "Distal: CEJ-to-crest
  175.2 px ÷ CEJ-to-apex 501.4 px = 35.0%. The stage uses the worse surface
  (distal): 35.0% > 33% → Stage III/IV";
- adds warnings, for example when the value is within 3 pp of a stage boundary.

**2. AI vs correction.** Each tooth keeps the AI record (`auto`) and the
correction (`manual`) separately. The report uses the correction only if it is
valid and signed by a reviewer. Every save and removal is added to
`correction_history` with the reviewer and the time. Nothing is overwritten.

**3. Figures.** The PDF and App show the original radiograph next to an annotated
copy. The box colour and line style show the stage. The label shows the PBL and
whether the value comes from the AI or a correction. The tooth with the highest
PBL is marked with ▲. In the App, selecting a tooth also shows a close-up of
that tooth.

**4. Exports.** The PDF has the summary, the figure, the tooth table, and the
explanation and warnings for each tooth. The CSV has one row per tooth with the
reported, AI and corrected values. The JSON has the full report plus the
original input.

**5. App.** The App puts everything together. You choose a case, select a tooth,
and the close-up, values, warnings, history and the editor all follow that tooth.
The editor heading shows which tooth you are editing ("Edit landmarks · T4").

## Demo cases

The demo cases are all 19 DenPAR test radiographs in
`week4/demo_denpar/external_test/` that have a saved Week 5 prediction. DenPAR has
no patient IDs, so each case is one radiograph. Tooth labels are DenPAR's tooth
numbers in each image, not FDI numbers.

**The corrections in the demo cases are simulated.** I do not have corrections
from a clinician. For each of the 17 flagged teeth, I moved the two landmarks
with the largest AI uncertainty to the DenPAR reference points. This was the best
strategy in my Week 5 correction study. Every export labels these corrections as
`SIMULATED`. Real corrections are entered in the App.

Two cases show the limits of the system:

- **DENPAR-TEST-100, T1.** The AI reported 43.5% (Stage III/IV) with 99% stage
  support, so it was not flagged. The reference is 13.6% (Stage I). The report
  cannot catch a confident error like this. This is why the output is only for
  review.
- **DENPAR-TEST-22, T2.** The correction moved the PBL from 12.1% to 14.9%. It is
  still Stage I, but only 0.1 pp from the boundary, and the reference is Stage II.
  The report shows a boundary warning for this tooth.

## Problems I found and fixed

I tested the App by hand and had the code reviewed. These problems came up:

| Problem | Fix |
|---|---|
| After editing one case and switching to another, saving could write the old case's points into the new case | Each case and tooth now has its own form. I added a test that repeats this exact case |
| A second correction replaced the first one, so the first was lost | Added `correction_history`. Every save and removal is kept |
| Missing values were shown as 0.0%, and a missing point was saved as (0, 0) | Missing values show "not measurable", and empty fields stay empty |
| The case with no case ID crashed the App | The App now uses the report's tooth labels. All 4 edge cases open in the App |
| Near a boundary, rounding gave sentences like "15.0% < 15%" | The explanation adds decimals when needed ("14.99% < 15%") |
| Two uploaded files with the same name and size were treated as the same case | Uploads are now identified by their content |
| A correction with no reviewer was still used as the reported value | It is kept in the record but not used, and a high warning is shown |
| It was easy to read one tooth and edit another | One "Selected tooth" now controls the close-up, values, history and editor |

## Warnings

| Code | Level | When |
|---|---|---|
| `MISSING_LANDMARKS` | high | a point needed for the long axis is missing; no PBL |
| `SINGLE_SURFACE_ONLY` | high | one crest is missing; no stage, only "at least Stage X" |
| `INVALID_GEOMETRY` | high | the calculator rejected the points, e.g. crest above the CEJ |
| `CORRECTION_INVALID` | high | the correction cannot be measured; nothing is reported |
| `CORRECTION_PROVENANCE_MISSING` | high | the correction has no reviewer, time or method; it is not used |
| `FLAGGED_NOT_REVIEWED` | high | flagged by the Week 5 rule but not corrected yet |
| `LOW_STAGE_SUPPORT` | medium | the AI stage has less than 94% support (Week 5 rule) |
| `NEAR_STAGE_BOUNDARY` | medium | the reported PBL is within 3 pp of 15% or 33% |
| `ORIENTATION_SWITCHED` | medium | the orientation check reversed the apex direction |
| `STAGE_CHANGED_BY_CORRECTION` | medium | the AI stage and corrected stage are different |
| `INTERVAL_SPANS_BOUNDARY` | info | the AI 95% interval crosses 15% or 33% |
| `WIDE_INTERVAL` | info | the AI 95% interval is wider than 20 pp |
| `CORRECTION_OUTSIDE_AI_95` | info | a point was moved outside the AI 95% circle |
| `CORRECTION_ADDED_OR_REMOVED` | info | the correction added or removed a point |
| `MANUAL_NO_MODEL_UNCERTAINTY` | info | corrected values have no model interval |
| `MISSING_CASE_ID`, `NO_IMAGE`, `IMAGE_NOT_FOUND`, `NO_TEETH`, `DUPLICATE_TOOTH_ID` | case | incomplete case data |

At first `INTERVAL_SPANS_BOUNDARY` was a medium warning, but it appeared on 27 of
36 teeth and hid the more useful warnings. I changed it to info.

Exactly 33% counts as Stage II, the same as my Week 3 calculator.

## Report structure

```
case report
├── case_id, generated_at_utc, report_version, image, source
├── method         PBL definition, stage rule, warning thresholds
├── disclaimer
├── summary        teeth, stage counts, highest stage and PBL, flagged,
│                  corrected, reported from corrections
├── case_warnings
└── teeth[]
    ├── tooth_id, label, arch, site, bbox
    ├── auto        AI points, uncertainty, 95% interval, stage probabilities
    ├── manual      current correction: points, reviewer, time, method,
    │               moved / added / removed points (or null)
    ├── correction_history[]   every save and removal, in order
    ├── final       where the reported values come from (manual / auto / none)
    ├── review_flagged, review_reasons
    ├── interpretation
    └── warnings[]  code, level, message
```

To see who changed a tooth and which points moved, open the JSON and look at that
tooth's `correction_history` and `manual.changed_landmarks`.

## Run

```bash
python -m pip install -r week7/requirements.txt
python -m pytest -q week7/tests           # 203 tests
python -m week7.build_reports             # rebuild every report in week7/reports/
python -m streamlit run week7/app.py
```

The App and reports use the saved Week 5 predictions and the DenPAR images that
are already in the repository. No model weights or downloads are needed.

## Limitations

- The corrections in the demo cases are simulated, not made by a dentist.
- The stage uses bone loss on the radiograph only. Attachment loss, tooth loss,
  complexity and grade are not included, so Stage III and IV are not separated.
- PBL is a ratio in image pixels. Projection angle and overlapping teeth are not
  corrected.
- 36 teeth is a small sample. The Week 5 reports are still the accuracy results.
- In the App, points are corrected by typing coordinates. The drag tool from
  Weeks 4 and 5 is easier for placing points.
- Corrections made in the App are kept only for the current session. The
  exported JSON is the saved record.

## Files

| File | Role |
|---|---|
| `report.py` | Builds the report: PBL, stage, explanation, warnings, AI vs correction |
| `figures.py` | Annotated radiograph and single-tooth close-up |
| `export.py` | PDF, CSV and JSON export |
| `app.py` | Streamlit App |
| `cases.py`, `edge_cases.py` | The 19 demo cases and 4 edge cases |
| `build_reports.py` | Rebuilds all files in `reports/` |
| `case_report.schema.json` | JSON schema for the exported report |
| `tests/` | 203 tests ([TESTING.md](TESTING.md)) |
