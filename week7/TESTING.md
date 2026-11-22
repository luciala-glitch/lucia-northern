# Week 7 tests

From the project folder, run these commands.

```bash
python -m pip install -r week7/requirements.txt
python -m pytest -q week7/tests
```

The suite has 203 tests. [Test output](reports/test_results.txt)

## What I checked

- **Measurements.** I compared both sides of each tooth with the Week 3 calculator. I also checked the original PBL and stage against the saved Week 5 predictions.
- **Stage cutoffs.** Exactly 15% and exactly 33% both fall in Stage II. The report shows extra decimals when rounding would hide which side of a cutoff the value falls on.
- **Review flags.** A tooth is flagged if stage support is below 94% or the model reverses the apex direction. A separate warning marks values within three percentage points of a cutoff. For context, the Week 3 reader limits of agreement were about ±11 percentage points.
- **Missing points.** Without an apex, the report leaves PBL blank. With one crest missing, it gives a minimum stage. I also checked invalid coordinates, missing images and duplicate tooth IDs.
- **Edits.** I checked that switching from case 5 to case 68 keeps each case’s own points. Two saves and a removal must all appear in the history. An edit needs a reviewer, time and method before the report can use it.
- **Selected tooth.** In case 68, selecting T4 updates the image, measurements and editor together. Saving changes only T4. Discarding edits takes a second click.
- **Uploads.** Two files can have the same name and size. The app checks the file contents to tell them apart.
- **Exports.** I checked CSV and JSON for 19 demo cases and four edge cases. I checked the text in 12 PDFs for the case ID, measurements and simulated-edit label. The saved CSV and JSON files must match a fresh export.

## Results on the demo cases

The 19 images contain 36 teeth. The review rule flagged 17. The original stage matched the reference for 28 teeth. After simulated edits, 34 matched. Those edits use reference points, so the second count only describes this demo.

[Results by tooth](reports/all_cases_summary.csv) · [Case totals](reports/all_cases_stats.json)
