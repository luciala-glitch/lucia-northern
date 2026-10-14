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
- CSV capture of all point coordinates (in original image pixels) and results
  for two measurement rounds;
- blind Round 2: saved data and the summary stay hidden until you tick
  "I've finished Round 2";
- repeatability summary with worst/mesial/distal PBL change, stage agreement,
  and the average pixel shift of each landmark; and
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

## Install and run

In the VS Code terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r week2/requirements.txt
python -m pytest -q week2
python -m streamlit run week2/app.py
```

On this Mac, the installed Python 3.13 interpreter is at
`/opt/anaconda3/bin/python3.13`. If `python3 --version` shows Python 3.9, create
the environment with this command instead:

```bash
/opt/anaconda3/bin/python3.13 -m venv .venv
```

On Windows, activate the environment with `.venv\Scripts\activate`.
Streamlit normally opens the app automatically; otherwise visit
`http://localhost:8501`.

## Measurement workflow

1. Choose a bundled Kaggle image or upload an X-ray. Any `.jpg`/`.png` placed
   in `week2/sample_xrays/` shows up in the demo list.
2. Optionally enable **Contrast enhancement (CLAHE)**.
3. Click the three mesial points followed by the three distal points, using the
   on-screen order. Use **Undo** or **Reset** to correct a placement.
4. Read the mesial PBL, distal PBL, worse surface, and tooth stage.
5. Enter an observer and tooth ID, choose **Round 1**, and save the row.
6. Measure 10 teeth across several images. A few days later, repeat those same
   image/tooth IDs as **Round 2** without looking at Round 1.
7. Download `measurements.csv` and copy the app's repeatability summary into
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

The worse of mesial and distal PBL determines the radiographic stage: Stage I
is below 15%, Stage II is 15% to below 33%, and 33% or more is reported as
Stage III/IV. PBL alone cannot distinguish Stage III from Stage IV; that needs
complexity and tooth-loss information.

Pixel coordinates need no millimetre calibration because PBL is a ratio.

## Dataset credit

The included images (1, 10, 26, 42 from `Teeth Segmentation JSON/d2/img/`) are from
[Humans in the Loop's Teeth Segmentation on dental X-ray images](https://www.kaggle.com/datasets/humansintheloop/teeth-segmentation-on-dental-x-ray-images),
released under CC0. The project does not include the full 5.7 GB dataset.

## Repeatability deliverable

`week2/measurements.csv` is a header-only template until the observer records
the 20 observations (10 teeth × 2 rounds). The app writes each saved row to
that file and also provides a download button. `week2/REPEATABILITY.md`
explains exactly which summary values to report. Results are intentionally not
fabricated: Round 2 must be performed after the requested waiting interval.

This project is an educational measurement tool, not a diagnostic device.
