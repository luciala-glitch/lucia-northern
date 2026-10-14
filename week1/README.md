# Periodontal Bone Loss Calculator

This small Python project calculates periodontal bone loss (PBL) from three 2D
points on one side of a tooth: the CEJ (or crown margin), bone crest, and root
tip. It uses Euclidean distance, so it also works for tilted teeth.

The bone crest must be on the root side of the CEJ and must not project beyond
the root tip. The calculator shows an error for either invalid arrangement.
Because the percentage uses Euclidean distance, placing the bone crest far away
from the tooth's long axis can make the result larger than expected.

## Formula

```text
PBL (%) = distance(CEJ, bone crest) / distance(CEJ, root tip) × 100
```

## Classification

- **Mild:** PBL below 15%
- **Moderate:** PBL from 15% (inclusive) to 33% (exclusive)
- **Severe:** PBL of 33% or higher

## Download and open

Clone the project and enter its folder:

```bash
git clone https://github.com/luciala-glitch/pbl-calculator.git
cd pbl-calculator
code .
```

If the `code` command is unavailable, open VS Code, choose **File → Open
Folder…**, and select the cloned `pbl-calculator` folder.

## Install

From this project folder, install the dependencies:

```bash
python -m pip install -r week1/requirements.txt
```

## Run the tests

```bash
python -m pytest -q week1
```

## Start the app

```bash
python -m streamlit run week1/app.py
```

Streamlit will open the app in a browser. If it does not open automatically,
visit `http://localhost:8501`.

Use the sidebar sliders to move each point. The PBL percentage,
classification, and tooth schematic update immediately.
