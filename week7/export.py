"""Export a case report as PDF, CSV and JSON. All three use the same report dictionary."""

from __future__ import annotations

import csv
import io
import re
import json
from pathlib import Path
from typing import Any, Mapping

from week4.constants import LANDMARK_NAMES
from week7.report import history_line

CSV_DIGITS = 2

CSV_COLUMNS = [
    "case_id", "tooth_id", "tooth_label", "arch", "site",
    "reported_source", "measurement_status",
    "reported_mesial_pbl_pct", "reported_distal_pbl_pct", "reported_pbl_max_pct",
    "reported_worse_surface", "reported_stage", "minimum_stage",
    "auto_mesial_pbl_pct", "auto_distal_pbl_pct", "auto_pbl_max_pct", "auto_stage",
    "auto_stage_probability", "auto_pbl_ci95_low", "auto_pbl_ci95_high", "auto_orientation_switched",
    "manual_mesial_pbl_pct", "manual_distal_pbl_pct", "manual_pbl_max_pct", "manual_stage",
    "manual_reviewer_id", "manual_saved_at_utc", "manual_method", "manual_changed_landmarks",
    "manual_added_landmarks", "manual_removed_landmarks", "manual_traceable", "correction_events",
    "correction_history",
    "review_flagged", "review_reasons", "warning_codes",
] + [f"auto_{n}_{a}" for n in LANDMARK_NAMES for a in "xy"] \
  + [f"manual_{n}_{a}" for n in LANDMARK_NAMES for a in "xy"]


def _r(value: Any) -> Any:
    return "" if value is None else round(float(value), CSV_DIGITS)


def _side(meas: Mapping[str, Any] | None, side: str) -> Any:
    if not meas or not meas.get(side):
        return ""
    return _r(meas[side]["pbl_pct"])


def csv_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for t in report["teeth"]:
        f, a, m = t["final"], t["auto"], t["manual"]
        am = a["measurement"] if a else None
        mm = m["measurement"] if m else None
        ci = (a or {}).get("pbl_ci95") or [None, None]
        row: dict[str, Any] = {
            "case_id": report["case_id"],
            "tooth_id": t["tooth_id"],
            "tooth_label": t["label"],
            "arch": t["arch"] or "",
            "site": t["site"] or "",
            "reported_source": f["source"],
            "measurement_status": f["status"],
            "reported_mesial_pbl_pct": _side(f, "mesial"),
            "reported_distal_pbl_pct": _side(f, "distal"),
            "reported_pbl_max_pct": _r(f["pbl_max_pct"]),
            "reported_worse_surface": f["worse_surface"] or "",
            "reported_stage": f["stage"] or "",
            "minimum_stage": f["minimum_stage"] or "",
            "auto_mesial_pbl_pct": _side(am, "mesial"),
            "auto_distal_pbl_pct": _side(am, "distal"),
            "auto_pbl_max_pct": _r(am["pbl_max_pct"]) if am else "",
            "auto_stage": (am or {}).get("stage") or "",
            "auto_stage_probability": _r((a or {}).get("stage_probability")),
            "auto_pbl_ci95_low": _r(ci[0]),
            "auto_pbl_ci95_high": _r(ci[1]),
            "auto_orientation_switched": "" if a is None else a["orientation_switched"],
            "manual_mesial_pbl_pct": _side(mm, "mesial"),
            "manual_distal_pbl_pct": _side(mm, "distal"),
            "manual_pbl_max_pct": _r(mm["pbl_max_pct"]) if mm else "",
            "manual_stage": (mm or {}).get("stage") or "",
            "manual_reviewer_id": (m or {}).get("reviewer_id") or "",
            "manual_saved_at_utc": (m or {}).get("saved_at_utc") or "",
            "manual_method": (m or {}).get("method") or "",
            "manual_changed_landmarks": ";".join((m or {}).get("changed_landmarks") or []),
            "manual_added_landmarks": ";".join((m or {}).get("added_landmarks") or []),
            "manual_removed_landmarks": ";".join((m or {}).get("removed_landmarks") or []),
            "manual_traceable": "" if m is None else m.get("traceable", True),
            "correction_events": len(t["correction_history"]),
            "correction_history": " | ".join(
                f"{e['action']} by {e['reviewer_id'] or '?'} at {e['saved_at_utc'] or '?'}"
                + ("" if e["action"] == "remove" else
                   f" -> {'—' if e['pbl_max_pct'] is None else round(e['pbl_max_pct'], CSV_DIGITS)}% {e['stage'] or ''}".rstrip())
                for e in t["correction_history"]),
            "review_flagged": t["review_flagged"],
            "review_reasons": " | ".join(t["review_reasons"]),
            "warning_codes": ";".join(w["code"] for w in t["warnings"]),
        }
        for prefix, rec in (("auto", a), ("manual", m)):
            for n in LANDMARK_NAMES:
                p = (rec or {}).get("landmarks", {}).get(n) if rec else None
                row[f"{prefix}_{n}_x"] = _r(p[0]) if p else ""
                row[f"{prefix}_{n}_y"] = _r(p[1]) if p else ""
        rows.append(row)
    return rows


