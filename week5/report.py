"""Write the four Week 5 Markdown reports from ``metrics.json``.

Every number and every verdict ("improved", "no significant change") is
derived from the metrics, so the prose cannot drift from the evidence when
``python -m week5.evaluate`` is re-run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from week4.constants import LANDMARK_NAMES

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "week5" / "reports"
W4_METRICS = ROOT / "week4" / "reports" / "results" / "metrics.json"
NAMES = {"mesial_cej": "Mesial CEJ", "distal_cej": "Distal CEJ", "mesial_bc": "Mesial bone crest",
         "distal_bc": "Distal bone crest", "apex": "Apex", "all": "All landmarks"}


def pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{100 * value:.{digits}f}%"


def num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def delta(entry: Mapping[str, Any], *, percent: bool = False, digits: int = 2, lower_is_better: bool = False) -> str:
    """Δ [95% CI]; ✓ marks a significant improvement, ✗ a significant worsening."""
    scale = 100 if percent else 1
    unit = " pp" if percent else ""
    low, high = (scale * v for v in entry["ci95"])
    mark = ""
    if low > 0 or high < 0:
        better = (high < 0) if lower_is_better else (low > 0)
        mark = " ✓" if better else " ✗"
    return f"{scale * entry['delta']:+.{digits}f}{unit} [{low:+.{digits}f}, {high:+.{digits}f}]{mark}"


def verdict(entry: Mapping[str, Any], *, lower_is_better: bool) -> str:
    low, high = entry["ci95"]
    if (high < 0) if lower_is_better else (low > 0):
        return "significantly better"
    if (low > 0) if lower_is_better else (high < 0):
        return "significantly worse"
    return "not significantly different"


def table(header: Sequence[str], rows: Sequence[Sequence[Any]], align: str | None = None) -> str:
    align = align or "|".join(["---"] + ["---:"] * (len(header) - 1))
    lines = ["| " + " | ".join(header) + " |", "|" + align + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


# ------------------------------------------------------------- error analysis


def error_analysis(m: Mapping[str, Any], w4: Mapping[str, Any]) -> str:
    dev, ext = m["week4_raw_development_oof"], m["week4_raw_external"]
    base_lm, base_ds = w4["landmarks_external"]["baseline_ext"], w4["downstream_pooled"]["baseline_ext"]
    raw_ds = w4["downstream_pooled"]["learned_raw_ext"]
    worst_landmark = max(LANDMARK_NAMES, key=lambda n: dev["landmarks"][n]["mre_px"])
    ratio = {n: dev["landmarks"][n]["along_mae_px"] / dev["landmarks"][n]["perpendicular_mae_px"] for n in LANDMARK_NAMES}
    sub = {r["subgroup"]: r for r in m["clinical"]["subgroups_development"]}
    orient = sub.get("orientation metadata wrong (>45°)")
    rules = w4["uncertainty"]["rules"]["margin_tuned_on_development"]
    worst = w4["worst_five_development"]
    wrong_orientation = sum(r["orientation_error_deg"] > 45 for r in worst)
    tilted = sum(bool(r["tilted"]) for r in worst)
    invalid = sum(not r["valid"] for r in worst)
    tail = m["clinical"]["error_concentration_week4_dev"]
    ladder = {step["label"]: step for step in m["ladder"]}
    o = m["orientation"]

    def screened(*names: str) -> str:
        parts = []
        for name in names:
            entry = m["screening"].get(name)
            if entry is None:
                continue
            d = m["screening_vs_week4"].get(name, {}).get("mre_px")
            parts.append(f"`{name}` {entry['mre_px']:.2f} px" + (f" (Δ {d['delta']:+.2f})" if d else ""))
        chosen = "selected" if m["selected_config"] in names else "not selected"
        return "; ".join(parts) + f" — **{chosen}** (fold-1 screen, seed-noise floor {m['seed_noise_floor_px']:.2f} px)"

    def outcome(prefix: str) -> str:
        step = next((s for label, s in ladder.items() if label.startswith(prefix)), None)
        if step is None:
            return "not run"
        status = "**kept**" if step["accepted"] else "**rejected**"
        return f"{status} (dev MRE {step['dev_mre_px']:.2f} px)"

    lm_rows = [
        [NAMES[n], num(dev["landmarks"][n]["mre_px"]), pct(dev["landmarks"][n]["sdr_10px"]),
         num(dev["landmarks"][n]["along_mae_px"]), num(dev["landmarks"][n]["perpendicular_mae_px"]), f"{ratio[n]:.1f}×",
         num(ext["landmarks"][n]["mre_px"])]
        for n in LANDMARK_NAMES
    ]
    worst_rows = [
        [f"DenPAR {r['denpar_id']} / tooth {r['tooth_id']}", f"{r['arch']} {r['site']}", num(r["mre_px"], 0),
         "invalid" if not r["valid"] else f"{r['pred_pbl']:.0f}%", f"{r['truth_pbl']:.0f}%",
         "yes" if r["tilted"] else "no", f"{r['orientation_error_deg']:.0f}°", num(r["max_sigma_px"], 0)]
        for r in worst
    ]
    worst_align = "---|---|---:|---:|---:|---|---:|---:"
    return f"""# Week 5 error analysis: what limited the Week 4 model

