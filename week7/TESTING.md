# Week 7 testing

```bash
python -m pip install -r week7/requirements.txt
python -m pytest -q week7/tests
```

Result: **203 passed** in a clean virtual environment with the pinned versions
(Python 3.13, numpy 2.2.6, matplotlib 3.11.2, Pillow 11.3.0, streamlit 1.51.0,
reportlab 5.0.1, pypdf 6.17.0, jsonschema 4.26.0). Full output:
[`reports/test_results.txt`](reports/test_results.txt).

## What is tested

| Area | Test | Cases |
|---|---|---|
| Calculation accuracy | every reported mesial, distal and worse-surface PBL and stage equals an independent call to the Week 3 calculator on the landmarks the report says it used | 19 demo cases |
| Consistency with earlier weeks | automated PBL and stage equal the saved Week 5 predictions (`pred_pbl`, `pred_stage`) | 19 |
| Traceability | the input is not modified; automated landmarks in the report equal the input; corrected teeth report `source = manual` with reviewer, time and method; `changed_landmarks` matches the moved distances | 19 |
| Flags and warnings | flag ⇔ P(stage) < 0.94 or orientation switch; `STAGE_CHANGED_BY_CORRECTION` ⇔ stages differ; `NEAR_STAGE_BOUNDARY` ⇔ within 3 pp of 15% or 33% | 19 |
| Stage boundaries | 14.99% → I, 15.0% → II, 33.0% → II, 33.01% → III/IV | 4 |
| Missing measurements | missing apex → no PBL, `MISSING_LANDMARKS`, `FLAGGED_NOT_REVIEWED`; one missing crest → no stage, "at least Stage II"; bad coordinates (`None`, strings, NaN, ∞, wrong length) treated as missing | 4 edge cases + 6 inputs |
| Invalid correction | crest placed above the CEJ → correction rejected, nothing reported, automated record kept | 1 |
| Incomplete case data | no case ID, no image, empty tooth, duplicate tooth ID, no teeth | 2 |
| CSV export | one row per tooth; every reported, automated and corrected value equals the report rounded to 2 dp; reviewer, changed landmarks and warning codes match | 23 |
| JSON export | validates against `case_report.schema.json`; equals the report exactly; contains the untouched input case | 23 |
| PDF export | text extracted from the PDF contains the case ID, the disclaimer, each reported and automated PBL to 1 dp, and the `SIMULATED` label for simulated corrections | 12 |
| Committed files | the CSV text (line endings ignored) and the parsed JSON in `reports/cases/` equal a fresh export | 19 |
| App | App table (mesial, distal, worse PBL, stage, AI PBL) equals the report for all 19 cases; all 4 edge cases render with export buttons and never show a missing value as 0.0%; a correction without a reviewer ID is refused | 19 + 4 + 1 |
| App corrections (regression tests from the code review) | editing case 5 then switching to case 68 and saving keeps case 68's own coordinates; two saves and a removal are all kept in `correction_history`; untouched points keep full precision; saving a tooth with a missing crest keeps it missing (partial, not invalid) | 3 |
| Correction tracing | 0.1 px moves, added and removed landmarks are recorded; a correction without reviewer/time/method raises `CORRECTION_PROVENANCE_MISSING`, is kept in the record and is not used for the reported values; the CSV lists every history event | 3 |
| Tooth review (usability round) | Case 68 → T4: panel shows AI 31.2% · Stage II → 35.0% · Stage III/IV, distal surface, moved Distal CEJ and Distal bone crest, editor titled "Edit landmarks · T4"; saving changes only T4 and shows a confirmation; "Reported from corrections" equals `teeth_reported_from_manual` and excludes unattributed corrections; discard needs confirmation; review panel works with no image or no landmarks | 5 |
| Uploads | an uploaded case is identified by the SHA-256 of its content, so two files with the same name and size (CASE-A, CASE-B) never share App state | 1 |
| Boundary wording | the explanation never shows a rounded value that contradicts the stage (14.99, 14.999, 15, 33, 33.004, 33.01) | 6 |
| Files | missing image file raises `IMAGE_NOT_FOUND`; case IDs with Windows-invalid characters export to safe file names; `True`/string coordinates are rejected | 10 |

## Demo-case results

`python -m week7.build_reports` writes [`reports/all_cases_summary.csv`](reports/all_cases_summary.csv)
and [`reports/all_cases_stats.json`](reports/all_cases_stats.json).

| | Count |
|---|---:|
| Cases (radiographs) | 19 |
| Teeth | 36 |
| Flagged by the Week 5 review rule | 17 |
| With (simulated) correction | 17 |
| Automated stage = DenPAR reference | 28 / 36 |
| Reported stage = DenPAR reference | 34 / 36 (optimistic: corrections copy reference points) |

These counts describe the demo sample only. They are not an accuracy estimate.
