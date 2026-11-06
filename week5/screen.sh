#!/usr/bin/env bash
# Week 5 hyper-parameter screen: every configuration is trained on the training
# radiographs of development fold 1 and scored only on fold 1's held-out
# radiographs (python -m week5.experiments). Two runs share the GPU at a time.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-.venv/bin/python}
run() {
  local config=$1
  local out=week5/weights/screen/${config}_raw_fold_1.pt
  [[ -f $out ]] && return 0
  "$PYTHON" -m week5.train --config "$config" --fold 1 --output "$out" > "week5/weights/logs/screen_${config}.log" 2>&1
}
run week4 & run lr_1e-3 & wait
run strong_aug & run coord_0.1 & wait
run lr_2.5e-4 & run sigma_2 & wait