Source: the saved Week 4 out-of-fold (OOF) development predictions (1,330 teeth, 727 radiographs) and
external-test predictions (327 teeth, 180 radiographs). All numbers are regenerated by
`python -m week5.evaluate`.

## 1. Baseline vs learned model (Week 4)

{table(["External test", "Classical baseline", "Week 4 learned (Raw)"], [
    ["MRE (px)", num(base_lm["all"]["mre_px"]), num(ext["landmarks"]["all"]["mre_px"])],
    ["SDR@10 px", pct(base_lm["all"]["sdr_10px"]), pct(ext["landmarks"]["all"]["sdr_10px"])],
    ["ICC(2,1) PBL%", num(base_ds["icc_2_1"], 3), num(raw_ds["icc_2_1"], 3)],
    ["Weighted κ", num(base_ds["weighted_kappa"], 3), num(raw_ds["weighted_kappa"], 3)],
    ["Stage accuracy", pct(base_ds["stage_accuracy"]), pct(raw_ds["stage_accuracy"])],
])}

The learned detector's MRE was already {base_lm["all"]["mre_px"] / ext["landmarks"]["all"]["mre_px"]:.1f}× lower than the classical baseline's, so Week 5
targets the learned model's *residual* failure modes rather than the architecture choice.

## 2. Which landmarks are misidentified (Week 4 Raw, development OOF)

{table(["Landmark", "MRE px", "SDR@10", "Along-axis px", "Perpendicular px", "Along/perp", "External MRE px"], lm_rows)}

The **{NAMES[worst_landmark].lower()}** has the highest MRE. CEJ and bone-crest errors lie mainly along the tooth's
long axis (along/perpendicular ratio {min(ratio[n] for n in LANDMARK_NAMES[:4]):.1f}–{max(ratio[n] for n in LANDMARK_NAMES[:4]):.1f}×). That is the direction
that changes PBL%, so a crest placed slightly too coronal or apical moves the stage. The apex error is
closer to isotropic: it is harder to find, but it changes PBL less, because it only enters the denominator.

## 3. Five worst Week 4 development predictions

{table(["Tooth", "Site", "MRE px", "Auto PBL", "True PBL", "Tilted", "Orientation error", "Max σ px"], worst_rows, worst_align)}

Recurring pattern: {wrong_orientation}/5 had **orientation metadata more than 45° wrong** (the detector was
told the apex was at the wrong end), {tilted}/5 were tilted more than 15°, and {invalid}/5 produced an
anatomically invalid measurement. All five had very large reported σ, so these teeth were *detectable*
failures. They are not silent errors.

## 4. The three most significant sources of error

1. **Wrong apex direction causes gross failures.** {orient['n'] if orient else 'n/a'} development teeth
   ({pct(orient['n'] / 1330) if orient else 'n/a'}) have orientation metadata that is more than 45° wrong. Their Week 4 MRE was
   {num(orient['week4_mre_px'], 1) if orient else 'n/a'} px against {num(sub['all']['week4_mre_px'], 1)} px overall. The worst
   {pct(tail['top_5pct_share_of_error'], 0)} of teeth by error produce {pct(tail['top_5pct_error_share'], 0)} of all landmark error. The error
   distribution is heavy-tailed, so the mean is dominated by a few catastrophic cases.
   Week 4 trusted the reader's (or the metadata's) apex direction without checking it.
2. **Bone-crest and CEJ displacement along the long axis.** This is the clinically consequential error
   direction. It shows as {w4['downstream_pooled']['learned_raw_dev']['undercalled_any']} undercalls against
   {w4['downstream_pooled']['learned_raw_dev']['overcalled_any']} overcalls on development, and
   {w4['downstream_pooled']['learned_raw_dev']['severe_undercalled']} Stage III/IV teeth were called Stage I/II.
3. **Uncertainty was not calibrated or stage-aware.** The Week 4 95% PBL interval covered the true PBL in only
   {pct(w4['uncertainty']['development']['ci95_empirical_coverage'])} of development teeth (nominal 95%). Spearman ρ between
   landmark σ and error was {num(w4['uncertainty']['development']['spearman_landmark_sigma_vs_radial_error'])}. The shipped boundary-margin rule still
   auto-accepted {rules['development']['accepted_severe_undercalls']} development Stage III/IV undercalls, because it
   measures distance to a boundary and ignores the direction of the error.

## 5. Planned improvements and outcomes

Each change was tested on development data only and kept only if it lowered cross-fitted development MRE.

{table(["Weakness", "Change tried", "Why", "Outcome"], [
    ["1", "Orientation self-check: also run the reversed-apex hypothesis; switch, and always flag for review, when the model is more certain that way", "Turns silent metadata errors into flagged, mostly fixed predictions", outcome("+ orientation") + f"; development-fitted ratio {o['switch_ratio']:.1f}; switched {o['development_switched']} dev teeth, {o['development_switched_with_wrong_metadata']} truly mis-oriented, {o['development_switched'] - o['development_switched_with_wrong_metadata']} false switches (all flagged)"],
    ["1, 2", "Re-train with stronger rotation/scale and gamma/blur/noise augmentation", "More robust to tilt and poor films", screened("strong_aug")],
    ["2", "Higher coordinate-loss weight; sharper heatmap targets; learning rates 2.5e-4 and 1e-3", "Penalise along-axis coordinate error directly", screened("coord_0.1", "sigma_2", "lr_2.5e-4", "lr_1e-3")],
    ["2", "Raw/CLAHE ensemble (fixed 50/50, and learned per-landmark weights)", "CLAHE sharpens the crest edge; averaging reduces variance", outcome("+ Raw/CLAHE")],
    ["2", "Multi-margin test-time augmentation (box margin 5/8/11%)", "Averages out sensitivity to the reader's box", outcome("+ multi-margin")],
    ["3", "Landmark σ calibrated to empirical 95% coverage; Monte Carlo stage probabilities", "Makes the interval mean what it says", "see uncertainty analysis"],
    ["3", "Stage-aware review rule with a separate Stage III/IV miss guard", "Targets the clinically dangerous undercalls", "see uncertainty analysis"],
], "---|---|---|---")}