def to_csv(report: Mapping[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(csv_rows(report))
    return buf.getvalue()


def to_json(report: Mapping[str, Any], case_input: Mapping[str, Any] | None = None) -> str:
    """The full report plus the original input, so nothing is lost."""
    payload = dict(report)
    if case_input is not None:
        payload["input_case"] = case_input
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ---- PDF
def _register_fonts() -> tuple[str, str]:
    """Use DejaVu Sans (it comes with matplotlib) so symbols like ≥ and ⚠ show on every computer."""
    import matplotlib
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        ttf = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(ttf / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(ttf / "DejaVuSans-Bold.ttf")))
        addMapping("DejaVuSans", 0, 0, "DejaVuSans")
        addMapping("DejaVuSans", 1, 0, "DejaVuSans-Bold")
        addMapping("DejaVuSans", 0, 1, "DejaVuSans")
        addMapping("DejaVuSans", 1, 1, "DejaVuSans-Bold")
    return "DejaVuSans", "DejaVuSans-Bold"


def safe_slug(case_id: Any) -> str:
    """Make a case ID safe to use as a file name on Windows."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(case_id)).strip("._")
    return slug or "case"


def _pct(v: Any) -> str:
    return "—" if v is None else f"{v:.1f}%"


def _side_pct(meas: Mapping[str, Any] | None, side: str) -> str:
    if not meas or not meas.get(side):
        return "—"
    return _pct(meas[side]["pbl_pct"])


def to_pdf(report: Mapping[str, Any], figure_path: str | Path | None, out_path: str | Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    out_path = Path(out_path)
    font, bold = _register_fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=font, fontSize=8.5, leading=11)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=bold, fontSize=15, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=bold, fontSize=11, spaceBefore=6, spaceAfter=3)
    page = landscape(A4)
    doc = SimpleDocTemplate(str(out_path), pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"PBL case report {report['case_id']}")
    s = report["summary"]
    story: list[Any] = [
        Paragraph(f"Periodontal bone loss (PBL) case report — {report['case_id']}", h1),
        Paragraph(f"<b>RESEARCH PROTOTYPE — FOR PROFESSIONAL REVIEW, NOT A DIAGNOSIS.</b> "
                  f"{report['disclaimer']}", small),
        Spacer(1, 4),
        Paragraph(
            f"Generated {report['generated_at_utc']} · report {report['report_version']} · "
            f"image {report['image'].get('path', '—')} · "
            f"teeth {s['teeth_total']} (staged {s['teeth_staged']}, flagged {s['teeth_flagged']}, "
            f"manually corrected {s['teeth_manually_corrected']})", small),
        Paragraph(
            f"<b>Highest tooth-level stage:</b> {s['highest_tooth_stage'] or '—'} "
            f"(highest PBL {_pct(s['highest_pbl_pct'])} on {s['highest_pbl_tooth'] or '—'}). "
            f"Stage counts: I {s['stage_counts']['I']}, II {s['stage_counts']['II']}, "
            f"III/IV {s['stage_counts']['III/IV']}. {s['stage_note']}", body),
    ]
    for w in report["case_warnings"]:
        story.append(Paragraph(f"⚠ <b>{w['code']}</b>: {w['message']}", body))
    if figure_path and Path(figure_path).is_file():
        from PIL import Image as PILImage
        # Use a JPEG copy in the PDF. The PNG made each PDF about 1 MB.
        jpg = out_path.with_name(out_path.stem + "_figure_tmp.jpg")
        with PILImage.open(figure_path) as im:
            iw, ih = im.size
            im.convert("RGB").save(jpg, quality=85)
        figure_path = jpg
        max_w, max_h = page[0] - 28 * mm, page[1] - 75 * mm
        scale = min(max_w / iw, max_h / ih)
        story += [Spacer(1, 4), RLImage(str(figure_path), width=iw * scale, height=ih * scale)]

    story += [PageBreak(), Paragraph("Tooth-level measurements", h2)]
    head = ["Tooth", "Arch / site", "Reported from", "Mesial PBL", "Distal PBL", "PBL (worse surface)",
            "Reported stage", "AI PBL · stage", "AI P(stage)", "AI 95% interval", "Corrected PBL · stage",
            "Warnings (high / medium)"]
    hstyle = ParagraphStyle("th", parent=small, fontName=bold, fontSize=7, leading=8.5)
    rows: list[list[Any]] = [[Paragraph(h, hstyle) for h in head]]
    stage_bg = {"I": "#e3f4e3", "II": "#fff1cf", "III/IV": "#f8dcdc"}
    style_cmds: list[Any] = [
        ("FONT", (0, 0), (-1, -1), font, 7.5),
        ("FONT", (0, 0), (-1, 0), bold, 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e1e0d9")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c3c2b7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i, t in enumerate(report["teeth"], start=1):
        f, a, m = t["final"], t["auto"], t["manual"]
        am = a["measurement"] if a else None
        mm_ = m["measurement"] if m else None
        ci = (a or {}).get("pbl_ci95")
        p = (a or {}).get("stage_probability")
        src = {"manual": "Manual", "auto": "Automated", "none": "Not reported"}[f["source"]]
        stage = f["stage"] or (f"≥ {f['minimum_stage']} (1 surface)" if f["minimum_stage"] else "—")
        rows.append([
            t["label"], f"{t['arch'] or '—'} / {t['site'] or '—'}", src,
            _side_pct(f, "mesial"), _side_pct(f, "distal"), _pct(f["pbl_max_pct"]), stage,
            f"{_pct(am['pbl_max_pct'])} · {am['stage'] or '—'}" if am else "—",
            "—" if p is None else f"{p:.2f}",
            "—" if not ci else f"{ci[0]:.1f}–{ci[1]:.1f}%",
            f"{_pct(mm_['pbl_max_pct'])} · {mm_['stage'] or '—'}" if mm_ else "—",
            Paragraph("<br/>".join(w["code"].replace("_", " ").lower() for w in t["warnings"]
                                  if w["severity"] != "info") or "none", small),
        ])
        if f["stage"] in stage_bg:
            style_cmds.append(("BACKGROUND", (6, i), (6, i), colors.HexColor(stage_bg[f["stage"]])))
        if f["source"] == "manual":
            style_cmds.append(("FONT", (2, i), (2, i), bold, 7.5))
    col_w = [13, 25, 19, 15, 15, 18, 22, 25, 17, 24, 27, 0]
    total = page[0] / mm - 28
    col_w[-1] = total - sum(col_w)
    table = Table(rows, colWidths=[c * mm for c in col_w], repeatRows=1)
    table.setStyle(TableStyle(style_cmds))
    story += [table, Spacer(1, 3), Paragraph(
        "Reported values use the manual correction when one exists; the automated (AI) values are kept "
        "unchanged beside it. AI P(stage) = Monte Carlo support for the AI stage; AI 95% interval = "
        "calibrated Week 5 PBL interval. Corrected values carry no model interval.", small)]

    story += [Paragraph("Interpretation and warnings", h2)]
    for t in report["teeth"]:
        block = [Paragraph(f"<b>{t['label']}</b> — {t['interpretation']}", body)]
        a, m = t["auto"], t["manual"]
        if m is not None and a is not None:
            am = a["measurement"]
            moved = ", ".join(
                [f"{n} {m['moved_px'][n]:.1f} px" for n in m["changed_landmarks"]]
                + [f"{n} added" for n in m["added_landmarks"]]
                + [f"{n} removed" for n in m["removed_landmarks"]]) or "none"
            block.append(Paragraph(
                f"Trace: automated {_pct(am['pbl_max_pct'])} (Stage {am['stage'] or '—'}) → corrected "
                f"{_pct(m['measurement']['pbl_max_pct'])} (Stage {m['measurement']['stage'] or '—'}) by "
                f"{m['reviewer_id'] or 'unknown reviewer'} at {m['saved_at_utc'] or '—'}; "
                f"method: {m['method'] or '—'}; landmarks moved: {moved}.", small))
        if len(t["correction_history"]) > 1:
            lines = [history_line(k, e) for k, e in enumerate(t["correction_history"], start=1)]
            block.append(Paragraph("Correction history: " + "; ".join(lines), small))
        if t["review_flagged"]:
            block.append(Paragraph("Review flag: " + "; ".join(t["review_reasons"]), small))
        for w in t["warnings"]:
            mark = {"high": "⚠ HIGH", "medium": "⚠", "info": "ℹ"}[w["severity"]]
            block.append(Paragraph(f"{mark} {w['code']}: {w['message']}", small))
        block.append(Spacer(1, 4))
        story.append(KeepTogether(block))
    story += [Paragraph("Method", h2), Paragraph(report["method"]["pbl_definition"], small),
              Paragraph(report["method"]["stage_rule"], small),
              Paragraph(f"Boundary warning band ±{report['method']['boundary_warning_pp']:.0f} pp; review "
                        f"threshold P(stage) < {report['method']['review_min_stage_probability']:.2f}. "
                        f"Calculator: {report['method']['calculator']}.", small)]
    src = report.get("source") or {}
    if src:
        story.append(Paragraph("Provenance: " + "; ".join(f"{k}: {v}" for k, v in src.items()), small))

    def footer(canvas: Any, _doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.drawString(14 * mm, 7 * mm, f"{report['case_id']} · research prototype — supports professional "
                                           f"review, not an independent clinical diagnosis")
        canvas.drawRightString(page[0] - 14 * mm, 7 * mm, f"page {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    if figure_path and Path(figure_path).name.endswith("_figure_tmp.jpg"):
        Path(figure_path).unlink(missing_ok=True)
    return out_path
