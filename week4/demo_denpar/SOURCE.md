# DenPAR demo subset

This folder contains two disjoint subsets of 20 unmodified radiographs each,
plus their matching official keypoint and bone-level JSON:

- `development/`: from DenPAR's official **Training** partition, with 90 tooth
  boxes. These images can be annotated twice and used in development folds.
- `external_test/`: from DenPAR's official **Testing** partition, with 92 tooth
  boxes. These are for final external evaluation and must never be trained on.

- Dataset: *DenPAR: Annotated Intra-Oral Periapical Radiographs Dataset for
  Machine Learning*, version 3.
- Authors: Sumudu Rasnayaka, Dhanushka Leuke Bandara, Amali Jayasundara,
  Ruwan Jayasinghe, Chathura Wimalasiri, Piumal Rathnayake, Shamod Wijerathne,
  Roshan Ragel, Vajira Thambawita, and Isuru Nawinne.
- Dataset DOI: <https://doi.org/10.5281/zenodo.16645076>
- Article DOI: <https://doi.org/10.1038/s41597-025-05906-9>
- License: Creative Commons Attribution 4.0 International (CC BY 4.0), as
  stated in the dataset article's Data Records section.
- Downloaded: 2026-10-27.

No patient identifiers are present in these subsets. Image filenames are the
original DenPAR identifiers. The images and annotations were not modified;
folder placement is the only change from the source archive.

The official CEJ/apex JSON is not in this project's five-keypoint schema: CEJ
and apex points are listed per image, and bone levels are polylines.
`week4/denpar.py` associates them to individual teeth using the tooth-wise masks
in the full archive (see `week4/reports/DATASET.md`). `characteristics.json`
copies the arch/site/visible-teeth rows of DenPAR's characteristics sheet for
these 40 images, so the App can suggest the orientation.
