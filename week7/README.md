# Week 7 · Reviewing periodontal bone loss on a radiograph

In Week 5 I saved the landmarks for each tooth. This week I used those points to make a report. I wanted to see how moving a point changed the periodontal bone loss (PBL) measurement.

On a Mac, double-click `Open-Week7.command` inside the week7 folder to open the editor. Keep the terminal window open during the demo. You can also use the commands below.

The [case browser](case-review.html) shows saved results. In the editor you can select a tooth, enter your name under **Reviewer name or ID**, edit its points and export the updated report.

## Try one case

From the project folder, run the following commands.

```bash
python -m pip install -r week7/requirements.txt
python -m streamlit run week7/app.py
```

Choose **DENPAR-TEST-68**, leave simulated corrections on, and select **T4**. The original prediction gives 31.2% PBL (Stage II). After two landmarks move, the distal surface gives 35.0% (Stage III/IV). The close-up shows which points moved. The history below it records where the correction came from.

The PDF includes the annotated image, tooth table and warnings. The CSV has one row per tooth. The JSON includes the input coordinates and correction history. Edits last for the current session, so download the JSON to keep them. [Example PDF](reports/cases/DENPAR-TEST-68/DENPAR-TEST-68.pdf) · [Demo walkthrough](DEMO.md)

## What I found

| DenPAR test set | Result |
|---|---|
| Radiographs and teeth | 19 images, 36 teeth |
| Teeth flagged for review | 17 |
| Automated stages matching the reference | 28 of 36 |
| Stages matching after simulated corrections | 34 of 36 |

I used the DenPAR reference points to simulate edits. For each flagged tooth, I replaced the two points with the most uncertainty. Then I checked the table and the three exports. Because the edits use the reference itself, I expect more stages to match after an edit. I still need edits from a clinician to see how this works in practice.

The review rule missed **DENPAR-TEST-100, T1**. The model gave it 43.5% PBL with 99% stage support, but the reference was 13.6%. **DENPAR-TEST-22, T2** shows a different problem. Even after correction, 14.9% falls just below the Stage II cutoff.

## How to read a tooth record

The [report code](report.py) uses the Week 3 calculator for the mesial and distal surfaces. The larger PBL sets the tooth stage. Values below 15% fall in Stage I, 15% through 33% in Stage II, and values above 33% in Stage III/IV. If one crest is missing, the measurable side gives only a minimum stage.

Open `auto` for the original prediction or `manual` for the latest edit. The list in `correction_history` shows each save and removal. Check `final.source` to see which measurement the report used. A correction missing its reviewer, time or method stays in the record and raises a warning. The table falls back to the automated measurement if available.

These are tooth-level research measurements on a 2D image. Projection and overlap can affect the result. The report does not establish a patient diagnosis or distinguish Stage III from Stage IV.

## Checks

The [test notes](TESTING.md) cover the export comparisons and hand calculations. The [edge cases](reports/edge_cases/) include a missing apex, one missing crest, an invalid correction, and a case with neither an ID nor an image. I checked that edits stay with the right case. I also checked that saving twice keeps both edits in the history.

```bash
python -m pytest -q week7/tests
python -m week7.build_reports
```

Rebuilding uses the images in `week4/demo_denpar/external_test/` and the saved predictions in `week5/reports/`. The generated files go into [reports](reports/). The JSON fields are defined in the [report schema](case_report.schema.json).

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

The interval crossed a stage cutoff for 27 of the 36 teeth. I moved this warning to info so the other warnings are easier to find.
