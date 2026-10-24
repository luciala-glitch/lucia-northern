# Raw Round 2 preliminary quality check

Current study: afb9efae0e0f4389907765ba6adc2cdd. Total: 60/90 saved readings.
Raw R1/R2, HE R1 and CLAHE R1 each have 15 records. HE R2 and CLAHE R2 remain empty.

## Data pairing and validation

- All 15 Raw Round-2 tooth IDs match the same image IDs as Raw Round 1.
- No duplicate identities, out-of-image coordinates, unsaved drafts, schema
  failures or recomputed-metric mismatches were found.
- Raw R2 mesial/distal CEJ order matches the reviewed image-side convention.
  This checks orientation conventions, not precise anatomical locations.

## Visual screening priorities

Paired same-scale Raw overlays were inspected for teeth 7, 9, 12 and 11.

- Tooth 9 apex: 27.89 px displacement. Confirm that both readings identify the
  same actual root tip rather than a nearby overlapping image boundary.
- Tooth 7 apex: 23.71 px displacement; distal crest also shifts 15.81 px. This
  markedly tilted tooth remains anatomically ambiguous on the available image.
- Tooth 12 apex: 20.00 px displacement; confirm the terminal root boundary.
- Tooth 11 distal CEJ: 12.00 px displacement; review cervical landmark definition.

Displacement magnitude is not an accuracy score or a validated rejection rule.
The overlays cannot certify exact anatomical points. There is no basis to redo
all 15 readings merely to improve agreement. Preserve the independent readings;
complete the remaining blind HE/CLAHE Round-2 readings before a full retrospective
review. Any confirmed annotation error should be documented and retained in an
amendment history, without disguising revised measurements as original blind
readings. No coordinates were modified during this check.

The paired-coordinate overlay is stored as raw_round2_priority_review.png; defer
side-by-side comparison until collection is complete to reduce recall cues.
