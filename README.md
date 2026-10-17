# Periodontal Bone Loss Calculator

This repository contains both internship deliverables in separate folders so
they can be reviewed from one GitHub link.

| Version | Folder | What it does |
| --- | --- | --- |
| Week 1 | [`week1/`](week1/) | Calculates PBL from sliders for one tooth surface. |
| Week 2 | [`week2/`](week2/) | Places six landmarks on a real X-ray, reports mesial/distal PBL, stages from the worse surface, and records repeatability measurements. |

## Quick start

Python 3.10 or newer is required.

```bash
git clone https://github.com/luciala-glitch/pbl-calculator.git
cd pbl-calculator
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

Streamlit normally opens the app automatically. Otherwise visit
<http://localhost:8501>. Stop the server with `Ctrl+C` before switching
between versions.

## Open in VS Code

From the cloned repository:

```bash
code .
```

If the `code` command is unavailable, open VS Code, choose **File → Open
Folder…**, and select the cloned `pbl-calculator` folder.

In VS Code, run **Python: Select Interpreter** from the Command Palette and
choose the interpreter inside `.venv` before running tests or the apps.

Each week's folder has its own detailed README. Week 2 includes four small
CC0 sample X-rays, or a reviewer can upload a JPG, PNG, or TIFF image in the
app. No millimetre calibration is required because PBL is calculated as a
ratio.

## Repository history

- `main`: the current repository with both Week 1 and Week 2 folders;
- `week2`: the Week 2 development branch; and
- `week1` tag: the original Week 1 submission snapshot.

This project is an educational measurement tool and is not a diagnostic
device.
