#!/usr/bin/env bash
# Re-train the configuration selected by the fold-1 screen on all five folds,
# Raw and CLAHE (fold-1 Raw is reused from the screen). Two runs share the GPU.
#   CONFIG=strong_aug ./week5/train_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-.venv/bin/python}
CONFIG=${CONFIG:?set CONFIG to the selected configuration name}
mkdir -p week5/weights/logs
run() {
  local condition=$1 fold=$2
  local out=week5/weights/${CONFIG}_${condition}_fold_${fold}.pt
  [[ -f $out || -f week5/weights/screen/${CONFIG}_${condition}_fold_${fold}.pt ]] && return 0
  "$PYTHON" -m week5.train --config "$CONFIG" --condition "$condition" --fold "$fold" --output "$out" \
    > "week5/weights/logs/${CONFIG}_${condition}_fold_${fold}.log" 2>&1
}
jobs=()
for condition in raw clahe; do
  for fold in 1 2 3 4 5; do
    jobs+=("$condition $fold")
  done
done
for ((i = 0; i < ${#jobs[@]}; i += 2)); do
  run ${jobs[i]} &
  if (( i + 1 < ${#jobs[@]} )); then run ${jobs[i+1]} & fi
  wait
done
