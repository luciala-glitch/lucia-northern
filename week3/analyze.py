"""Reproduce exploratory legacy analysis or analyze new strict-schema records.

Run from repository root: python -m week3.analyze
New study: python -m week3.analyze --measurements path.json --output path
"""

from __future__ import annotations
import argparse
import csv
from dataclasses import asdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/pbl-week3-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from week3.pbl_calculator import (
    SideLandmarks,
    ToothLandmarks,
    calculate_tooth_pbl,
    stage_pbl,
    sub,
    dot,
)
from week3.exports import (
    make_record,
    json_export,
    csv_export,
    landmarks_from_record,
    validate_record,
)
from week3.statistics import agreement, quadratic_kappa
from week3.sensitivity import sensitivity, LANDMARK_NAMES
from week3.image_processing import preprocess, crest_profile, coordinate_rmsd
from week3.comparison import compare_conditions
from week3.errors import decompose_displacements

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT.parent / "week2" / "sample_xrays"
STAGES = {"I": 0, "II": 1, "III/IV": 2}
SYNTHETIC_PREFIX = "SYNTHETIC_"
TARGET_TEETH = 15


def fmt(value: float | None, spec: str, missing: str = "undefined") -> str:
    """Format a coefficient that may legitimately be undefined (None)."""
    return missing if value is None else format(value, spec)


def kappa_text(value: float | None) -> str:
    return fmt(
        value,
        ".4f",
        "undefined (all observations in one category; expected disagreement = 0)",
    )


def koo_li_band(value: float) -> str:
    """Koo & Li (2016) reliability bands for an ICC value."""
    if value < 0.5:
        return "poor"
    if value < 0.75:
        return "moderate"
    if value <= 0.9:
        return "good"
    return "excellent"


def reject_synthetic(records: list[dict]) -> None:
    synthetic = sum(
        str(r.get("image_id", "")).startswith(SYNTHETIC_PREFIX) for r in records
    )
    if synthetic:
        raise ValueError(
            f"{synthetic} synthetic fixture records found; never pool them with "
            "empirical data (pass --allow-synthetic only for pipeline testing)"
        )


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_legacy() -> list[dict]:
    """Keep condition unknown; apex midpoint is an explicit analytic proxy only."""
    with (ROOT.parent / "week2" / "measurements.csv").open() as handle:
        source = list(csv.DictReader(handle))
    # Chronological order, so a later correction supersedes an earlier reading.
    source.sort(key=lambda row: row["timestamp_utc"])
    latest = {}
    for row in source:
        key = (row["observer"], row["image_id"], row["tooth_id"], row["round"])
        latest[key] = row
    records = []
    for row in latest.values():

        def p(name: str) -> tuple[int, int]:
            return int(row[name + "_x"]), int(row[name + "_y"])

        m_tip, d_tip = p("mesial_root_tip"), p("distal_root_tip")
        apex = ((m_tip[0] + d_tip[0]) / 2, (m_tip[1] + d_tip[1]) / 2)
        lm = ToothLandmarks(
            SideLandmarks(p("mesial_cej"), p("mesial_bone_crest")),
            SideLandmarks(p("distal_cej"), p("distal_bone_crest")),
            apex,
        )
        records.append(
            {
                "key": (row["observer"], row["image_id"], row["tooth_id"]),
                "round": int(row["round"].split()[-1]),
                "landmarks": lm,
                "result": calculate_tooth_pbl(lm),
                "source": row,
            }
        )
    return records


def group_pairs(records: list[dict]) -> list[tuple[dict, dict]]:
    grouped: dict[tuple, dict] = {}
    for record in records:
        rounds = grouped.setdefault(record["key"], {})
        if record["round"] in rounds:
            raise ValueError("Duplicate record identity")
        rounds[record["round"]] = record
    return [(r[1], r[2]) for _, r in sorted(grouped.items()) if 1 in r and 2 in r]


