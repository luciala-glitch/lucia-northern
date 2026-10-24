# Week 3 — PBL measurements and repeatability analysis

For Week 3, I continued working on the PBL calculator from Week 2. I used a
shared tooth axis for both surfaces, added checks for invalid points, and
compared repeated measurements under Raw, HE and CLAHE. I kept the earlier
weeks in their own folders so the changes could be reviewed separately.

**Current collection: 15 teeth × 3 conditions × 2 rounds = 90 saved readings
/ 180 surface observations**, from one image and one reader. See the
[current full report](reports/collected_study/WEEK3_COLLECTED_REPORT.md),
[validated empirical exports](reports/collected_study/exports/measurements.json).
The two analyzed rounds were about 13 hours apart, after an excluded earlier
RAW session, with fixed RAW → HE → CLAHE condition order. The report discloses
practice/recall confounding; separate markings are not proof of independent
perception. See [the review response](reports/collected_study/REVIEW_RESPONSE.md).

The old `reports/WEEK3_REPORT.md` remains a separate 10-tooth Week 2 exploratory
analysis and must not be presented as the result of this completed study.

## Setup and run

From the repository root, use Python **3.11 or later** (verified on 3.13):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r week3/requirements.txt
python -m streamlit run week3/app.py
```

Windows activation: `.venv\Scripts\activate`. Streamlit opens at
<http://localhost:8501>. Run these commands from the repository root so package
imports resolve. No external enhancer module is required: Week 3 uses OpenCV
CLAHE directly, fixed at clip limit 2.0 and tile grid (8,8).

## Measure and export

New sessions default to **Routine measurement**: one reading per registered
tooth, with results visible and no condition/round task checklist. A session with
five registered teeth shows progress out of five. Under **Measurement settings**,
choose **Research protocol** to set an optional target tooth count, included image
conditions and any positive number of rounds, then **Apply settings**. A target
is a progress goal, not a registration cap; if more teeth are registered, progress
uses the larger registered count. Existing sessions retain their prior research
plan on upgrade. Changing modes or settings preserves all records, drafts and
locations, including readings outside the new plan; exports include every record.

1. **Register teeth**: select a sample X-ray or upload an image. Click a crown
   centre, then **Register tooth**. Repeat for the teeth you want to measure; there is no fixed registration limit.
   The numbered location boxes stay fixed across all conditions and rounds.
   IDs are study numbers, not FDI/Universal tooth numbers. A nearby-location
   guard flags likely duplicates; it does not recognize tooth anatomy.
   Optionally confirm the **dental midline** for each image (the line between the
   central incisors). On panoramic films the app suggests one from left–right
   symmetry; check it and confirm or edit it. For periapicals, choose the edge
   that faces the front of the mouth. With a midline, prompts say which image side
   is mesial for each tooth and warn when a mesial point lands on the distal side.
2. **Measure teeth**: choose a registered tooth. Its original image is selected
   automatically. The selected tooth keeps a faint number only, without a circle or T prefix. Other tooth labels stay hidden until **Show tooth locations** is enabled. Switching teeth automatically centres the selected location. The tooth selector and **Previous tooth** sit above the image. The single **Next tooth →** button sits beside the image, directly below **Record tooth**. Choose `raw`, `he` or `clahe`, and Round 1 or 2. Use
   **Find selected tooth** to centre and enlarge its fixed location. In research
   mode, each condition/round presents teeth in its own reproducible shuffled
   order, so the sequence does not cue recall of earlier readings.
3. Click mesial CEJ, mesial bone crest, distal CEJ, distal bone crest, then the
   **shared anatomical root apex**. The green line connects your points; the
   software checks geometry, not anatomical correctness. Optional crown-tip
   placement enables the ratio check. Obtain an appropriate expert review for
   ambiguous, overlapping or multi-root landmarks.
4. **Record tooth** becomes available after valid placement. Recording locks
   that tooth for this condition and round. Saving and tooth navigation update only
   the measurement workspace; the image stays mounted and retains zoom and pan.
   The save button keeps its position, and saved landmarks remain visible for review. Both the UI and a database unique
   constraint prevent a repeated click from adding another record. Other
   conditions/rounds remain independent. Choose **Next tooth →** beside the image after saving to
   continue. The shortcut stays disabled until the current tooth is recorded,
   helping prevent a completed draft from being skipped. Switching teeth opens
   a wider view with crown-to-root margin instead of the previous 200% zoom. The checklist shows all six readings for each registered tooth.
   To correct a recorded reading, open **Amend this reading**, give a reason and
   choose **Reopen for re-marking**. The original record, its save time and the
   reason move to an amendment log (exportable); the tooth is re-marked from
   scratch. Records store their UTC save time, and Round 2 shows the time since
   Round 1 of the same condition.
5. Drafts and records are saved locally in `week3/data/studies.sqlite3`, including
   the source images and tooth locations. Refreshing the browser or restarting
   the local app preserves them. Export JSON/CSV regularly for a separate copy;
   exports are available with blind mode on, without showing results on screen.
   Blind mode defaults on. No previous-reading landmarks are shown while placing
   a new reading. Allow a suitable washout interval (reader studies often use
   about 2–4 weeks) and randomize condition order.
6. **Clear current landmarks** clears only the current unrecorded draft;
   **Undo last point** removes one point. **Start over…** opens a second step:
   **Archive current study and start new**. This creates an empty study without
   deleting the old records, locations, images or drafts. **Resume archived study**
   restores an old study and archives the current one. Opening or cancelling the
   restart panel changes no study data.
7. Existing session records migrate automatically on upgrade. JSON imports append
   without overwriting conflicting measurements. Imported locations are estimated
   from the CEJs and marked unconfirmed: visually confirm the identity before
   adding another condition/round. Legacy JSON has no image checksum; retain the
   original image and verify it when attaching it to an imported study.
8. For the original assignment only, configure 15 teeth × 3 conditions × 2 rounds
   to collect **90 tooth records / 180 surfaces**. This is not a universal app requirement.
   Do not reuse the five landmark clicks across conditions.

Navigation stays above the image: **＋ / −**, **Fit image**, and **Pan image**.
A drag pans in either mode; only a stationary click in Mark mode places a point.
Space temporarily enables Pan; Ctrl/Command + wheel zooms around the cursor.
Zoom and pan preserve original-image coordinates. Image decoding/encoding is
cached; after the browser acknowledges the image, updates carry `src=null`.
A new iframe requests its missing image. No public static image directory is used.

The local study directory is excluded from Git. SQLite records are stored on this
computer; this is local research storage, not a clinical records system or a cloud
backup. See [the UX rationale and verification](UX_RESEARCH.md).

App exports retain the exact requested schema. It contains no crown field;
optional crown information and its warning are displayed during measurement
but are not persisted in this fixed schema. An invalid crown point is reported
and ignored; it never blocks saving a valid PBL measurement. Use a separate study log if crown
measurements or observer identity must be audited. Do not pool multiple observers
in one export without an external observer manifest.

## Geometry and validation

`u = (apex − midpoint(CEJ_mesial, CEJ_distal)) / norm(...)`.
For each side, use signed dot products with `u` to enforce
`0 <= defect <= root`, then calculate `PBL = abs(defect) / abs(root) * 100`.
A lateral crest displacement is allowed when its axial coordinate is valid;
raw Euclidean distance is never substituted.

- Stage I: <15%; II: 15–33% inclusive; III/IV: >33%, with a furcation/vertical
  defect review flag. This implements the assignment's **33**, not 100/3.
  PBL is rounded to 9 decimals before staging so floating-point error on a
  tilted axis (exact 15% computed as 14.999999999999996) cannot change stage.
- `CoordinateError`: malformed, nonnumeric or nonfinite points.
- `DegenerateGeometryError`: undefined axis, zero/negative projected root length,
  or an optional crown tip that does not project coronally.
- `BoneCrestBoundsError`: crest coronal to CEJ or beyond apex. Signed validation
  precedes absolute values. Numerical tolerance is 1e-9 px at bounds.
- `AnatomicalPlausibilityWarning`: optional measured root/crown ratio <1 or >2.5.
  Without a crown point, the ratio is unavailable; it is never guessed.
- Collinearity alone is valid; coincident CEJ/apex that causes a zero projected
  root length is not. No blanket collinearity rejection removes valid axial cases.

Coordinates are original-image pixels regardless of display scale. The engine
supports continuous coordinates for math; exports require exact integer pixels
and reject fractional inputs instead of silently rounding them. JSON Schema
also rejects extra properties, negative coordinates and incorrect field types;
validation additionally rejects float-typed IDs/rounds/pixels such as `1.0`,
which JSON Schema itself counts as integers. Stored axis and metrics are
recalculated during validation to catch stale values (floats agree to 1e-9).
CSV columns are typed by name, not cell content, so an `image_id` such as
`[2024] scan.png` round-trips. Text cells starting with `= + - @` (or `'`) are
prefixed with `'` against spreadsheet formula injection and unescaped on import.
The app additionally checks all landmarks against image bounds.

