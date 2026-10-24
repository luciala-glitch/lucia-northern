# Independent review response

I checked these review comments on 2026-10-23 against the local study database,
backup snapshots, exported measurements and recomputed results. I kept the 90
included readings unchanged. The table explains what I corrected and what still
limits the findings.

| Review item | Finding and action |
| --- | --- |
| B1: interval | Confirmed. Study creation is 04:26:07 UTC; complete R1 backup is 04:49:30; R2 saves run 17:47:18–18:00:09 on 2026-10-23. The conservative bounds are 12.96–13.57 hours. Replaced the one-day account in the report, generator and collection check; added recall/practice limitations. Backups bound completion, not individual click times. |
| B2: excluded RAW attempt | Confirmed: archived study 317d1b49 contains 15 RAW readings on identical registered locations. Disclosed the workflow restart, extra exposure and exclusion. The detailed reason was not captured in the structured log, so no anatomical or statistical rationale was invented. Archived input and audit history are preserved separately under protocol_history/. Direction clarified: final RAW R1 minus archived RAW is +3.85 pp (SD 2.29); the reverse subtraction is −3.85 pp. Neither archived readings nor their derived differences enter the main analyses. |
| B3: publication | I prepared the GitHub submission separately after finishing the report corrections; see [my submission links](SUBMISSION.md). Removed the public README link to the local Claude handoff and ignored that machine-specific file. Replaced the collection-check link into ignored storage with bundled relative export links. The submission links record the current branch and PR status. |
| H1: order/recall confounding | Confirmed. Added fixed RAW → HE → CLAHE condition order, timing table and the earlier RAW exposure. All three R2 save orders match the deterministic seeded shuffle; R1 tooth order is unverified. The first-to-last R2 save span is 12.85 min; group spans are 126, 143, 129 s. Median inter-save intervals are 9, 9, 8 s, not direct tooth-marking durations. No causal enhancement superiority is claimed. |
| H2: per-case sensitivity | Added 200 individual signed ±5/±10 px trials for the five ranked tooth/condition cases in case_sensitivity.csv and eight-row summaries per case. Updated every case title with both rounds' mesial/distal PBL. Added HE T7's separate flagged-condition overlay. |
| H3: stage context | Confirmed no whole-tooth Stage I and 4/15, 1/15, 3/15 tooth disagreements. Added the full three-class tooth confusion matrices. More precisely, the 11 near-threshold entries are repeated surface observations, representing eight distinct tooth surfaces, not 11 distinct anatomical surfaces. Added the 42/90 software review-flag count. |
| H4: clustered checks | Tooth PBLmax ICC independently confirmed as 0.689, 0.742, 0.792. Added tooth-level bias/LoA/BA plots, within-tooth difference correlations (0.444, 0.561, 0.614), and 10,000 tooth-cluster bootstrap draws with a fixed seed. Surface-ICC percentile intervals are approximately 0.489–0.819, 0.595–0.882, 0.640–0.878. These are pooled-surface clustered intervals, not tooth-PBLmax intervals. A lower upper endpoint alone does not establish that the nominal interval is too narrow; methods/small-sample variability can change both bounds and widths. |
| M1: gradients | Confirmed off-centre full-window peaks. Retained the full-window control, added ±3 px peaks and offset/boundary diagnostics, and moved the profile figure back to the gradient results. Explicitly stated that unnormalized gray-level stretching/noise can increase gradients without improving localization. No edge-accuracy claim is made. |
| M2: synthetic title | Corrected synthetic_cases to show mesial PBL change as well as worse-side change. The restoration example now explains that the affected side changes even when the worse-side maximum remains unchanged. |
| M3: stale prose/evidence | Bound this study-specific manuscript to the exact empirical input SHA-256; added checks for named LoA flags, rankings, rounded SD and largest landmark RMS. Changed verification date, frontend count and branch percentage to evidence-derived fields. Saved logs/source/protocol hashes are checked before report generation, which does not itself rerun tests. run_checks.py refreshes logs and the manifest through actual check execution. |
| M4: systematic/random distinction | Added tooth-cluster intervals for mean surface bias; all include zero. The report says there is no clear evidence of overall directional PBL drift in this sample, with mainly heterogeneous per-tooth residual variation. It does not claim absence of systematic error or proof of random error, and retains the CLAHE apex parallel drift (~5.5 px) as a review concern. A naive surface-level paired t test would ignore clustering, so its nonsignificance is not used as proof. |
| Other | Explained variance = RMSD²/2 for this two-round coordinate measure and the interpretation of “tile grid = 88” as 8 × 8. Retained the limits on true clinical case categories and crown-point auditability. |

## What remains open

1. The current GitHub branch and PR status are recorded in [SUBMISSION.md](SUBMISSION.md).
2. Existing radiographic screening examples have now been added in the
   [case appendix](radiographic_cases/RADIOGRAPHIC_CASES.md), using saved points:
   legacy img10-T3 for restoration/CEJ, current T9 for projected root-outline
   overlap, and current T7 for tilt. The assignment does not explicitly demand
   expert certification. The labels remain visual interpretations, and the
   legacy six-point restoration example is not a new five-point study reading.
3. The fixed five-landmark export cannot verify a measured root-to-crown ratio.
4. The short interval, fixed condition order and prior RAW exposure cannot be
   repaired retrospectively by rewriting the report. Stronger claims require a
   prospectively planned collection; the current descriptive dataset is retained.

See [the revised report](WEEK3_COLLECTED_REPORT.md) and
[protocol audit evidence](protocol_history/history_evidence.json). No original
observations were removed or changed to improve agreement.
