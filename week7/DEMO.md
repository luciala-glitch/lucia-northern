# Week 7 demonstration (about 3 minutes)

Start the App (double-click `run_week7_app.bat` on Windows, or):

```bash
python -m streamlit run week7/app.py
```

1. **Case overview (DENPAR-TEST-68).** Select the case in the sidebar. The page
   header reads "Case DENPAR-TEST-68". Point out the summary row: 4 teeth,
   highest tooth stage III/IV, 4 flagged, 4 reported from corrections, and the
   disclaimer.
2. **Annotated radiograph.** Original on the left, annotated on the right. Box
   colour and line style show the stage (green solid I, amber dashed II, red thick
   III/IV), each label gives PBL %, stage and whether the value is AI or
   corrected, ▲ marks the highest-PBL tooth and ⚠ marks review warnings. Hollow
   blue circles are AI landmarks; white crosses with arrows are corrections.
3. **Tooth table.** Reported mesial, distal and worse-surface PBL, where each value
   comes from, and the AI PBL, stage probability and calibrated 95% interval.
4. **Tooth review: select T4 once.** Everything below follows this choice: a
   close-up of T4 with its landmarks, "Reported from: Simulated correction",
   "AI: 31.2% · Stage II → Reported: 35.0% · Stage III/IV", "Stage set by: distal
   surface (35.0%)", "Landmarks changed: moved Distal CEJ, Distal bone crest", the
   calculation sentence, the warnings and the correction history. The editor
   heading reads "Edit landmarks · T4".
5. **Save a correction for T4.** Change the apex y coordinate, enter your reviewer
   ID and click "Save correction for T4". A green message confirms "Saved for T4
   by … The report now uses this correction", the table row says "Reviewer
   correction (…)", and the history lists the simulated correction and your save.
   Saving without a reviewer ID is refused.
6. **AI-only view.** Untick "Include simulated corrections". The highest stage
   drops to II and every flagged tooth shows `FLAGGED_NOT_REVIEWED`.
7. **Export.** Download the PDF, CSV and JSON. Page 1 of the PDF has the summary
   and figure; page 2 the tooth table and interpretation with the trace. For "who
   changed what", open the JSON: `teeth[3].correction_history`.
8. **Discard.** "Discard my edits for this case" asks for confirmation and names
   the teeth it will reset.
9. **Incomplete data.** Choose `[edge] EDGE-one-surface`: T2 has no distal crest,
   so it shows "one surface only · at least Stage II". `[edge] no case id` has no
   image; the table, editor and exports still work.
10. **A limitation.** DENPAR-TEST-100 T1 is reported as Stage III/IV with 99%
    support but the reference is Stage I. This is why the output is for review.

## Checked automatically vs. by hand

Steps 1, 4, 5, 6, 8 and 9 are covered by `week7/tests/test_app.py` (Streamlit
AppTest). Still to check by hand in a real browser: the layout and readability of
the close-up and the full figure, downloaded files opening correctly, and a JSON
upload through the browser's file picker.