## Reproduce the completed 90-reading report

From the repository root after installing dependencies:

```bash
python -m week3.reports.collected_study.build_report
```

This study-specific builder validates the bundled JSON/CSV, exact cohort, image
checksum and coordinate bounds; recomputes all three agreement analyses; and
regenerates the current report, plots, 2,700 sensitivity trials, five ranked
review teeth and crest profiles. It reads
`reports/collected_study/exports/measurements.json`; it does not change local app
records or the SQLite database. It uses saved test evidence for the verification
section, so run `run_checks` to refresh the logs and `verification_manifest.json` after code changes. Install Node.js or pass `--node /path/to/node` when it is not on PATH. The manifest binds test evidence to source hashes; the builder fails when these differ. The input JSON is also frozen by checksum, so a changed dataset needs a new editorial review.

```bash
python -m week3.reports.collected_study.run_checks
python -m week3.reports.collected_study.build_report
```

The [radiographic case appendix](reports/collected_study/radiographic_cases/RADIOGRAPHIC_CASES.md)
uses existing saved readings for restoration/CEJ, projected molar-root overlap and
tilted-tooth screening examples. The legacy six-point restoration example is
kept outside the main 90-reading statistics. The report distinguishes these
visual interpretations from expert reference labels and synthetic mechanisms. Completing the local
report does not establish anatomical accuracy or clinical validation.

