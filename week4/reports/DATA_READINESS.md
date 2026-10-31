# Week 4 data readiness

`python -m week4.reproduce` writes [`data_readiness.json`](data_readiness.json).

- **My own readings**: 15 teeth on one panoramic image, under three conditions
  and two rounds. Consolidated means and inter-round noise are in
  `data/week3_round_means.json`. One image is a single group, so these readings
  cannot be split into five folds; `reproduce --strict` still refuses, by
  design. They are used only as the human repeatability reference.
- **Model data**: 1,657 DenPAR teeth from official annotations, with a saved
  radiograph-level 5-fold split. See [DATASET.md](DATASET.md).
