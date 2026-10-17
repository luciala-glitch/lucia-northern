# Two-sided PBL X-ray Calculator — Week 2

This Streamlit app measures radiographic periodontal bone loss (PBL) directly
on a dental X-ray. It records CEJ, bone crest, and root tip points on both the
mesial and distal surfaces, reports each surface separately, and stages the
tooth from the surface with greater loss.

Week 1 and Week 2 both live in this repository. The Week 1 slider version is
in [`../week1/`](../week1/), and its original submission is also preserved in
the [`week1`](https://github.com/luciala-glitch/pbl-calculator/tree/week1) tag.

## Features

- six-click mesial/distal landmark workflow on a real X-ray;
- 50%–200% zoom controls that preserve already placed landmark positions;
- four bundled CC0 panoramic X-rays from the linked Kaggle dataset (see `sample_xrays/README.md`);
- upload support for JPG, PNG, and TIFF X-rays;
- optional CLAHE contrast enhancement: uses `apply_clahe` from Ansh's
  `enhance_dataset.py` if it's in the project folder, otherwise OpenCV directly
  (`clipLimit=2.0`, `8 × 8` tiles);
- clear handling of zero root length, crest above CEJ, and crest past root tip;
- CSV capture of all point coordinates (in original image pixels), image
  processing state, app version, and results for two measurement rounds;
- a general reading record for single assessments or blinded repeat readings;
- optional **Blind reading mode** hides the current PBL, stage, prior readings,
  and agreement analysis while still allowing the reading to be saved;
- Round 2 automatically starts in blind mode; earlier readings, the current
  result, and the summary stay hidden until the reader completes the session;
- intra-reader agreement with worst/mesial/distal PBL change, stage agreement,
  average pixel shift of each landmark, mean bias, 95% limits of agreement,
  and a repeatability coefficient; and
- pytest coverage for calculations, invalid inputs, worse-side staging, and
  repeatability analysis.

## Download and open in VS Code

Python 3.10 or newer is required.

```bash
git clone https://github.com/luciala-glitch/pbl-calculator.git
cd pbl-calculator
code .
```

If `code` is unavailable, open VS Code, choose **File → Open Folder…**, and
select the `pbl-calculator` folder.

In VS Code, run **Python: Select Interpreter** from the Command Palette and
choose the interpreter inside `.venv`.

## Install and run

In the VS Code terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r week2/requirements.txt
python -m pytest -q week2
python -m streamlit run week2/app.py
```

If `python3 --version` is below 3.10, install a current Python release from
[python.org](https://www.python.org/downloads/) and recreate `.venv` with that
interpreter.

On Windows, activate the environment with `.venv\Scripts\activate`.
Streamlit normally opens the app automatically; otherwise visit
`http://localhost:8501`.

## Measurement workflow

1. Choose a bundled Kaggle image or upload a JPG, PNG, or TIFF X-ray. Any
   `.jpg`/`.png` placed in `week2/sample_xrays/` shows up in the demo list.
2. Optionally enable **Contrast enhancement (CLAHE)**.
3. Click the three mesial points followed by the three distal points, using the
   on-screen order. Use **Undo** or **Reset** to correct a placement.
4. Read the mesial PBL, distal PBL, worse surface, and tooth stage. For an
   independent reading outside the two-round workflow, enable **Blind reading
   mode** before placing points and turn it off only when ready to review.
5. Enter a reader and tooth ID, choose **Round 1**, and save the reading. A
   Round 1 record can also be used as a standalone assessment.
6. For an intra-reader study, select **Round 2** and repeat the same image/tooth
   IDs. Selecting Round 2 automatically enables blind mode so the current
   result and earlier readings are hidden.
7. Select **Complete Round 2 and reveal results**. This automatically turns
   off Blind reading mode and displays the current result, saved readings, and
   agreement analysis. Completion remains set if you switch sessions and come
   back. Download the completed CSV if needed. The submitted
   study results are recorded in
   `week2/REPEATABILITY.md`.

## Calculation and input policy

For each surface:

```text
PBL (%) = distance(CEJ, bone crest) / distance(CEJ, root tip) × 100
```

- CEJ equal to root tip: rejected with a **zero root length** error.
- Bone crest on the crown side of the CEJ: reported as **0%**.
- Bone crest projected past the root tip: **flagged as invalid** rather than
  capped, because it most likely represents a misplaced click.
- Bone crest farther from the CEJ than the root tip, including a severely
  off-axis click: **flagged as invalid** so PBL cannot exceed 100%.

The worse of mesial and distal PBL determines the radiographic stage: Stage I
is below 15%, Stage II is 15% to below one third of the root (33.3%), and one
third or more is reported as Stage III/IV. The calculator uses the exact
one-third boundary internally and rounds only the displayed value. PBL alone
cannot distinguish Stage III from Stage IV; that needs complexity and
tooth-loss information.

Pixel coordinates need no millimetre calibration because PBL is a ratio.

## Measurement limitations

- The formula uses the full CEJ-to-crest distance and does not subtract the
  normal physiological CEJ-to-alveolar-crest space. Because the app has no
  millimetre calibration, early bone loss can be overestimated.
- The bundled examples are panoramic radiographs, which may contain blur,
  overlap, and geometric distortion. Intraoral/periapical imaging is generally
  better suited to confirmatory measurements requiring high precision.
- This is a point-placement and workflow demonstration, not a clinical
  diagnostic or validation tool.
- A future optional shared-apex mode could reduce one click for a confirmed
  single-rooted tooth. The six-point workflow remains the default because it
  supports separate surfaces and multi-rooted teeth and matches the assignment.

Method references: the [2018 AAP/EFP staging framework](https://doi.org/10.1002/JPER.18-0006),
[normal radiographic CEJ-to-crest reference values](https://pubmed.ncbi.nlm.nih.gov/1941497/),
[Bland–Altman measurement-error guidance](https://www.bmj.com/content/312/7047/1654),
and a [panoramic versus intraoral comparison](https://pmc.ncbi.nlm.nih.gov/articles/PMC12746162/).

## Dataset credit

The included images (1, 10, 26, 42 from `Teeth Segmentation JSON/d2/img/`) are from
[Humans in the Loop's Teeth Segmentation on dental X-ray images](https://www.kaggle.com/datasets/humansintheloop/teeth-segmentation-on-dental-x-ray-images),
released under CC0. The project includes only the four demo images, not the
full dataset.

## Repeatability deliverable

`week2/measurements.csv` contains the completed 20 observations (10 teeth ×
2 rounds). New saves include whether CLAHE was enabled, the app commit/version,
and a superseded-record timestamp. Re-saving the same reader/session/image/tooth
now appends an auditable version instead of deleting the earlier row; summaries
use the newest version. The historical 20 rows are marked `unknown` for CLAHE
and app version because those fields were not recorded at measurement time; the
values were not guessed retrospectively. The app also provides a CSV download
button.
`week2/REPEATABILITY.md` reports the observed PBL changes, agreement metrics,
landmark shifts, and the limitation that this demonstration used a same-day
repeat rather than the requested multi-day interval.

This project is an educational measurement tool, not a diagnostic device.