## Reproduce the legacy Week 2 exploratory analysis

```bash
python -m week3.analyze
```

This reads the original Week 2 CSV without editing it and generates:

- [Statistical verification and failure study](reports/WEEK3_REPORT.md), with
  ICC(2,1), quadratic weighted kappa and Bland–Altman plot.
- Five ranked tooth overlays with round-to-round displacement and projections.
  The report states how many surfaces actually lie outside the LoA; other review
  cases are not falsely called outliers. All counts and coefficients in the
  report are computed (undefined values print as "undefined", never crash). The
  report also states the round interval, image count and PBL range that limit
  interpretation. Synthetic diagrams show restoration/overlap/tilt
  stress scenarios separately.
- `error_decomposition.csv`: per-landmark mean axial/normal drift, total RMS,
  and centered residual RMS, separating descriptive directional and residual
  displacement components without assigning an unverified cause.
- `sensitivity.csv`: 600 signed 2/5/10-pixel trials, one landmark at a time,
  parallel and normal to the baseline axis, with axis recomputation and rejection
  status. `sensitivity_summary.csv` aggregates worse-side PBL changes.
- `crest_edge_metrics.csv`, `crest_profile.png`, `contrast_comparison.png`, and
  `preprocessing_comparison.csv`: fixed-coordinate contrast controls. The crest
  chord is a proxy tangent. Increased gradients can reflect noise as well as
  contrast; these controls do not measure human placement stability.
- `legacy_recomputed_metrics.csv` and `provenance.json`: condition remains
  **unknown**. The legacy records are not relabeled as raw or exported as
  purported conforming Week 3 empirical records.
- `exports/synthetic/`: 90 software examples, explicitly synthetic. Their
  coordinates are deliberately identical across condition labels. They test the
  schema/export pipeline, not image enhancement or clinical repeatability.

ICC is the two-way random-effects, single-measure, absolute-agreement estimator.
Quadratic kappa returns `None` when expected disagreement is zero (all readings
in one category), rather than incorrectly reporting 1.0. LoA use sample SD
(ddof=1). Staging and continuous agreement are reported at surface level, plus
worse-side tooth stage kappa. Shared tooth/apex clustering and same-day memory
make these descriptive estimates, not independent clinical validation.

With an explicit `--output` directory, legacy report generation puts **all**
artifacts there, including synthetic fixtures in `exports/synthetic/` underneath
that directory. Without `--output`, the original `week3/reports` and
`week3/exports/synthetic` locations are preserved. For an isolated check:

```bash
python -m week3.analyze --output /tmp/pbl-week3-report
```

## Analyze newly collected condition-specific data

Download the app's combined JSON, then run:

```bash
python -m week3.analyze --measurements measurements.json --output week3/reports/new_study
```

The command validates every record and rejects duplicate identities. It refuses
`SYNTHETIC_` fixture records unless `--allow-synthetic` is passed (pipeline tests
only), and warns that rounds other than 1/2 are excluded from agreement. It writes
statistics and Bland–Altman figures separately per condition when at least two
teeth have complete rounds. `preprocessing_comparison.json` reports:

