#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
python=.venv/bin/python
if [[ ! -x "$python" ]]; then
    python3 -m venv .venv
fi
if ! "$python" -c 'import streamlit, reportlab, PIL, matplotlib; from week7.cases import build_demo_cases' 2>/dev/null; then
    "$python" -m pip install -r week7/requirements.txt
fi
exec "$python" -m streamlit run week7/app.py --server.address 127.0.0.1 --server.headless false --browser.gatherUsageStats false