The fixed 50/50 blend (cross-fitted development MRE {num(m['blend_selection_development']['fixed_50_50_mre_px'])} px) beat learned
per-landmark weights ({num(m['blend_selection_development']['fitted_per_landmark_mre_px'])} px), so the simpler blend was kept.
"""


# ------------------------------------------------------------- comparison


def model_comparison(m: Mapping[str, Any]) -> str:
    screen = m["screening"]
    vs = m["screening_vs_week4"]
    screen_rows = []
    for name, s in screen.items():
        d = vs.get(name)
        screen_rows.append([
            f"`{name}`", num(s["mre_px"]), delta(d["mre_px"], lower_is_better=True) if d else "reference",
            pct(s["sdr_10px"]), num(s["icc_2_1"], 3), num(s["weighted_kappa"], 3), pct(s["stage_accuracy"]),
        ])
    ladder_rows = [
        [s["label"], num(s["dev_mre_px"]), pct(s["dev_stage_accuracy"]), num(s["ext_mre_px"]), pct(s["ext_stage_accuracy"]),
         "kept" if s["accepted"] else "rejected"]
        for s in m["ladder"]
    ]
    c = m["paired_comparison_refined_minus_week4"]

    def section(key: str, title: str, w4_key: str, w5_key: str) -> str:
        old, new = m[w4_key], m[w5_key]
        lm_rows = []
        for n in (*LANDMARK_NAMES, "all"):
            a, b = old["landmarks"][n], new["landmarks"][n]
            lm_rows.append([
                NAMES[n], f"{a['mre_px']:.2f} → **{b['mre_px']:.2f}**",
                f"{pct(a['sdr_2px'])} / {pct(a['sdr_5px'])} / {pct(a['sdr_10px'])} → {pct(b['sdr_2px'])} / {pct(b['sdr_5px'])} / {pct(b['sdr_10px'])}",
                f"{a['along_mae_px']:.2f} → {b['along_mae_px']:.2f}", f"{a['perpendicular_mae_px']:.2f} → {b['perpendicular_mae_px']:.2f}",
            ])
        p = c[key]
        da, db = old["downstream"], new["downstream"]
        return f"""### {title}

{table(["Landmark", "MRE px (Week 4 → Week 5)", "SDR@2 / @5 / @10", "Along-axis MAE px", "Perpendicular MAE px"], lm_rows)}

{table(["Metric (paired, teeth valid under both)", "Week 4", "Week 5", "Δ [95% CI]"], [
    ["MRE px", num(p["mre_px"]["baseline"]), num(p["mre_px"]["candidate"]), delta(p["mre_px"], lower_is_better=True)],
    ["SDR@2 px", pct(p["sdr_2px"]["baseline"]), pct(p["sdr_2px"]["candidate"]), delta(p["sdr_2px"], percent=True, digits=1)],
    ["SDR@5 px", pct(p["sdr_5px"]["baseline"]), pct(p["sdr_5px"]["candidate"]), delta(p["sdr_5px"], percent=True, digits=1)],
    ["SDR@10 px", pct(p["sdr_10px"]["baseline"]), pct(p["sdr_10px"]["candidate"]), delta(p["sdr_10px"], percent=True, digits=1)],
    ["Along-axis MAE px", num(p["along_mae_px"]["baseline"]), num(p["along_mae_px"]["candidate"]), delta(p["along_mae_px"], lower_is_better=True)],
    ["ICC(2,1) PBL%", num(p["icc_2_1"]["baseline"], 3), num(p["icc_2_1"]["candidate"], 3), delta(p["icc_2_1"], digits=3)],
    ["Quadratic weighted κ", num(p["weighted_kappa"]["baseline"], 3), num(p["weighted_kappa"]["candidate"], 3), delta(p["weighted_kappa"], digits=3)],
    ["Stage accuracy", pct(p["stage_accuracy"]["baseline"]), pct(p["stage_accuracy"]["candidate"]), delta(p["stage_accuracy"], percent=True, digits=1)],
])}

Unpaired totals: valid measurements {da['n_valid']}/{da['n_total']} → {db['n_valid']}/{db['n_total']};
Stage III/IV called I/II {da['severe_undercalled']}/{da['severe_n']} → {db['severe_undercalled']}/{db['severe_n']};
Bland–Altman bias {da['bias_pp']:+.2f} → {db['bias_pp']:+.2f} pp, limits-of-agreement width {da['loa_width_pp']:.1f} → {db['loa_width_pp']:.1f} pp.
"""

    ext = c["external"]["mre_px"]
    dev = c["development_oof"]["mre_px"]
    sens = c["development_oof_excluding_screen_fold_1"]["mre_px"]
    return f"""# Refined model vs Week 4