- Complete image/tooth/round triplets across raw, HE and CLAHE (incomplete
  triplets are counted and excluded).
- Pooled coordinate RMSD relative to raw: `sqrt(mean(dx² + dy²))`, in pixels,
  over all five landmarks of the matched triplets (raw itself is `null`).
- Within-condition Round 1–2 coordinate RMSD for teeth whose matched triplets
  are complete in both rounds, so every condition uses the same teeth.
- Mean within-landmark sample x+y variance across two rounds:
  `mean(dx² + dy²) / 2`, in px². Not the variance of pooled absolute image positions.

No pairs produces missing metrics (`null`), never a misleading zero. Local
crest profiles are also available through `crest_profile(image, crest, tangent)`
when expert local tangent annotations are available.

## Tests and coverage

```bash
python -m pytest week3/tests --cov=week3.pbl_calculator --cov-branch --cov-report=term-missing --cov-report=json:week3/reports/coverage.json --cov-fail-under=90 -q
python -m pytest week3/tests --cov=week3 --cov-branch --cov-report=term-missing --cov-report=json:week3/reports/full_coverage.json -q
python -m pytest -q
# Optional frontend logic tests (Node.js 18+; no npm dependencies):
node --test week3/tests/canvas_frontend.test.cjs
```

Verified Week 3 result: **142 passing Python tests; 100% of engine branches covered**.
The full project has **219 passing Python tests**. All 14 frontend logic tests also passed on the current code. Fresh logs and coverage
for the completed collection are saved in `reports/collected_study/`.
Coverage for each module is recorded in the current coverage JSON. The engine target is checked separately; coverage of the application or report-writing helpers is not clinical validation.
The real legacy-report pipeline is now tested end to end in temporary directories:
known numerical results, CSV counts, decodable plot files, report image links,
synthetic-export roundtrips, all-rejected perturbations, and repository files
remaining unchanged. Both default and explicit output paths are exercised.

See [saved full test output](reports/full_test_results.txt),
[full coverage JSON](reports/full_coverage.json), and
[engine coverage JSON](reports/coverage.json). Tests cover exact stage boundaries,
signed bounds, axis/crown degeneracy, geometry invariance, hand-derived ICC and
kappa examples, sample-SD LoA, missing contrast data, CSV/JSON roundtrips,
perturbations, contrast profiles, and the app's save/duplicate/reset workflows.

## Image transport verification

The handshake tests check image acknowledgement, rejection of old-image messages,
rapid clicks, undo/reset, missing-image recovery, condition changes, pixel-floor
coordinates, pixel-centre drawing, zoom anchors, panning without accidental
landmarks, and original-coordinate correctness after panning. A real-browser check also exercised five
clicks, undo, switching to CLAHE, and another click. The frontend logic harness is
separate from that browser check.

Before the tooth-roster upgrade, bundled sample 1 in raw mode serialized component arguments measured
**1,071,480 bytes on first transfer versus 487 bytes for a five-point update**.
This is a **99.95% reduction in these arguments**, not a measurement of total
WebSocket traffic or end-to-end latency. See [the measurement](reports/canvas_transport.json).
The first image and condition changes still require transferring image data.
The current roster adds small location/status fields; the historical 487-byte
figure is not a current roster payload benchmark.

## Submission status

| Checklist item | Status |
| --- | --- |
| Typed projected engine and guardrails | Complete |
| Passing tests and >90% engine branch coverage | Complete (100%) |
| Statistical report and generated figures | Complete for 15 paired teeth in each of three conditions |
| Five ranked review-case overlays and perturbation study | Complete; four surface differences exceed condition-specific LoA; existing-image screening appendix added; legacy restoration example separate |
| Three-condition preprocessing code and edge control table | Complete |
| Separately marked three-condition localization variance table | Complete, 30 matched tooth/round triplets |
| Structured JSON/CSV export pipeline and examples | Complete; 90 empirical readings bundled with current report; synthetic fixtures separate |
| 15-tooth empirical study | Complete: one image, 15 registered teeth, three conditions, two rounds |
| GitHub submission | [My repository and pull request links](reports/collected_study/SUBMISSION.md) |

The configured repository is [luciala-glitch/pbl-calculator](https://github.com/luciala-glitch/pbl-calculator).
I recorded the submission links in [SUBMISSION.md](reports/collected_study/SUBMISSION.md).
The sample X-ray source/license details remain in [Week 2's attribution](../week2/sample_xrays/README.md).
