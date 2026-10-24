# Week 3: PBL Measurements and Repeatability

For Week 3, I continued working on the PBL calculator and compared two readings
of the same 15 teeth under Raw, HE and CLAHE. I included the 90 saved readings,
figures and [report](reports/collected_study/WEEK3_COLLECTED_REPORT.md).
The [submission page](reports/collected_study/SUBMISSION.md) has the repository
and current pull request links.

## 1. Install

Use Python 3.11 or later. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r week3/requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead.

## 2. Use the calculator

```bash
python -m streamlit run week3/app.py
```

Open the address shown in the terminal, usually <http://localhost:8501>.

1. Choose a sample image or upload an image. In **Register teeth**, click each
   crown centre and register the tooth once. These IDs identify study teeth,
   rather than using a clinical numbering system.
2. Open **Measure teeth** and select a registered tooth. Place the mesial CEJ,
   mesial bone crest, distal CEJ, distal bone crest and shared anatomical apex.
3. Use **Record tooth**, then **Next tooth**. A saved tooth is locked for that
   condition and round. **Amend this reading** allows a correction with a reason
   while keeping the previous record in the amendment log.
4. Export JSON and CSV from **Export measurements**. The local study database
   is kept in `week3/data/` and excluded from Git. **Start over** archives the
   current study rather than deleting it.

Routine mode works with the teeth registered for that session. For the Week 3
protocol, choose **Research protocol**, 15 teeth, Raw/HE/CLAHE and two rounds.
Blind mode hides previous results while marking. A confirmed dental midline can
help with mesial/distal orientation. Zoom and pan do not change the original
pixel coordinates; **Pan image**, **Fit image** and **Find selected tooth** help
with navigation. The optional crown point enables the root-to-crown ratio warning.

## 3. Reproduce the report

```bash
python -m week3.reports.collected_study.build_report
```

This uses the bundled [JSON](reports/collected_study/exports/measurements.json)
and [CSV](reports/collected_study/exports/measurements.csv), rather than the local
app database. It regenerates the agreement plots, five case overlays,
2/5/10 px sensitivity results, coordinate comparison and crest profiles.
The report inputs and saved test evidence are checked before rebuilding; after
code changes, run the checks in the next section first.

The [radiographic appendix](reports/collected_study/radiographic_cases/RADIOGRAPHIC_CASES.md)
uses existing image examples for restoration/CEJ difficulty, projected molar-root
overlap and tilt. Its older six-point restoration example is kept outside the
main statistics. Sample attribution is in [Week 2's image README](../week2/sample_xrays/README.md).

To analyze another combined export:

```bash
python -m week3.analyze --measurements measurements.json --output week3/reports/new_study
```

The older `reports/WEEK3_REPORT.md` is a separate Week 2 exploratory analysis.
It is not the report for the completed 90-reading collection.

## 4. Run the tests

Node.js 18 or later is needed for the frontend checks.

```bash
python -m week3.reports.collected_study.run_checks
python -m week3.reports.collected_study.build_report
```

If Node is not on PATH, use `run_checks --node /path/to/node` with the same module
command. The checks save the test output, coverage and verification manifest.
The current results are **142 Week 3 tests, 217 project tests and 14 frontend
tests passed**, with **28/28 engine branches covered**.

Individual commands are also available:

```bash
python -m pytest -q
python -m pytest week3/tests --cov=week3.pbl_calculator --cov-branch --cov-fail-under=90
node --test week3/tests/canvas_frontend.test.cjs
```

The results describe one reader and one image. The timing, reading order and
other study limits are explained in the report.