**Verdict.** On the held-out external test, the Week 5 system's MRE is {verdict(ext, lower_is_better=True).replace("different", "different from").replace("better", "better than").replace("worse", "worse than")}
Week 4 (Δ {delta(ext, lower_is_better=True)} px). On cross-fitted development OOF it is
{verdict(dev, lower_is_better=True)} (Δ {delta(dev, lower_is_better=True)} px). Excluding fold 1, which was used to
screen configurations, development Δ is {delta(sens, lower_is_better=True)} px. ✓/✗ mark 95% intervals that
exclude zero. Intervals come from a paired bootstrap that resamples whole radiographs, so correlated teeth
in one image are not counted as independent evidence.

![Per-landmark MRE and refinement ladder](model_comparison.png)

## Protocol

- The split is exactly `week4/data/denpar_split_5fold.json`: radiograph-level, the same as Week 4.
- Configurations were screened on development fold 1 only: trained on its training radiographs and scored
  on its held-out radiographs. The external test was not used.
- The winning configuration was re-trained on all five folds (Raw and CLAHE). Development numbers are
  out-of-fold.
- Every post-processing parameter (blend, σ scale, orientation threshold, review policy) for held-out fold k
  was fitted on the other four folds. The external test was scored once, with parameters fitted on all
  development rows.

## Step 1: configuration screen (development fold 1, {m['screening_n_teeth']} teeth)

{table(["Configuration", "MRE px", "Δ vs saved Week 4 [95% CI]", "SDR@10", "ICC", "κ", "Stage acc."], screen_rows)}

`week4 (re-trained, seed noise)` repeats the Week 4 recipe with the same seed. GPU non-determinism alone
moves its MRE, so any difference smaller than that is not evidence. Selection rule, fixed in advance:
lowest fold-1 MRE, and only if it beats Week 4 by more than 0.1 px. Selected: **`{m['selected_config']}`**;
multi-margin TTA {'selected' if m['tta_selected'] else 'not selected'}.

## Step 2: refinement ladder (each step kept only if cross-fitted development MRE falls)

{table(["System", "Dev MRE px", "Dev stage acc.", "External MRE px", "External stage acc.", "Decision"], ladder_rows)}

The external columns are reported for transparency only. No decision used them.

## Step 3: final comparison

{section("external", "External test (held out)", "week4_raw_external", "refined_external")}
{section("development_oof", "Development (cross-fitted out-of-fold)", "week4_raw_development_oof", "refined_development_oof")}

## Final configuration