def statistics_report(
    pairs: list[tuple[dict, dict]], output: Path, label: str
) -> tuple:
    first, second, stage1, stage2, ids = [], [], [], [], []
    for a, b in pairs:
        for side in ("mesial", "distal"):
            v1, v2 = (
                getattr(a["result"], side).pbl_pct,
                getattr(b["result"], side).pbl_pct,
            )
            first.append(v1)
            second.append(v2)
            stage1.append(STAGES[stage_pbl(v1)])
            stage2.append(STAGES[stage_pbl(v2)])
            ids.append(f"{a['key'][-1]} / {side}")
    summary = agreement(first, second, stage1, stage2)
    tooth_kappa = None
    if len(pairs) >= 2:
        tooth_kappa = quadratic_kappa(
            [STAGES[a["result"].stage] for a, b in pairs],
            [STAGES[b["result"].stage] for a, b in pairs],
        )
    data = asdict(summary) | {
        "tooth_pairs": len(pairs),
        "tooth_stage_quadratic_kappa": tooth_kappa,
    }
    (output / "statistics.json").write_text(
        json.dumps(data, indent=2, allow_nan=False) + "\n"
    )
    means, diff = (np.asarray(first) + second) / 2, np.asarray(second) - first
    fig, ax = plt.subplots(figsize=(9, 5.5), layout="constrained")
    ax.scatter(means, diff, color="#217a97", s=40)
    for i in summary.outside_indices:
        ax.annotate(
            ids[i],
            (means[i], diff[i]),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=8,
        )
    for value, color, name in [
        (summary.bias, "#163546", "Bias"),
        (summary.loa_lower, "#b9473a", "Lower LoA"),
        (summary.loa_upper, "#b9473a", "Upper LoA"),
    ]:
        ax.axhline(value, color=color, linestyle="--", label=f"{name}: {value:.3f} pp")
    ax.set(
        xlabel="Mean PBL of two rounds (%)",
        ylabel="Round 2 − Round 1 (percentage points)",
        title=f"Bland–Altman · {label}\n{len(pairs)} teeth / {len(first)} surfaces",
    )
    ax.legend(loc="best")
    ax.grid(alpha=0.15)
    fig.savefig(output / "bland_altman.png", dpi=160)
    plt.close(fig)
    rows = [
        {
            "identity": identity,
            "round1_pct": a,
            "round2_pct": b,
            "difference_pp": b - a,
            "outside_loa": i in summary.outside_indices,
        }
        for i, (identity, a, b) in enumerate(zip(ids, first, second))
    ]
    write_csv(output / "surface_agreement.csv", rows)
    return summary, rows, tooth_kappa


def overlay(a: dict, b: dict, output: Path, rank: int) -> None:
    lm1, lm2 = a["landmarks"], b["landmarks"]
    image = Image.open(SAMPLES / a["key"][1])
    fig, ax = plt.subplots(figsize=(6, 6), layout="constrained")
    ax.imshow(image, cmap="gray")
    allpoints = []
    for name in LANDMARK_NAMES:

        def get(lm):
            return (
                lm.apex
                if name == "apex"
                else getattr(getattr(lm, name.split(".")[0]), name.split(".")[1])
            )

        p, q = np.array(get(lm1)), np.array(get(lm2))
        allpoints.extend([p, q])
        ax.scatter(*p, c="#00d5ff", s=25)
        ax.scatter(*q, c="#ffae36", s=25)
        ax.annotate(
            "",
            xy=q,
            xytext=p,
            arrowprops={"arrowstyle": "->", "color": "#ffae36", "lw": 1.8},
        )
        ax.annotate(
            name,
            p,
            xytext=(5, 5),
            textcoords="offset points",
            color="#00d5ff",
            fontsize=8,
        )
    axis = a["result"].long_axis_vector
    ax.plot(
        [lm1.mid_cej[0], lm1.apex[0]],
        [lm1.mid_cej[1], lm1.apex[1]],
        c="#79ff79",
        label="R1 long axis",
    )
    for side in (lm1.mesial, lm1.distal):
        t = dot(sub(side.bc, side.cej), axis)
        projected = np.array(side.cej) + np.array(axis) * t
        ax.plot(
            [side.bc[0], projected[0]],
            [side.bc[1], projected[1]],
            "--",
            color="#ff70b7",
        )
        ax.plot(
            [side.cej[0], projected[0]], [side.cej[1], projected[1]], color="#ff70b7"
        )
    coords = np.array(allpoints)
    ax.set_xlim(coords[:, 0].min() - 65, coords[:, 0].max() + 65)
    ax.set_ylim(coords[:, 1].max() + 45, coords[:, 1].min() - 45)
    ax.set_title(
        f"Review rank {rank}: {a['key'][-1]}\nCyan R1 · Orange R2 / displacement arrows\nShared apex = midpoint proxy, not anatomical annotation",
        fontsize=10,
    )
    ax.legend(fontsize=8)
    ax.set_xlabel("Original x (px)")
    ax.set_ylabel("Original y (px)")
    fig.savefig(output / f"case_{rank}.png", dpi=160)
    plt.close(fig)


