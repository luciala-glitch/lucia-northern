"""Figures for the report: the full radiograph with labels, and a close-up of one tooth."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

from week4.constants import STAGE_BOUNDARIES

# Stage colours. Line style and the text label also show the stage, so colour is not needed.
STAGE_STYLE = {
    "I": {"color": "#0ca30c", "ls": "-", "lw": 1.6, "name": "Stage I"},
    "II": {"color": "#fab219", "ls": "--", "lw": 2.2, "name": "Stage II"},
    "III/IV": {"color": "#d03b3b", "ls": "-", "lw": 3.2, "name": "Stage III/IV"},
    None: {"color": "#b0b0b0", "ls": ":", "lw": 1.6, "name": "Not staged"},
}
AUTO_COLOR = "#86b6ef"
MANUAL_COLOR = "#ffffff"


def _segment(ax: Any, a: Any, b: Any, **kw: Any) -> None:
    if a is not None and b is not None:
        ax.plot([a[0], b[0]], [a[1], b[1]], **kw)


def render_case_figure(
    report: Mapping[str, Any],
    image_path: str | Path | None,
    out_path: str | Path,
    dpi: int = 130,
) -> Path:
    out_path = Path(out_path)
    image = None
    if image_path and Path(image_path).is_file():
        image = Image.open(image_path).convert("L")
    teeth = report["teeth"]
    if image is None:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.axis("off")
        ax.text(0.5, 0.5, "No radiograph available for this case", ha="center", va="center")
        fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        return out_path

    w, h = image.size
    fig_w = 11.0
    fig_h = fig_w / 2 * h / w + 1.4
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(fig_w, fig_h))
    for ax, title in ((ax0, "Original radiograph"), (ax1, "Annotated: landmarks, PBL and stage")):
        ax.imshow(image, cmap="gray")
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])

    labels: list[tuple[Any, str, str]] = []
    staged = [t for t in teeth if t["final"]["pbl_max_pct"] is not None]
    worst = max(staged, key=lambda t: t["final"]["pbl_max_pct"], default=None)
    for tooth in teeth:
        final = tooth["final"]
        style = STAGE_STYLE[final["stage"]]
        bbox = tooth.get("bbox")
        is_worst = worst is not None and tooth is worst
        if bbox:
            x0, y0, x1, y1 = bbox
            ax1.add_patch(Rectangle(
                (x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor=style["color"],
                linestyle=style["ls"], linewidth=style["lw"] + (1.2 if is_worst else 0),
            ))
        auto = (tooth.get("auto") or {}).get("landmarks") or {}
        manual = (tooth.get("manual") or {}).get("landmarks") or {}
        shown = manual if tooth["final"]["source"] == "manual" else auto
        for side in ("mesial", "distal"):
            _segment(ax1, shown.get(f"{side}_cej"), shown.get(f"{side}_bc"),
                     color=style["color"], lw=2.0)
        if shown.get("mesial_cej") and shown.get("distal_cej") and shown.get("apex"):
            mid = [(shown["mesial_cej"][i] + shown["distal_cej"][i]) / 2 for i in range(2)]
            _segment(ax1, mid, shown["apex"], color="#ffffff", lw=0.8, ls=(0, (4, 3)), alpha=0.8)
        for name, p in auto.items():
            if p is not None:
                ax1.plot(*p, marker="o", ms=7, mfc="none", mec=AUTO_COLOR, mew=1.6)
        for name, p in manual.items():
            if p is None:
                continue
            a = auto.get(name)
            if a is not None and ((a[0] - p[0]) ** 2 + (a[1] - p[1]) ** 2) ** 0.5 > 0.5:
                ax1.annotate("", xy=p, xytext=a,
                             arrowprops={"arrowstyle": "->", "color": MANUAL_COLOR, "lw": 1.2})
                ax1.plot(*p, marker="X", ms=8, mfc=MANUAL_COLOR, mec="#0b0b0b", mew=0.8)
        src = {"manual": "corrected", "auto": "AI", "none": "no value"}[final["source"]]
        if final["pbl_max_pct"] is not None:
            line2 = f"{final['pbl_max_pct']:.1f}% · {style['name'].replace('Stage ', '')} · {src}"
        elif final.get("minimum_stage"):
            line2 = f"1 surface · ≥{final['minimum_stage']}"
        else:
            line2 = "not measured"
        head = tooth["label"]
        if is_worst:
            head = "▲ " + head + " (highest)"
        if any(wn["severity"] in ("high", "medium") for wn in tooth["warnings"]):
            head += " ⚠"
        anchor = bbox
        if not anchor:
            pts = [p for p in list(auto.values()) + list(manual.values()) if p is not None]
            if pts:  # no tooth box: put the label above the landmarks
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                anchor = [min(xs), max(min(ys) - 40, 0), max(xs), max(ys)]
        if anchor:
            labels.append((anchor, f"{head}\n{line2}", style["color"]))

    # Put each label at the top of its box. If it overlaps another label, move it down.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    placed: list[Any] = []
    inv = ax1.transData.inverted()
    for bbox, text, color in sorted(labels, key=lambda item: item[0][1]):
        y = max(bbox[1] + 4, 4)
        art = ax1.text(bbox[0] + 4, y, text, fontsize=7.5, color="#0b0b0b", va="top", linespacing=1.15,
                       bbox={"facecolor": color, "edgecolor": "none", "alpha": 0.9, "pad": 1.5})
        for _ in range(40):
            ext = art.get_window_extent(renderer).expanded(1.02, 1.08)
            clash = [p for p in placed if ext.overlaps(p)]
            if not clash:
                break
            lowest = min(p.y0 for p in clash)
            y = inv.transform((0, lowest))[1] + 3
            art.set_y(y)
        placed.append(art.get_window_extent(renderer))

    handles = [
        Patch(facecolor="none", edgecolor=s["color"], linestyle=s["ls"], linewidth=s["lw"], label=s["name"])
        for k, s in STAGE_STYLE.items() if k is not None
    ] + [
        Line2D([], [], marker="o", ls="", mfc="none", mec=AUTO_COLOR, mew=1.6, label="AI landmark"),
        Line2D([], [], marker="X", ls="", mfc=MANUAL_COLOR, mec="#0b0b0b", label="Manual correction (arrow = move)"),
        Line2D([], [], color="#555555", lw=2, label="CEJ → bone crest"),
    ]
    lo, hi = STAGE_BOUNDARIES
    fig.legend(handles=handles, loc="lower center", ncol=6, fontsize=8.5, frameon=False,
               bbox_to_anchor=(0.5, 0.02))
    fig.text(0.5, 0.42 / fig_h, f"Stage from worse surface: I < {lo:.0f}%  ·  II {lo:.0f}–{hi:.0f}%  ·  "
             f"III/IV > {hi:.0f}%   ·   ⚠ = review warning   ·   research prototype, not a diagnosis",
             ha="center", va="bottom", fontsize=8.5, color="#444444")
    fig.tight_layout(rect=(0, 0.75 / fig_h, 1, 1))
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    return out_path


def render_tooth_zoom(
    tooth: Mapping[str, Any],
    image_path: str | Path | None,
    out_path: str | Path,
    dpi: int = 130,
) -> Path | None:
    """Close-up of one tooth with AI points, corrected points and arrows for moved points.

    Returns None if there is no image, or no box and no points to find the tooth.
    """
    if not image_path or not Path(image_path).is_file():
        return None
    auto = (tooth.get("auto") or {}).get("landmarks") or {}
    manual = (tooth.get("manual") or {}).get("landmarks") or {}
    pts = [p for p in list(auto.values()) + list(manual.values()) if p is not None]
    bbox = tooth.get("bbox")
    if bbox:
        x0, y0, x1, y1 = bbox
    elif pts:
        x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
        x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    else:
        return None
    image = Image.open(image_path).convert("L")
    w, h = image.size
    pad = 0.12 * max(x1 - x0, y1 - y0, 40)
    left, top = max(int(x0 - pad), 0), max(int(y0 - pad), 0)
    right, bottom = min(int(x1 + pad), w), min(int(y1 + pad), h)
    crop = image.crop((left, top, right, bottom))
    out_path = Path(out_path)
    style = STAGE_STYLE[tooth["final"]["stage"]]
    fig_h = 4.2
    fig_w = max(2.4, fig_h * crop.width / max(crop.height, 1))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.imshow(crop, cmap="gray", extent=(left, right, bottom, top))
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)
    ax.set_xticks([])
    ax.set_yticks([])
    shown = manual if tooth["final"]["source"] == "manual" else auto
    for side in ("mesial", "distal"):
        _segment(ax, shown.get(f"{side}_cej"), shown.get(f"{side}_bc"), color=style["color"], lw=2.2)
    for p in auto.values():
        if p is not None:
            ax.plot(*p, marker="o", ms=9, mfc="none", mec=AUTO_COLOR, mew=1.8)
    short = {"mesial_cej": "M-CEJ", "distal_cej": "D-CEJ", "mesial_bc": "M-crest",
             "distal_bc": "D-crest", "apex": "Apex"}
    for name, p in (shown or {}).items():
        if p is not None:
            ax.annotate(short[name], p, xytext=(6, -6), textcoords="offset points", fontsize=7,
                        color="#ffffff", bbox={"facecolor": "#0b0b0b", "alpha": 0.6, "pad": 1, "edgecolor": "none"})
    for name, p in manual.items():
        a = auto.get(name)
        if p is None:
            continue
        if a is not None and ((a[0] - p[0]) ** 2 + (a[1] - p[1]) ** 2) ** 0.5 > 0.5:
            ax.annotate("", xy=p, xytext=a, arrowprops={"arrowstyle": "->", "color": MANUAL_COLOR, "lw": 1.4})
            ax.plot(*p, marker="X", ms=10, mfc=MANUAL_COLOR, mec="#0b0b0b", mew=0.8)
    for spine in ax.spines.values():
        spine.set_edgecolor(style["color"])
        spine.set_linewidth(3)
    ax.set_title(f"{tooth['label']} · {style['name']}", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    return out_path
