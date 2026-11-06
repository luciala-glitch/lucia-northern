# Lucia · Northern Internship

I keep my internship work in separate weekly folders so the code, measurements
and reports can be reviewed from one GitHub link.

| Version | Folder | What it does |
| --- | --- | --- |
| Week 1 | [`week1/`](week1/) | Calculates PBL from sliders for one tooth surface. |
| Week 2 | [`week2/`](week2/) | Places six landmarks on a real X-ray, reports mesial/distal PBL, stages from the worse surface, and records repeatability measurements. |
| Week 3 | [`week3/`](week3/) | Typed long-axis projection, statistical agreement, sensitivity and contrast analysis, validated JSON/CSV exports. |
| Week 4 | [`week4/`](week4/) | Pretrained heatmap landmark detector vs classical baseline on 1,657 DenPAR teeth (radiograph-level 5-fold CV + external test), uncertainty-based rejection, failure analysis, and an auto-detect → correct → export review App. |
| Week 5 | [`week5/`](week5/) | Refines the Week 4 model, checks its uncertainty, improves the review rule, and adds 12 annotated clinical examples. |

## Quick start

Python 3.10 or newer is required.

```bash
git clone https://github.com/luciala-glitch/lucia-northern.git
cd lucia-northern
python3 -m venv .venv
source .venv/bin/activate
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\activate
```

### Run Week 1

```bash
python -m pip install -r week1/requirements.txt
python -m pytest -q week1
python -m streamlit run week1/app.py
```

### Run Week 2

```bash
python -m pip install -r week2/requirements.txt
python -m pytest -q week2
python -m streamlit run week2/app.py
```

### Run Week 3 (Python 3.11+)

```bash
python -m pip install -r week3/requirements.txt
python -m pytest week3/tests --cov=week3.pbl_calculator --cov-branch --cov-fail-under=90
python -m week3.reports.collected_study.build_report
python -m streamlit run week3/app.py
```

See the [current Week 3 report](week3/reports/collected_study/WEEK3_COLLECTED_REPORT.md)
and [detailed instructions](week3/README.md). For Week 3, I measured
15 teeth on one image under three separately marked conditions in two rounds:
90 tooth readings / 180 surface observations. I included the saved measurements
and figures with the current report, along with the limits of this small study.
Older Week 2 exploratory reports and synthetic examples remain separate; they
are not pooled with this collection.

### Run Week 4

```bash
python -m pip install -r week4/requirements.txt -r week4/requirements-model.txt
python -m streamlit run week4/app.py
make reproduce PYTHON=python   # data → split → (missing) weights → all reports
```

See [`week4/README.md`](week4/README.md) for weights download, the review
workflow, links to every Week 4 report, and the [model card](week4/MODEL_CARD.md).

### Run Week 5

```bash
python -m pip install -r week5/requirements.txt -r week4/requirements-model.txt
make reproduce-week5 PYTHON=.venv/bin/python
python -m streamlit run week5/app.py
```

See [`week5/README.md`](week5/README.md) for the Week 4 vs Week 5 comparison,
uncertainty results, annotated examples, model weights, limitations, and links
to the Week 5 reports.

Streamlit normally opens the app automatically. Otherwise visit
<http://localhost:8501>. Stop the server with `Ctrl+C` before switching
between versions.

## Open in VS Code

From the cloned repository:

```bash
code .
```

If the `code` command is unavailable, open VS Code, choose **File → Open
Folder…**, and select the cloned `lucia-northern` folder.

In VS Code, run **Python: Select Interpreter** from the Command Palette and
choose the interpreter inside `.venv` before running tests or the apps.

Each week's folder has its own detailed README. Week 2 includes four small
CC0 sample X-rays, or a reviewer can upload a JPG, PNG, or TIFF image in the
app. No millimetre calibration is required because PBL is calculated as a
ratio.

## Repository history

- `main`: the current combined submission;
- `week1` tag: the original Week 1 submission snapshot;
- `week2`, `week3`, and `week4`: earlier development branches retained for the
  weekly history; and
- `week4-weights` release: the ten Week 4 model checkpoints and checksum
  manifest.

I developed this project as an educational measurement tool. The measurements
and tests do not establish clinical diagnostic accuracy.