def synthetic_cases(output: Path) -> None:
    """Controlled failure illustrations, never claimed to be patient findings."""
    cases = [
        (
            "Obscured CEJ / restoration",
            ToothLandmarks(
                SideLandmarks((60, 60), (55, 90)),
                SideLandmarks((100, 60), (105, 92)),
                (80, 200),
            ),
            "mesial.cej",
            (0, 10),
        ),
        (
            "Overlapping molar roots",
            ToothLandmarks(
                SideLandmarks((60, 60), (55, 90)),
                SideLandmarks((100, 60), (105, 92)),
                (80, 200),
            ),
            "apex",
            (30, -25),
        ),
        (
            "Tilt + lateral crest error",
            ToothLandmarks(
                SideLandmarks((60, 60), (130, 95)),
                SideLandmarks((100, 60), (135, 100)),
                (180, 200),
            ),
            "mesial.bc",
            (10, 0),
        ),
    ]
    from week3.sensitivity import perturb

    fig, axes = plt.subplots(1, 3, figsize=(13, 5), layout="constrained")
    for ax, (title, lm, name, delta) in zip(axes, cases):
        result = calculate_tooth_pbl(lm)
        changed = perturb(lm, name, delta)
        after = calculate_tooth_pbl(changed)
        for side in (lm.mesial, lm.distal):
            p, bc = np.asarray(side.cej), np.asarray(side.bc)
            projection = p + np.asarray(result.long_axis_vector) * dot(
                sub(side.bc, side.cej), result.long_axis_vector
            )
            ax.plot([p[0], lm.apex[0]], [p[1], lm.apex[1]], c="#cccccc")
            ax.plot([p[0], bc[0]], [p[1], bc[1]], "--", c="#b9473a")
            ax.plot([p[0], projection[0]], [p[1], projection[1]], c="#217a97", lw=3)
            ax.scatter(*bc, c="#217a97")
        original = (
            lm.apex
            if name == "apex"
            else getattr(getattr(lm, name.split(".")[0]), name.split(".")[1])
        )
        target = np.array(original) + delta
        ax.annotate(
            "",
            xy=target,
            xytext=original,
            arrowprops={"arrowstyle": "->", "color": "#ee8f00", "lw": 3},
        )
        ax.plot([lm.mid_cej[0], lm.apex[0]], [lm.mid_cej[1], lm.apex[1]], c="#39844b")
        if title.startswith("Obscured"):
            ax.add_patch(plt.Rectangle((50, 48), 60, 18, color="#aaaaaa", alpha=0.5))
        if name == "apex":
            ax.plot(
                [lm.mid_cej[0], target[0]],
                [lm.mid_cej[1], target[1]],
                "--",
                c="#ee8f00",
            )
        euclid = (
            math.dist(lm.mesial.cej, lm.mesial.bc)
            / math.dist(lm.mesial.cej, lm.apex)
            * 100
        )
        ax.set_title(
            f"{title}\nMesial Δ: {after.mesial.pbl_pct-result.mesial.pbl_pct:+.2f} pp; "
            f"worse-side Δ: {after.pbl_max_pct-result.pbl_max_pct:+.2f} pp\n"
            f"Mesial projected {result.mesial.pbl_pct:.2f}% / Euclidean {euclid:.2f}%",
            fontsize=9,
        )
        ax.set_aspect("equal")
        ax.invert_yaxis()
        ax.set_xlabel("px")
    fig.suptitle(
        "SYNTHETIC geometry stress cases · green axis / blue projection / orange error vector"
    )
    fig.savefig(output / "synthetic_failure_cases.png", dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path)
    parser.add_argument(
        "--output", type=Path, help="isolate all generated artifacts in this directory"
    )
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="accept SYNTHETIC_ fixture records (pipeline tests only)",
    )
    args = parser.parse_args()
    output = args.output if args.output is not None else ROOT / "reports"
    output.mkdir(parents=True, exist_ok=True)
    if args.measurements:
        data = json.loads(args.measurements.read_text())
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array of measurement records")
        for record in data:
            validate_record(record)
        if not args.allow_synthetic:
            reject_synthetic(data)
        ignored = sum(r["round"] not in (1, 2) for r in data)
        if ignored:
            print(
                f"Warning: {ignored} records with round other than 1/2 are "
                "excluded from round-to-round agreement.",
                file=sys.stderr,
            )
        comparison = compare_conditions(data)
        (output / "preprocessing_comparison.json").write_text(
            json.dumps(comparison, indent=2) + "\n"
        )
        for condition in ("raw", "he", "clahe"):
            selected = [r for r in data if r["condition"] == condition]
            records = [
                {
                    "key": ("study", r["image_id"], r["tooth_id"]),
                    "round": r["round"],
                    "landmarks": landmarks_from_record(r),
                    "result": calculate_tooth_pbl(landmarks_from_record(r)),
                }
                for r in selected
            ]
            pairs = group_pairs(records)
            target = output / condition
            target.mkdir(exist_ok=True)
            if len(pairs) >= 2:
                statistics_report(pairs, target, condition)
        print(json.dumps(comparison, indent=2))
        return
    records = load_legacy()
    pairs = group_pairs(records)
    if not pairs:
        raise ValueError("No complete Round 1/2 tooth pairs in the legacy data")
    summary, surface_rows, tooth_kappa = statistics_report(
        pairs, output, "legacy condition unknown / apex proxy"
    )
    write_csv(
        output / "legacy_recomputed_metrics.csv",
        [
            {
                "observer": r["key"][0],
                "image_id": r["key"][1],
                "tooth_id": r["key"][2],
                "round": r["round"],
                "condition": "unknown",
                "apex_method": "midpoint_of_two_legacy_apices",
                "mesial_pbl_pct": r["result"].mesial.pbl_pct,
                "distal_pbl_pct": r["result"].distal.pbl_pct,
                "pbl_max_pct": r["result"].pbl_max_pct,
                "stage": r["result"].stage,
            }
            for r in records
        ],
    )
    # Select unique teeth by largest absolute bias-centered surface residual.
    ranked = sorted(
        pairs,
        key=lambda pair: max(
            abs(
                getattr(pair[1]["result"], s).pbl_pct
                - getattr(pair[0]["result"], s).pbl_pct
                - summary.bias
            )
            for s in ("mesial", "distal")
        ),
        reverse=True,
    )[:5]
    all_sensitivity = []
    case_rows = []
    for rank, (a, b) in enumerate(ranked, 1):
        overlay(a, b, output, rank)
        row = {"rank": rank, "tooth_id": a["key"][-1]}
        for side in ("mesial", "distal"):
            delta = (
                getattr(b["result"], side).pbl_pct - getattr(a["result"], side).pbl_pct
            )
            row[f"{side}_difference_pp"] = delta
            row[f"{side}_outside_loa"] = (
                delta < summary.loa_lower or delta > summary.loa_upper
            )
        case_rows.append(row)
    write_csv(output / "worst_cases.csv", case_rows)
    for a, b in pairs:
        for row in sensitivity(a["landmarks"]):
            all_sensitivity.append({"tooth_id": a["key"][-1], **row})
    write_csv(output / "sensitivity.csv", all_sensitivity)
    synth_summary = []
    for size in (2, 5, 10):
        for direction in ("parallel", "normal"):
            rows = [
                r
                for r in all_sensitivity
                if abs(r["shift_px"]) == size and r["direction"] == direction
            ]
            valid = [abs(r["max_change_pp"]) for r in rows if r["status"] == "valid"]
            synth_summary.append(
                {
                    "shift_px": size,
                    "direction": direction,
                    "trials": len(rows),
                    "rejected": sum(r["status"] != "valid" for r in rows),
                    # Every trial may be rejected; report missing, not a crash or 0.
                    "max_abs_pbl_change_pp": max(valid) if valid else None,
                    "mean_abs_pbl_change_pp": float(np.mean(valid)) if valid else None,
                }
            )
    write_csv(output / "sensitivity_summary.csv", synth_summary)
    error_rows = decompose_displacements(
        [(a["landmarks"], b["landmarks"]) for a, b in pairs]
    )
    write_csv(output / "error_decomposition.csv", error_rows)
    synthetic_cases(output)
    # Fixed-coordinate contrast control. This is NOT annotation repeatability.
    edge_rows = []
    profiles = {}
    for a, b in pairs:
        lm = a["landmarks"]
        image = Image.open(SAMPLES / a["key"][1])
        tangent = sub(
            lm.distal.bc, lm.mesial.bc
        )  # chord proxy, needs local expert tangent
        for condition in ("raw", "he", "clahe"):
            enhanced = preprocess(image, condition)
            for side in ("mesial", "distal"):
                offsets, intensity, gradient = crest_profile(
                    enhanced, getattr(lm, side).bc, tangent
                )
                edge_rows.append(
                    {
                        "tooth_id": a["key"][-1],
                        "side": side,
                        "condition": condition,
                        "peak_abs_gradient_gray_per_px": float(gradient.max()),
                        "mean_abs_gradient_gray_per_px": float(gradient.mean()),
                        "peak_offset_px": float(offsets[np.argmax(gradient)]),
                    }
                )
                if a == pairs[0][0] and side == "mesial":
                    profiles[condition] = (offsets, intensity, gradient)
    write_csv(output / "crest_edge_metrics.csv", edge_rows)
    contrast = []
    for condition in ("raw", "he", "clahe"):
        selected = [r for r in edge_rows if r["condition"] == condition]
        contrast.append(
            {
                "condition": condition,
                "fixed_coordinate_profiles": len(selected),
                "mean_peak_gradient_gray_per_px": float(
                    np.mean([r["peak_abs_gradient_gray_per_px"] for r in selected])
                ),
                "independent_landmark_rmsd_px": "N/A - no condition-specific annotations",
                "within_condition_coordinate_variance_px2": "N/A - no condition-specific annotations",
            }
        )
    write_csv(output / "preprocessing_comparison.csv", contrast)
    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True, layout="constrained")
    for condition, (offsets, intensity, gradient) in profiles.items():
        axes[0].plot(offsets, intensity, label=condition)
        axes[1].plot(offsets, gradient, label=condition)
    axes[0].set_ylabel("Intensity (0–255)")
    axes[1].set_ylabel("|dI/ds| (gray / px)")
    axes[1].set_xlabel("Offset normal to crest chord proxy (px)")
    axes[0].legend()
    axes[0].set_title("Fixed-coordinate contrast control · first tooth, mesial crest")
    fig.savefig(output / "crest_profile.png", dpi=160)
    plt.close(fig)
    image = Image.open(SAMPLES / pairs[0][0]["key"][1])
    lm = pairs[0][0]["landmarks"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained")
    for ax, condition in zip(axes, ("raw", "he", "clahe")):
        ax.imshow(preprocess(image, condition), cmap="gray", vmin=0, vmax=255)
        ax.set_xlim(lm.mid_cej[0] - 100, lm.mid_cej[0] + 100)
        ax.set_ylim(lm.apex[1] + 45, lm.mid_cej[1] - 70)
        ax.set_title(condition.upper())
        ax.axis("off")
    fig.suptitle("Same original pixels · contrast transforms only")
    fig.savefig(output / "contrast_comparison.png", dpi=160)
    plt.close(fig)
    export_dir = (output if args.output is not None else ROOT) / "exports" / "synthetic"
    export_dir.mkdir(parents=True, exist_ok=True)
    examples = []
    for tooth in range(1, 16):
        for rnd in (1, 2):
            depth = (8, 22, 40)[(tooth - 1) % 3] + (rnd - 1)
            lm = ToothLandmarks(
                SideLandmarks((60, 60), (60, 60 + depth)),
                SideLandmarks((100, 60), (100, 62 + depth)),
                (80, 160),
            )
            for condition in ("raw", "he", "clahe"):
                examples.append(
                    make_record("SYNTHETIC_geometry_fixture", tooth, condition, rnd, lm)
                )
    (export_dir / "measurements.json").write_text(json_export(examples))
    (export_dir / "measurements.csv").write_text(csv_export(examples))
    (export_dir / "PROVENANCE.md").write_text(
        "# Synthetic export fixtures\n\n90 schema-validated examples: 15 constructed tooth geometries × 2 controlled rounds × 3 condition labels. These are software fixtures, NOT independent manual annotations or clinical validation. Coordinates are deliberately identical across conditions; no inference about contrast is possible. Never pool with empirical data.\n"
    )
    # Human-readable report generated from actual computed results.
    kappa = kappa_text(summary.weighted_kappa)
    icc_ci = (
        "undefined"
        if summary.icc_ci_lower is None
        else f"{summary.icc_ci_lower:.3f} to {summary.icc_ci_upper:.3f}"
    )
    icc_band = (
        "undefined"
        if summary.icc_ci_lower is None
        else " to ".join(
            dict.fromkeys(
                koo_li_band(v) for v in (summary.icc_ci_lower, summary.icc_ci_upper)
            )
        )
    )
    gaps = sorted(
        (
            datetime.fromisoformat(b["source"]["timestamp_utc"])
            - datetime.fromisoformat(a["source"]["timestamp_utc"])
        ).total_seconds()
        / 60
        for a, b in pairs
    )
    image_count = len({a["key"][1] for a, _ in pairs})
    surface_values = [
        v for r in surface_rows for v in (r["round1_pct"], r["round2_pct"])
    ]
    missing_teeth = max(0, TARGET_TEETH - len(pairs))
    outside = len(summary.outside_indices)
    worst_lines = "\n".join(
        f"| {r['rank']} | {r['tooth_id']} | {r['mesial_difference_pp']:+.3f} | {r['distal_difference_pp']:+.3f} | {r['mesial_outside_loa'] or r['distal_outside_loa']} |"
        for r in case_rows
    )
    sens_lines = "\n".join(
        f"| {r['shift_px']} | {r['direction']} | {fmt(r['mean_abs_pbl_change_pp'], '.3f', 'N/A')} | {fmt(r['max_abs_pbl_change_pp'], '.3f', 'N/A')} | {r['rejected']} / {r['trials']} |"
        for r in synth_summary
    )
    contrast_lines = "\n".join(
        f"| {r['condition']} | {r['fixed_coordinate_profiles']} | {r['mean_peak_gradient_gray_per_px']:.3f} | N/A | N/A |"
        for r in contrast
    )
    error_lines = "\n".join(
        f"| {r['landmark']} | {r['mean_parallel_shift_px']:+.3f} | {r['mean_normal_shift_px']:+.3f} | {r['rms_displacement_px']:.3f} | {r['mean_drift_magnitude_px']:.3f} | {r['centered_residual_rms_px']:.3f} |"
        for r in error_rows
    )
    report = (
        f"""# Week 3 — Statistical verification and failure analysis

## Evidence status

**Exploratory analysis only: {len(pairs)} paired teeth / {summary.n} surfaces, target {TARGET_TEETH} / {2 * TARGET_TEETH}.** Source: `week2/measurements.csv`, Lucia's same-day readings. Existing records have unknown enhancement state and two side-specific root tips. The shared apex used here is the arithmetic midpoint of those tips (unrounded); this is an **analytic proxy, not a newly identified anatomical apex**. All PBL percentages below were recomputed with projected geometry; Week 2 percentages were not reused. The Week 3 app collects the required shared anatomical apex directly.

No new manual readings were fabricated. {missing_teeth} additional teeth, independent repeats, condition-specific annotations, crown points, and clinically confirmed restoration/overlap cases remain to be collected. The synthetic exports are separate software examples and do not satisfy the empirical sample requirement.

Data limits that shape every coefficient below: the Round 1 → Round 2 interval was {np.median(gaps):.0f} min median (range {gaps[0]:.0f}–{gaps[-1]:.0f} min), so recall of earlier clicks is likely; the {len(pairs)} teeth come from only {image_count} images; and all {len(surface_values)} surface readings lie within {min(surface_values):.1f}–{max(surface_values):.1f}% PBL. That narrow range lowers ICC for a given measurement error and leaves stage kappa undefined.

## Statistical verification

| Metric | Recomputed result |
| --- | ---: |
| Surface ICC, two-way, absolute agreement, single measure | {fmt(summary.icc_2_1, ".4f")} |
| ICC 95% CI (McGraw & Wong) | {icc_ci} |
| Koo & Li 2016 band of the CI | {icc_band} |
| Surface quadratic weighted kappa | {kappa} |
| Tooth worse-side stage kappa | {kappa_text(tooth_kappa)} |
| Mean bias, Round 2 − Round 1 | {summary.bias:+.3f} pp |
| Sample SD of differences | {summary.difference_sd:.3f} pp |
| 95% lower LoA | {summary.loa_lower:+.3f} pp |
| 95% upper LoA | {summary.loa_upper:+.3f} pp |
| Descriptive bias SE (ignores tooth clustering) | {summary.bias_se:.3f} pp |
| Difference-versus-mean slope | {fmt(summary.difference_mean_slope, ".4f")} pp / pp |
| Surfaces strictly outside LoA | {outside} / {summary.n} |

![Bland–Altman](bland_altman.png)

ICC uses balanced two-way ANOVA: `(MS_subject − MS_error) / (MS_subject + (k−1)MS_error + k(MS_round−MS_error)/n)`, k=2. For one reader's repeated readings Koo & Li (2016) recommend the two-way mixed-effects, absolute-agreement, single-measure model; McGraw & Wong's ICC(A,1) estimate and its confidence interval are identical under the random and mixed models, so this is that coefficient. Interpret the 95% CI, not the point estimate, using Koo & Li's bands (<0.5 poor, 0.5–0.75 moderate, 0.75–0.9 good, >0.9 excellent); the interval treats surfaces as independent, so with two surfaces per tooth it is optimistic. Quadratic kappa uses fixed ordered classes I, II, III/IV and disagreement weights `(i−j)²/4`. Zero expected disagreement produces an undefined coefficient, not a perfect score. LoA = mean difference ± 1.96 × sample SD (ddof=1); these are limits for individual differences, not confidence intervals on the limits. Both surface and worse-side tooth stages use the exact assignment thresholds: <15, 15–33 inclusive, >33.

The observed mean shift is {summary.bias:+.3f} pp against a difference SD of {summary.difference_sd:.3f} pp. Directional drift may coexist with placement noise; this small, same-day dataset cannot establish their cause or prove systematic bias absent. Review coordinate arrows and the descriptive slope before attributing error to landmark drift. Mesial and distal surfaces share a tooth/apex and are correlated; the pooled surface coefficients are descriptive, and independence-based confidence claims would be inappropriate. No observer generalization or production/clinical validation is claimed.

## Largest tooth residuals (top {len(case_rows)})

Rank by the maximum of the two absolute bias-centered surface differences. **Only {outside} {"surface is" if outside == 1 else "surfaces are"} outside the calculated LoA; the table lists {len(case_rows)} review cases, not {len(case_rows)} claimed outliers.** An outlier is a flag for review, not evidence of pathology.

| Rank | Legacy tooth ID | Mesial Δ pp | Distal Δ pp | Any surface outside LoA |
| --- | --- | ---: | ---: | --- |
{worst_lines}

"""
        + "\n\n".join(
            f"![Review case {i}](case_{i}.png)" for i in range(1, len(case_rows) + 1)
        )
        + f"""

Cyan: Round 1; orange: Round 2; arrows: original-coordinate displacement; green: R1 axis; pink: projected crest distance and lateral residual. Shared-apex displacements reflect both original root tips. Without expert labels these images cannot establish obscured CEJs, overlapping molar roots, or a specific failure cause.

![Controlled failure geometries](synthetic_failure_cases.png)

The separate **synthetic** restoration, overlapping-root, and tilted-tooth examples demonstrate coordinate error vectors. In the tilted example, a lateral component inflates Euclidean distance; projected distance removes that component. Changing a CEJ or apex can rotate the axis, so even a normal displacement may change both surfaces. Collinear landmarks are valid if projected lengths are positive; only degenerate zero/negative projected root lengths are rejected. Lateral distance alone is not grounds for rejecting a valid axial crest position.

## Landmark error decomposition

Round-to-round displacement is resolved along each tooth's R1 axis (+ toward apex) and its normal `(-u_y, u_x)`. RMS displacement² = magnitude of mean drift² + centered residual RMS² (population normalization, denominator n). These are descriptive components in a local coordinate frame, not proof of causal systematic/random errors. The proxy apex averages two clicks and can conceal opposing root-tip errors.

| Landmark | Mean parallel px | Mean normal px | Total RMS px | Mean drift magnitude px | Centered residual RMS px |
| --- | ---: | ---: | ---: | ---: | ---: |
{error_lines}

A large mean component suggests directional placement drift to investigate; a large centered component suggests heterogeneous placement error. With only two same-day rounds and no reference landmarks, the components cannot distinguish observer memory, anatomy, projection changes, and random noise.

## Coordinate sensitivity

All {len(pairs)} R1 geometries × five landmarks × two directions × three magnitudes × two signs = {len(all_sensitivity)} trials. Move only one landmark per trial using the baseline unit axis or its normal, then recompute the axis and both percentages. Units are original pixels, with continuous shifts (not rounded for stress testing). Invalid placements are retained as rejection rows, never converted to zero loss. Summary uses absolute change in **worse-side** PBL; the full CSV also contains both surfaces and stage flips.

| Magnitude px | Direction | Mean absolute Δ pp | Maximum absolute Δ pp | Rejected / trials |
| --- | --- | ---: | ---: | ---: |
{sens_lines}

## Raw / HE / CLAHE comparison

CLAHE uses OpenCV clip limit 2.0 and tile grid (8,8). Global HE uses `equalizeHist`. Grayscale conversion preserves the image grid; no resizing enters analysis. The fixed-coordinate edge experiment uses R1 points on each of {len(pairs)} teeth and samples ±10 px at 1-px spacing, bilinearly, normal to the line connecting the two bone crests. **That line is a crest-tangent proxy, not a local expert contour.** Gradient is `abs(gradient(intensity))`, gray levels per pixel; peaks are descriptive and can reflect noise. These are contrast transforms only, not an added blur/noise degradation experiment.

| Condition | Fixed profiles | Mean peak gradient (gray / px) | Independent coordinate RMSD | Within-condition placement variance |
| --- | ---: | ---: | --- | --- |
{contrast_lines}

![Contrast crops](contrast_comparison.png)

![Local crest profiles](crest_profile.png)

Transforms do not move the stored coordinates. Copying the same points across conditions would trivially yield RMSD=0 and cannot establish localization stability. Therefore missing independent coordinate RMSD/variance are N/A. The new analysis command accepts independently re-annotated strict-schema records, matches image/tooth/round across all three conditions, calculates `sqrt(mean(dx²+dy²))` against raw and across rounds, and reports average within-landmark x+y sample variance in px². Contrast gains alone do not demonstrate a more accurate bone boundary.

## Deliverables and remaining data

- Typed projected-axis engine, custom geometry errors, optional crown-based ratio warnings, exact stage thresholds and III/IV review flag: implemented.
- JSON Schema, coordinate/metric recomputation, automatic JSON and flattened CSV downloads: implemented.
- Reproducible plots, sensitivity CSV, fixed-coordinate edge table, analysis of future matched contrast annotations: implemented.
- Empirical requirement: **{len(pairs)}/{TARGET_TEETH} teeth**, enhancement condition unknown; new shared-apex and contrast measurements still needed.
- Structured exports: `exports/synthetic/` contains 90 explicitly synthetic examples; no empirical condition labels were guessed.
- Branch coverage: see the saved test output and coverage JSON generated with the README command.
- Public repository/PR: local work prepared; publishing status is recorded separately, not inferred by this script.

## Methods references

- [Pingouin ICC definitions and estimator documentation](https://pingouin-stats.org/generated/pingouin.intraclass_corr.html)
- [Scikit-learn quadratic weighted Cohen kappa](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html)
- [OpenCV CLAHE API](https://docs.opencv.org/3.4.17/d6/db6/classcv_1_1CLAHE.html)
"""
    )
    (output / "WEEK3_REPORT.md").write_text(report)
    provenance = {
        "source": "week2/measurements.csv",
        "source_condition": "unknown",
        "shared_apex": "arithmetic midpoint of two legacy side tips; analytical proxy, not anatomical annotation",
        "empirical_tooth_pairs": len(pairs),
        "target_tooth_pairs": TARGET_TEETH,
        "synthetic_exports": "exports/synthetic/ only; do not pool",
        "limitation": "same-day non-independent legacy repeats; no condition-specific placements",
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(asdict(summary), indent=2))


if __name__ == "__main__":
    main()