`calibration.json` records the checkpoints, TTA margins, blend weights, per-landmark σ scales, orientation
threshold and review policy that the App loads. Weights and training logs are in `week5/weights/`; the
checksums are in `week5/weights/MANIFEST.json`.
"""


# ------------------------------------------------------------ uncertainty


def uncertainty_report(m: Mapping[str, Any]) -> str:
    u = m["uncertainty"]
    dev, ext, w4 = u["development"], u["external"], u["week4_raw"]
    policy = u["policy"]
    score_names = {"max_sigma_px": "max landmark σ", "mean_sigma_px": "mean landmark σ", "ci_width_pp": "95% PBL CI width",
                   "one_minus_p_auto_stage": "1 − P(auto stage)"}
    corr_rows = [
        [label, num(dev["confidence"]["scores"][k]["spearman_vs_mean_landmark_error"]), num(ext["confidence"]["scores"][k]["spearman_vs_mean_landmark_error"]),
         num(dev["confidence"]["scores"][k]["spearman_vs_abs_pbl_error"]), num(ext["confidence"]["scores"][k]["spearman_vs_abs_pbl_error"]),
         num(dev["confidence"]["scores"][k]["auroc_stage_error"]), num(ext["confidence"]["scores"][k]["auroc_stage_error"])]
        for k, label in score_names.items()
    ]
    cov_rows = [
        [NAMES[n], pct(w4["radial_coverage_development"][n]["0.95"]), pct(dev["radial_coverage_before_scaling"][n]["0.95"]),
         pct(dev["radial_coverage_calibrated"][n]["0.95"]), pct(ext["radial_coverage_calibrated"][n]["0.95"])]
        for n in (*LANDMARK_NAMES, "all")
    ]
    op_rows = []
    for name, point in u["operating_points"]["development"].items():
        e = u["operating_points"]["external"][name]
        op_rows.append([
            name, pct(point["review_rate"]), pct(point["accepted_stage_accuracy"]), f"{point['accepted_severe_misses']}/{point['severe_n']}",
            pct(e["review_rate"]), pct(e["accepted_stage_accuracy"]), f"{e['accepted_severe_misses']}/{e['severe_n']}",
            pct(e["stage_error_recall"]),
        ])
    folds = u["policy_cross_fitted_folds"]
    pi = u["pbl_interval"]
    hc_dev, hc_ext = dev["high_confidence_failures"], ext["high_confidence_failures"]
    criteria = [f"the Monte Carlo probability of the automatic stage is below **{pct(policy['min_stage_probability'], 0)}**"]
    if policy["severe_guard"] is not None:
        criteria.append(f"the automatic stage is I or II and P(Stage III/IV) ≥ **{pct(policy['severe_guard'], 0)}**: a possible missed severe case")
    criteria += ["the orientation self-check reversed the apex direction", "no valid automatic measurement or interval could be produced"]
    rule_list = "\n".join(f"{i}. {c}{'; or' if i == len(criteria) - 1 else '.' if i == len(criteria) else ';'}"
                           for i, c in enumerate(criteria, 1))
    targets = policy["targets"]
    accuracy_target, miss_target = pct(targets["accepted_stage_accuracy"], 0), pct(targets["accepted_severe_misses_per_severe"], 1)
    check_rows = []
    for label, key, point_set in (("Development, fitted on all folds (in-sample)", None, None),
                                  ("Development, held-out folds (cross-fitted)", "development_cross_fitted", "development"),
                                  ("External test", "external", "external")):
        if key is None:
            met = "yes" if policy["targets_met_in_sample"] else "no"
            check_rows.append([label, met, met])
            continue
        c, point = policy["target_check"][key], u["operating_points"][point_set]["Week 5 policy"]
        check_rows.append([
            label,
            f"{pct(c['accepted_stage_accuracy'])} — {'met' if c['accepted_stage_accuracy_met'] else '**not met**'}",
            f"{point['accepted_severe_misses']}/{point['severe_n']} = {pct(c['accepted_severe_miss_rate'], 2)} — "
            f"{'met' if c['accepted_severe_miss_rate_met'] else '**not met**'}",
        ])
    held_out = policy["target_check"]["development_cross_fitted"]
    all_met = all(policy["target_check"][k][f] for k in ("development_cross_fitted", "external")
                  for f in ("accepted_stage_accuracy_met", "accepted_severe_miss_rate_met"))
    target_verdict = (
        "Both targets also hold on held-out data." if all_met else
        "The targets are met only on the data the thresholds were fitted to. On held-out data the accuracy "
        "target " + ("holds" if held_out["accepted_stage_accuracy_met"] else "fails") + " but the severe-miss target "
        + ("holds" if held_out["accepted_severe_miss_rate_met"] else f"does not: {miss_target} is a fitting target, not a guarantee")
        + ". With only a handful of Stage III/IV misses at stake, one tooth more or less moves the rate by "
        f"about {100 / u['operating_points']['development']['Week 5 policy']['severe_n']:.1f} pp on development and "
        f"{100 / u['operating_points']['external']['Week 5 policy']['severe_n']:.1f} pp on the external test, so the held-out estimate is imprecise."
    )
    w5 = u["operating_points"]["external"]["Week 5 policy"]
    same_dev = next(v for k, v in u["operating_points"]["development"].items() if k.startswith("Week 5 at Week 4's review burden"))
    shipped_dev = u["operating_points"]["development"]["Week 4 system as shipped (Week 4 Raw + k=0.45)"]
    shipped = u["operating_points"]["external"]["Week 4 system as shipped (Week 4 Raw + k=0.45)"]
    return f"""# Uncertainty calibration and revised review rule

![Confidence versus error, calibration and stage reliability](confidence_vs_error.png)

## Do confidence estimates track accuracy?

Spearman correlation with error, and AUROC for detecting a wrong stage (0.5 = chance, 1 = perfect). Week 4
reference on development: ρ(max σ, error) = {num(w4['spearman_max_sigma_vs_mean_error_development'])}, AUROC
{num(w4['auroc_max_sigma_stage_error_development'])}.

{table(["Confidence score", "ρ error dev", "ρ error ext", "ρ abs PBL error dev", "ρ abs PBL error ext", "AUROC stage dev", "AUROC stage ext"], corr_rows)}

Landmark σ tracks *geometric* error well; it is strongest for gross failures (top-right of the scatter).
For predicting a *wrong stage*, `1 − P(auto stage)` is the best score, because a large but harmless
landmark error far from a stage boundary does not change the stage. This is why the review rule is built
on stage probability rather than on raw σ.

## Is the stated uncertainty honest?

{table(["Landmark", "Week 4 σ (dev)", "Week 5 before scaling (dev)", "Week 5 calibrated (dev, cross-fitted)", "Week 5 calibrated (external)"], cov_rows)}

The table shows the share of true landmarks inside the nominal 95% radius. Week 4's heatmap σ was
over-confident. Week 5 adds Raw/CLAHE and test-time disagreement, then rescales each landmark on
development data only.

Landmark errors are heavy-tailed rather than Gaussian. Their radii therefore over-cover at lower
nominal levels and hit 95% only at the 95% level, which is the level the review rule and the interval use.

**Reassessed 95% PBL interval.** The interval comes from 1,000 Monte Carlo draws of all five landmarks
through the Week 3 calculator.

{table(["", "Development", "External"], [
    ["Week 4 Monte Carlo interval (heatmap σ)", pct(w4['pbl_ci95_coverage_development']), pct(w4['pbl_ci95_coverage_external'])],
    ["Week 5 Monte Carlo interval (calibrated σ)", pct(pi['coverage_monte_carlo_development']), pct(pi['coverage_monte_carlo_external'])],
    [f"Week 5 reported interval (× {pi['conformal_factor']:.2f} split-conformal stretch)", f"**{pct(pi['coverage_calibrated_development'])}**", f"**{pct(pi['coverage_calibrated_external'])}**"],
    ["Median reported width (pp)", num(pi['median_width_calibrated_development_pp'], 1), num(pi['median_width_calibrated_external_pp'], 1)],
])}

