#!/usr/bin/env bash
# Train all ten checkpoints (Raw and CLAHE inputs x 5 folds) used by the reports.
set -euo pipefail
PYTHON="${PYTHON:-python}"
for condition in raw clahe; do
  for fold in 1 2 3 4 5; do
    if [ ! -f "week4/weights/${condition}_fold_${fold}.pt" ]; then
      "$PYTHON" -m week4.train --fold "$fold" --condition "$condition" --epochs 30 \
        > "week4/weights/logs/${condition}_fold_${fold}.log" 2>&1
    fi
  done
done
