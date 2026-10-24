# Completed collection check

Study: afb9efae0e0f4389907765ba6adc2cdd

All 90 saved readings pair across the same 15 registered teeth on kaggle_dental_xray_1.jpg. Each tooth has Raw, HE and CLAHE readings in rounds 1 and 2. There are 180 surface observations; these are not 180 independent teeth.

Integrity checks passed: six groups of 15; unique image/tooth/condition/round identities; no missing condition triplets; no unsaved landmark drafts; original-image bounds and exported metric/axis recomputation. JSON and CSV round trips passed. No saved observations were changed.

| Condition | R1 | R2 | Surface ICC(2,1) | Surface quadratic kappa | Bias R2−R1 (pp) | 95% agreement limits (pp) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| RAW | 15 | 15 | 0.722 | 0.563 | -0.261 | -10.761 to 10.238 |
| HE | 15 | 15 | 0.786 | 0.816 | -0.627 | -11.510 to 10.256 |
| CLAHE | 15 | 15 | 0.825 | 0.718 | +0.199 | -10.996 to 11.395 |

## Review flags

- RAW: tooth/surface 7 / distal, R2−R1 -12.59 pp.
- RAW: tooth/surface 9 / distal, R2−R1 -12.37 pp.
- HE: tooth/surface 7 / mesial, R2−R1 +10.71 pp.
- CLAHE: tooth/surface 14 / mesial, R2−R1 +13.96 pp.

Flags identify differences outside the calculated limits, not verified marking errors. Do not replace independent observations merely to improve agreement. Earlier visual review also identified ambiguous apex/CEJ placements requiring qualified anatomical review.

## Interpretation limits

Successful pairing does not establish anatomical accuracy. These data come from one image, 15 teeth and one reader. Paired surfaces share a tooth and apex; pooled surface statistics and independence-based intervals are descriptive and cannot establish clinical performance or that one enhancement is superior. Agreement limits remain approximately ±11 percentage points despite small mean shifts. Study creation and backup snapshots place Round 1 between 04:26:07 and 04:49:30 UTC on 2026-10-23; Round 2 saves are 17:47:18–18:00:09 UTC. The interval was approximately 13 hours on the same date, not one day. Exact per-reading Round 1 timestamps are unavailable. An earlier 15-reading RAW session on the same registered locations was archived after a user-requested workflow restart and excluded from analysis. This earlier exposure, the short interval and fixed RAW → HE → CLAHE order could inflate agreement through recall or practice. Round 2 tooth order matches the seeded shuffle for all three conditions; Round 1 order is unverified. See the [history evidence](protocol_history/history_evidence.json).

## Preserved collection

The current [JSON](exports/measurements.json), [CSV](exports/measurements.csv) and [collection manifest](exports/collection_manifest.json) are bundled here. The [excluded earlier RAW readings](protocol_history/excluded_raw_round1.json) are preserved separately for transparency and never pooled. The complete local SQLite recovery snapshot remains in ignored local storage; it is not a repository deliverable. Original measurements were preserved.