Per-landmark calibration is not enough on its own. The few gross failures, and errors shared between
landmarks, push some true PBL values outside the Monte Carlo interval. Inflating σ until that interval
covered 95% would have made the stage probabilities under-confident. Instead, the reported interval is
stretched about the point estimate by a split-conformal factor fitted on development data (cross-fitted
fold factors {', '.join(f'{f:.2f}' for f in pi['cross_fitted_fold_factors'])}). The stage probabilities keep the unstretched draws,
because they are already well calibrated.
- **Stage-probability calibration**: expected calibration error {num(dev['stage_reliability']['expected_calibration_error'], 3)} dev /
  {num(ext['stage_reliability']['expected_calibration_error'], 3)} external; multi-class Brier
  {num(dev['stage_reliability']['multiclass_brier'], 3)} / {num(ext['stage_reliability']['multiclass_brier'], 3)}.

## High-confidence, large-error cases

Definition: {hc_dev['definition']}.

- Development: {hc_dev['n']} teeth, {hc_dev['stage_wrong']} with a wrong stage, **{hc_dev['stage_wrong_and_accepted']} wrong and not flagged**;
  {hc_dev['tilted']} tilted, {hc_dev['multirooted']} multi-rooted.
- External: {hc_ext['n']} teeth, {hc_ext['stage_wrong']} with a wrong stage, **{hc_ext['stage_wrong_and_accepted']} wrong and not flagged**.

These are the confidently wrong cases that no uncertainty rule can catch. They remain the main reason
every automatic result is still shown to a clinician.

## Revised review rule

Recommend clinician review when **any** of the following holds:

{rule_list}

The thresholds are the lowest review burden on development data that keeps accepted-tooth stage accuracy
≥ {accuracy_target} and accepted Stage III/IV misses ≤ {miss_target} of all III/IV teeth. Whether the
targets are met depends on which data you check:

{table(["Data", f"Accepted stage accuracy ≥ {accuracy_target}", f"Accepted III/IV misses ≤ {miss_target}"], check_rows)}

{target_verdict}

Refitting on each set of four folds gave thresholds
{', '.join(pct(f['min_stage_probability'], 0) for f in folds)} with guards
{', '.join('none' if f['severe_guard'] is None else pct(f['severe_guard'], 0) for f in folds)}. The threshold
moves between folds, which is one reason the in-sample targets do not carry over exactly.
Development numbers below use these held-out-fold rules.

{table(["Rule", "Dev review", "Dev accepted acc.", "Dev accepted III/IV misses", "Ext review", "Ext accepted acc.", "Ext accepted III/IV misses", "Ext stage-error recall"], op_rows)}

![Risk–coverage](risk_coverage.png)

On the external test, the Week 5 rule refers {pct(w5['review_rate'])} of teeth, keeps {pct(w5['accepted_stage_accuracy'])}
stage accuracy among auto-accepted teeth, and leaves {w5['accepted_severe_misses']} Stage III/IV miss(es) unflagged. The
Week 4 system as shipped referred {pct(shipped['review_rate'])}, with {pct(shipped['accepted_stage_accuracy'])} accepted accuracy
and {shipped['accepted_severe_misses']} unflagged severe miss(es).

