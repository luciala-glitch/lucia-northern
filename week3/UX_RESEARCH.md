# Measurement workflow: design rationale and verification

Reviewed 22 October 2026. I used these sources to guide the workflow changes; referencing them
is not medical-device approval or clinical validation.

## Sources and decisions

- [FDA: Applying Human Factors and Usability Engineering to Medical Devices](https://www.fda.gov/media/80481/download).
  The guidance describes identifying use-related problems and reducing them
  through interface design. The problems I ran into were forgotten tooth identity,
  uncertainty about whether a click was recorded, duplicate saves, and restart
  anxiety. I used these problems to guide changes to the workflow.
- [OHIF: Measurement Panel](https://docs.ohif.org/user-guide/viewer/measurement-panel/).
  OHIF distinguishes temporary and tracked measurements, supports measurement
  labels, navigation to a tracked measurement, and exports. I adapted these
  concepts as draft/ready/recorded states, fixed tooth labels and location boxes,
  Find selected tooth, a completion checklist, and exports.
- [OHIF: Measurement Tracking](https://docs.ohif.org/user-guide/viewer/measurement-tracking/).
  Tracking status and locking helped me add a visible recorded state and protection
  against writing the same tooth/condition/round again.

## Implemented workflow

New sessions use routine measurement with progress based on registered teeth.
Optional research settings add an adjustable target, conditions and repeated
rounds. Existing sessions retain their original plan. Configuration changes do
not delete data, and targets never cap tooth registration.

Register each tooth once on a raw overview, then independently mark each
condition/round. A registered tooth selects its own image, so repeating a study
ID on a different image is blocked. Locations are manual reminders, not automated
tooth recognition. Nearby-location checks are a heuristic and cannot prove that
15 registered IDs correspond to 15 distinct physical teeth.

A persistent completion matrix shows exactly what remains. Blind mode hides
results without hiding task completion. Current drafts are restored only within
their tooth/condition/round. Existing-reading points are not prefilled in another
reading. Record tooth requires valid geometry and a confirmed tooth identity;
geometry validation does not establish anatomical validity.

Local SQLite transactions and a unique study/tooth/condition/round key prevent
concurrent duplicate inserts. Filename/content collisions are rejected. Drafts,
source images and tooth locations survive browser refresh and server restart.
Start over uses an explicit second step and archives instead of deleting.
Archived studies can be resumed. A stale session cannot write to an archived
study. Imported legacy coordinates remain marked unconfirmed.

## Verification

- The current saved checks include 219 passing project Python tests and 142
  Week 3 tests, with 100% engine branch coverage. The current logs and coverage
  are in `reports/collected_study/`; earlier screenshots below describe the
  development checks rather than the final measurement results.
- 14 Node canvas tests passed, including numbered locator overlays, centring the
  selected tooth, locking recorded teeth, pan/zoom and original-pixel coordinates.
- Isolated real-browser flow: register → locate → five test clicks → refresh →
  recover draft → record → verify locked state → archive → resume old study.
  The test used a separate database and was not added to the user's study.
- Upgrade migration: all 13 existing user records compared exactly with the
  independent pre-upgrade JSON backup before archiving them for the fresh study.

These are software checks and a developer walkthrough. Representative-user
usability testing and expert landmark review have not been completed. JSON/CSV
exports preserve the assignment schema; the local database additionally retains
images, tooth locations, drafts and archived studies. Moving only an exported
measurement JSON to a different computer does not carry the whole study map.

## Save and orientation follow-up

The selected tooth now retains a faint number offset from its registered crown
position, without a circle or a T prefix. Other location labels remain optional. A
selection change centres the new tooth; saving the same tooth does not recenter.
Saving uses a callback inside one persistent workspace fragment, retaining the
image and its current markers. The save button remains in a fixed slot. Exports
and completion counts are refreshed inside the same workspace. Its outer layout
reserves space while Streamlit reconciles updates, with browser scroll anchoring
disabled in the main pane.

An isolated native-mouse browser check measured page scroll at 324 pixels both
before and after Record tooth. The image zoom and pan remained in place. The
synthetic test records were kept outside the user's database. This confirms the
observed browser flow; it is not a timing benchmark across all browsers.

## Navigation and framing follow-up

There is one Next tooth button beside the image, directly below Record tooth.
It requires saving the current tooth first. Duplicate Next controls above and
below the image were removed. The larger checklist
navigation remains available for deliberate review or draft switching.
Automatic framing now covers about 55% of original-image height, centred on the
registered crown reminder, instead of a fixed 200% scale. This provides generous
vertical margin on the bundled panoramic image. It is a framing heuristic, not
automatic tooth-boundary detection; zoom and pan remain adjustable.

## Midline, mesial/distal guidance and literature review (23 October 2026)

**Observed problem.** The saved-landmark review found mesial/distal labels reversed
for teeth on one side of the arch: readers used a fixed image direction, but
mesial means *toward the dental midline*, so the correct image side flips at the
midline. A non-dentist reader cannot be expected to remember this per tooth.

**Implemented.**
- Each image can have a confirmed dental midline. On wide (panoramic) films the app
  suggests one from left–right mirror symmetry (`week3/orientation.py`); on the
  four bundled samples the suggestion fell between the central incisors. It is a
  suggestion only: the reader confirms or edits it, and periapicals/bitewings
  record the midline as beyond the left or right edge instead.
- Landmark prompts state the image side, e.g. "Mesial CEJ — side facing the
  midline (image right →)". A non-blocking warning appears when a mesial point
  lies on the distal side of its partner; tilted or rotated teeth may fail it
  legitimately, so it never blocks recording.
- The midline does not suggest any landmark position, so it does not anchor the
  measured coordinates. The midline is optional: without it the app measures
  normally and only the side hints are off. **Protocol note:** Round 1 of the current study was
  collected before these prompts existed; report the change if Round 2 uses them.
- Records now store a UTC save time (`created`, additive column; earlier records
  stay NULL rather than being guessed). Round 2 shows the time since Round 1 of
  the same condition. Database connections are now always closed.

**Why the app does not predict landmarks or the tooth axis.** Published systems
remain weakest exactly where this tool needs precision: apex localisation (apex
recall 62%, Alberta 2024; apex hardest landmark, Danks 2021) and early Stage I/II
loss (Stage-I F1 = 0, Alberta 2024; 68% stage agreement, mostly II/III confusion,
Danks 2021). AI suggestions also anchor readers: wrong suggestions cut correct
ratings from ~80% to 20–46% even for experienced radiologists (Dratsch 2023,
Radiology), and dental caries AI raised false positives (Mertens 2021; Devlin
2021). Showing a predicted axis or points during a repeatability round would
partly measure the AI's consistency instead of the reader's. The axis is already
defined geometrically by the reader's own clicks (CEJ midpoint → apex), as in the
literature (Chang 2020 uses mask moments for an independent axis). Any future
model belongs in a separate, randomised assisted-versus-unassisted arm, hidden in
blinded rounds. Available landmark data are non-commercial (Banks 2025 keypoints,
CC BY-NC-SA, on request; DENTEX licence inconsistent between sources).

**Clinical scope reminders.** RBL staging uses the worst site and % of root length;
the 15%/33% cut-offs separate I, II and III/IV, and III vs IV needs clinical
information (tooth loss, complexity), so the tool correctly stops at "III/IV".
Paralleling periapicals are the reference view; panoramics have non-uniform
magnification. A single shared apex simplifies multi-rooted molars. Conventions
differ on subtracting a ~1.5–2 mm normal CEJ–crest distance; this tool does not.

**Implemented after review (23 October 2026).**
- *Amend with reason:* a recorded reading can be reopened with a reason of at
  least 5 characters. The original record, its save time, the reason and the
  reopen time move to an amendment log (exportable as `amendments.json`); the
  tooth is re-marked from scratch with no prefilled points, so the old clicks
  cannot anchor the new ones. Exports contain only current readings.
- *Reading order:* research readings present teeth in a reproducible shuffled
  order per study/condition/round, so sequence does not cue recall. Routine mode
  keeps numeric order. Round 2 save order was verified against the seeded
  shuffle for all three conditions. Round 1 tooth order could not be verified
  from the available saved records.
- *ICC 95% CI:* McGraw & Wong interval for ICC(A,1) with a Satterthwaite df
  approximation, interpreted with Koo & Li bands. F quantiles are computed in
  `statistics.py` (checked against table values); simulated coverage ≈ 95%.
  On the legacy data: ICC 0.797, 95% CI 0.559–0.914 (moderate to excellent),
  so the evidence does not yet establish "good" reliability.

**Still recommended, not implemented.**
1. Per-landmark "cannot determine" with a reason, reported as exclusions
   (GRRAS). Add it for the next study, not mid-study, so rounds stay comparable.
2. Drag-to-adjust a placed point and a magnifier.
3. Show saved landmarks when reviewing a recorded tooth outside blind mode.
4. Plan sample size with Walter 1998 or Bonett 2002; report against GRRAS; treat
   surfaces of one tooth as clustered when reporting intervals.

Sources: Tonetti, Greenwell & Kornman 2018 (J Periodontol 89:S159); AAP "Three
Steps" sheet; Danks 2021 (PMC8260405); Chang 2020 (PMC7200807); Alberta 2024
(PMC11797779); Banks 2025 (arXiv 2503.13477, Zenodo 17272200); Dratsch 2023
(Radiology); Mertens 2021 (J Dent 115:103849); Devlin 2021 (PMC8536492);
Schwendicke 2021 AI-in-dental-research checklist; Kottner 2011 GRRAS; Koo & Li 2016
(PMC4913118); CVAT skeleton visibility flags.