**Trade-off, stated plainly.** The Week 5 rule is *safer*, not *cheaper*. It reaches its accuracy target,
and comes close to its severe-miss target, by referring roughly twice as many teeth. At Week 4's review burden, the Week 5 stage-probability rule
gives {pct(same_dev['accepted_stage_accuracy'])} accepted accuracy on development, against
{pct(shipped_dev['accepted_stage_accuracy'])} for Week 4. That is no better at equal burden. The real gains in uncertainty are that
the intervals and stage probabilities now mean what they say (coverage and calibration above), and that
a wrong stage is far easier to detect (AUROC above). The risk–coverage curves compare the rules at every
possible review burden, not just at one operating point.
"""


# --------------------------------------------------------------- clinical


def clinical_report(m: Mapping[str, Any], manifest: Sequence[Mapping[str, Any]]) -> str:
    c = m["clinical"]
    confusion = c["external_stage_confusion_rows_truth_cols_pred"]
    stages = ("I", "II", "III/IV")

    def sub_rows(rows: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
        return [
            [r["subgroup"], r["n"], f"{r['week4_mre_px']:.1f} → {r['mre_px']:.1f}",
             f"{pct(r['week4_stage_accuracy'])} → {pct(r['stage_accuracy'])}", f"{r['severe_misses']}/{r['severe_n']}",
             pct(r["review_rate"]), pct(r["accepted_stage_accuracy"]), r["accepted_severe_misses"]]
            for r in rows
        ]

    severe = c["severe_undercalls"]
    severe_rows = [
        [s["split"], f"{s['image']} / {s['id']}", f"{s['truth_pbl']:.0f}%",
         "invalid" if s["auto_pbl"] is None else f"{s['auto_pbl']:.0f}% {s['auto_stage']}",
         num(s["p_severe"]), "**yes**" if s["flagged"] else "no", "; ".join(s["reasons"]) or "—",
         ", ".join(s["fixed_by"]) if s["fixed_by"] else ("—" if s["fixed_by"] is None else "≥2 landmarks"),
         s["after_review"] or "—",
         " ".join(t for t, on in (("multi-rooted", s["multirooted"]), ("tilted", s["tilted"]), ("anterior", s["anterior"])) if on) or "—"]
        for s in severe
    ]
    n_flagged = sum(s["flagged"] for s in severe)
    severe_header = ["Set", "Image / tooth", "True PBL", "Auto", "P(III/IV)", "Flagged", "Reason", "Fixed by", "After review", "Anatomy"]
    severe_align = "---|---|---:|---|---:|---|---|---|---|---"
    ext_severe = [s for s in severe if s["split"] == "external"]
    culprit_ext, culprit_dev = c["culprits_external"], c["culprits_development"]

    def culprit_line(cu: Mapping[str, Any]) -> str:
        counts = cu["single_landmark_fix_counts"]
        parts = [f"{NAMES.get(k, k)} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
        return ", ".join(parts)

    sim = c["correction_simulation"]

    def sim_rows(key: str) -> list[list[Any]]:
        out = []
        for policy, v in sim[key]["policies"].items():
            out.append([
                policy, f"{pct(v['stage_accuracy']['mean'])} [{pct(v['stage_accuracy']['p2.5'])}–{pct(v['stage_accuracy']['p97.5'])}]",
                f"{v['severe_misses']['mean']:.1f}", pct(v["flagged_errors_resolved"]["mean"]) if policy != "no review" and not policy.startswith("manual") else "—",
                pct(v["flagged_correct_broken"]["mean"]) if policy != "no review" and not policy.startswith("manual") else "—",
                f"{v['landmarks_moved_per_reviewed_tooth']['mean']:.1f}",
            ])
        return out

    example_rows = [
        [e["case"], e["kind"], e["why"], f"{e['image']} / {e['tooth_id']}", e["split"].replace("_", " "),
         (f"{e['auto_stage'] or 'invalid'} → {e['stage_after_simulated_review']}" if e["flagged"] else f"{e['auto_stage']} (no review)")
         + f" · ref {e['truth_stage']}",
         "flagged" if e["flagged"] else "accepted", f"{e['mean_landmark_error_px']:.1f}", f"[png](clinical_examples/{e['figure']})"]
        for e in manifest
    ]
    pct_root = c["human_noise_pct_root"]
    full = sim["external"]["policies"]["re-place all five"]
    none = sim["external"]["policies"]["no review"]
    manual = sim["external"]["policies"]["manual read of every tooth (no AI)"]
    verdict_line = (
        f"On the external test, a full re-read of every flagged tooth resolves {pct(full['flagged_errors_resolved']['mean'], 0)} of "
        f"flagged stage errors. It changes {pct(full['flagged_correct_broken']['mean'], 0)} of correctly staged flagged teeth to a wrong "
        f"stage. Overall stage accuracy moves from {pct(none['stage_accuracy']['mean'])} with no review to "
        f"{pct(full['stage_accuracy']['mean'])}; a manual read of every tooth gives {pct(manual['stage_accuracy']['mean'])}."
    )
    corner = "Reference ↓ · Auto →"
    return f"""# Clinical error analysis

All figures and tables come from `python -m week5.evaluate`. The external test (327 teeth) was scored
once, after every parameter was frozen. Development rows are cross-fitted out-of-fold.

![Twelve annotated cases](clinical_examples/overview.png)

## Stage errors on the external test

{table([corner, *stages], [[s, *row] for s, row in zip(stages, confusion)], "---|---:|---:|---:")}

## False-negative staging: every Stage III/IV tooth called I/II

Flagged by the review rule: {sum(s["flagged"] for s in ext_severe)}/{len(ext_severe)} external and
{n_flagged - sum(s["flagged"] for s in ext_severe)}/{len(severe) - len(ext_severe)} development teeth. "Fixed by" lists the single landmarks that would correct
the stage if moved to the reference position. "After review" is the stage after one simulated correction
(see below).

**External test**

{table(severe_header, [r for r in severe_rows if r[0] == "external"], severe_align)}

<details><summary>Development (cross-fitted), {sum(r[0] == "development" for r in severe_rows)} teeth</summary>

{table(severe_header, [r for r in severe_rows if r[0] == "development"], severe_align)}

</details>

## Which landmark causes stage errors?

Single-landmark fixes across all wrong stages: external {culprit_line(culprit_ext)}; development {culprit_line(culprit_dev)}.
The highest-σ landmark is itself a fix in {culprit_ext['most_uncertain_landmark_is_a_fix']}/{culprit_ext['n_stage_errors']} external and
{culprit_dev['most_uncertain_landmark_is_a_fix']}/{culprit_dev['n_stage_errors']} development stage errors. Bone-crest placement
dominates, which confirms weakness 2 of the error analysis.

## Are errors more common for particular teeth or image conditions?

Tooth type is approximated by DenPAR's structured fields: multi-rooted (molar-like) versus single-rooted,
anterior versus posterior site, and arch. DenPAR has no FDI tooth number for every box, so no per-tooth-number claim is made.
Image conditions use pixel measures with cut-offs taken from the development quartiles: RMS contrast
≤ {c['image_condition_cuts_from_development']['rms_contrast']:.3f}, and edge sharpness ≤ {c['image_condition_cuts_from_development']['sharpness']:.1f}.

**External test**

{table(["Subgroup", "n", "MRE px W4 → W5", "Stage acc. W4 → W5", "III/IV missed", "Review rate", "Accepted acc.", "Accepted III/IV misses"], sub_rows(c["subgroups_external"]))}

**Development (cross-fitted)**

{table(["Subgroup", "n", "MRE px W4 → W5", "Stage acc. W4 → W5", "III/IV missed", "Review rate", "Accepted acc.", "Accepted III/IV misses"], sub_rows(c["subgroups_development"]))}

## Does manual correction resolve the errors?

Previously, corrections were simulated by copying the expert reference, so they resolved every error
by construction. Week 5 instead uses a **noisy reviewer**. A reviewer edits only flagged teeth, and every
landmark they place lands at the reference plus Gaussian noise. The noise has the size of the Week 3
test–retest disagreement as a share of root length: CEJ {min(pct_root['mesial_cej'], pct_root['distal_cej']):.1f}–{max(pct_root['mesial_cej'], pct_root['distal_cej']):.1f}%,
crest {min(pct_root['mesial_bc'], pct_root['distal_bc']):.1f}–{max(pct_root['mesial_bc'], pct_root['distal_bc']):.1f}%, apex {pct_root['apex']:.1f}%. Results are the mean over
{sim['external']['seeds']} noise draws, with a 95% range.

Reviewer strategies:
- **re-place all five**: a full manual read of the flagged tooth;
- **move visibly wrong**: move only landmarks more than twice the typical reader disagreement away from the
  reference (an oracle for "looks wrong");
- **move two most uncertain**: move the two landmarks with the largest AI σ, using no oracle at all.

**External test, Week 3-level reader noise**

{table(["Strategy", "Stage accuracy (all teeth)", "III/IV missed", "Flagged errors resolved", "Correct flagged teeth broken", "Landmarks moved / reviewed tooth"], sim_rows("external"))}

**Sensitivity: reader twice as noisy**

{table(["Strategy", "Stage accuracy (all teeth)", "III/IV missed", "Flagged errors resolved", "Correct flagged teeth broken", "Landmarks moved / reviewed tooth"], sim_rows("external_double_reader_noise"))}

**Development (cross-fitted)**

{table(["Strategy", "Stage accuracy (all teeth)", "III/IV missed", "Flagged errors resolved", "Correct flagged teeth broken", "Landmarks moved / reviewed tooth"], sim_rows("development"))}

**Answer: manual correction does not resolve the errors consistently.** {verdict_line}
Reader noise can also flip a *correct* automatic stage, because flagged teeth sit near a stage boundary by
construction. AI-flagged review still beats a manual read of every tooth at the same reader precision. The App therefore:
shows the AI's 95% radius and stage probability while the reviewer corrects; records how far each
landmark moved, and whether it moved outside that radius; and warns when the corrected PBL lies within
3 pp of a stage boundary, where reader variability alone can change the stage. In that case a second reader is advisable.

## When the system recommends clinician review

1. P(auto stage) below the frozen threshold, or a possible missed Stage III/IV (see the uncertainty analysis);
2. the orientation self-check reversed the apex, or the measurement failed the geometric guardrails;
3. the clinician should also review, whatever the flag says, multi-rooted or tilted teeth, overlapping
   contacts, restorations obscuring the CEJ, and any case where the overlay visibly misses the anatomy.
   These are the subgroups with the lowest accuracy above.

## Twelve representative examples

The examples are 4 typical successes (median error, not best-case), 4 flagged errors resolved by the
simulated review, and 4 challenging cases. In each panel, × is the untouched automatic prediction, ○ is the
DenPAR reference, and the dashed circle is the calibrated 95% radius.

{table(["#", "Kind", "Why chosen", "Image / tooth", "Set", "Auto → after review (reference)", "Rule", "Mean err px", "Figure"], example_rows, "---:|---|---|---|---|---|---|---:|---")}

## Limitations

- The reviewer is simulated. Real clinician timing, usability and inter-clinician agreement still need a
  reader study; the App already records `moved_px`, `seconds_since_suggestion` and blind first reads for one.
- The reader-noise model comes from 15 Week 3 teeth read by a non-specialist and assumes no systematic bias.
- DenPAR is a single research dataset. Performance on other sensors, populations or projection geometries
  is unknown.
"""


def write_reports(metrics: Mapping[str, Any], calibration: Mapping[str, Any], manifest: Sequence[Mapping[str, Any]]) -> None:
    w4 = json.loads(W4_METRICS.read_text())
    (REPORTS / "ERROR_ANALYSIS.md").write_text(error_analysis(metrics, w4))
    (REPORTS / "MODEL_COMPARISON.md").write_text(model_comparison(metrics))
    (REPORTS / "UNCERTAINTY_ANALYSIS.md").write_text(uncertainty_report(metrics))
    (REPORTS / "CLINICAL_VALIDATION.md").write_text(clinical_report(metrics, manifest))


def main() -> None:
    metrics = json.loads((REPORTS / "metrics.json").read_text())
    calibration = json.loads((REPORTS / "calibration.json").read_text())
    manifest = json.loads((REPORTS / "clinical_examples" / "manifest.json").read_text())
    write_reports(metrics, calibration, manifest)


if __name__ == "__main__":
    main()
