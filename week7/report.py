"""Week 7 case report: turns tooth landmarks into PBL values, stages and warnings.

The app and exports share one report. Measurements use the Week 3 calculator
and retain the original landmarks alongside any reviewer edits.

Input case format::

    {
      "case_id": "DENPAR-TEST-68",
      "image": {"path": "...", "width": 1168, "height": 883},
      "source": {...free-form provenance...},
      "teeth": [
        {
          "tooth_id": 1, "label": "T1", "arch": "Lower", "site": "Left",
          "bbox": [x0, y0, x1, y1] | None,
          "auto": {
            "detector": "...",
            "landmarks": {"mesial_cej": [x, y] | None, ...},
            "sigma_px": {"mesial_cej": s, ...} | None,
            "pbl_ci95": [lo, hi] | None,
            "stage_probabilities": {"I": p, "II": p, "III/IV": p} | None,
            "orientation_switched": bool
          } | None,
          "manual": {
            "landmarks": {...}, "reviewer_id": "...", "saved_at_utc": "...",
            "method": "...", "note": "..."
          } | None
        }
      ]
    }
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from week3.pbl_calculator import (
    PBLValidationError,
    SideLandmarks,
    ToothLandmarks,
    calculate_tooth_pbl,
    long_axis,
    stage_pbl,
    _side,
)
from week4.constants import LANDMARK_NAMES, STAGE_BOUNDARIES

REPORT_VERSION = "week7-1.0"
STAGES = ("I", "II", "III/IV")
# Same value as the Week 4/5 App. My Week 3 repeat readings differed by up to
# about 11 pp, so a value this close to 15% or 33% could change stage.
BOUNDARY_WARNING_PP = 3.0
# Week 5 review rule (from week5/reports/calibration.json).
MIN_STAGE_PROBABILITY = 0.94
# 95% circle for a 2-D Gaussian point: radius = 2.4477 * sigma.
RADIUS_95 = 2.4477

DISCLAIMER = (
    "This research report is for review by a dental professional. It is not an independent clinical diagnosis. "
    "Each tooth stage uses bone loss on the X-ray alone. Stages III and IV are grouped together. "
    "The report does not assess clinical attachment loss, tooth loss, complexity or grade."
)

LANDMARK_LABELS = {
    "mesial_cej": "Mesial CEJ",
    "distal_cej": "Distal CEJ",
    "mesial_bc": "Mesial bone crest",
    "distal_bc": "Distal bone crest",
    "apex": "Apex",
}

SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}


def _point(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return [x, y]


def clean_landmarks(raw: Mapping[str, Any] | None) -> dict[str, list[float] | None]:
    raw = raw or {}
    return {name: _point(raw.get(name)) for name in LANDMARK_NAMES}


def measure(landmarks: Mapping[str, Any] | None) -> dict[str, Any]:
    """Measure one tooth.

    status is "ok", "partial" (only one surface can be measured, so no stage),
    "missing" (not enough points) or "invalid" (the calculator rejected the points).
    """
    pts = clean_landmarks(landmarks)
    missing = [n for n in LANDMARK_NAMES if pts[n] is None]
    empty = {
        "status": "missing",
        "missing_landmarks": missing,
        "error": None,
        "long_axis_vector": None,
        "mesial": None,
        "distal": None,
        "pbl_max_pct": None,
        "worse_surface": None,
        "stage": None,
        "minimum_stage": None,
    }
    if not missing:
        tooth = ToothLandmarks(
            SideLandmarks(pts["mesial_cej"], pts["mesial_bc"]),
            SideLandmarks(pts["distal_cej"], pts["distal_bc"]),
            pts["apex"],
        )
        try:
            result = calculate_tooth_pbl(tooth)
        except PBLValidationError as exc:
            return {**empty, "status": "invalid", "error": str(exc)}
        sides = {
            name: {
                "defect_px": side.defect_px,
                "root_px": side.root_px,
                "pbl_pct": side.pbl_pct,
            }
            for name, side in (("mesial", result.mesial), ("distal", result.distal))
        }
        worse = "mesial" if result.mesial.pbl_pct >= result.distal.pbl_pct else "distal"
        return {
            **empty,
            "status": "ok",
            "long_axis_vector": list(result.long_axis_vector),
            **sides,
            "pbl_max_pct": result.pbl_max_pct,
            "worse_surface": worse,
            "stage": result.stage,
            "minimum_stage": result.stage,
        }
    # The long axis needs both CEJs and the apex. After that, each surface needs its crest.
    if any(pts[n] is None for n in ("mesial_cej", "distal_cej", "apex")):
        return empty
    tooth_axis = ToothLandmarks(
        SideLandmarks(pts["mesial_cej"], pts["mesial_cej"]),
        SideLandmarks(pts["distal_cej"], pts["distal_cej"]),
        pts["apex"],
    )
    try:
        axis = long_axis(tooth_axis)
    except PBLValidationError as exc:
        return {**empty, "status": "invalid", "error": str(exc)}
    out = {**empty, "status": "partial", "long_axis_vector": list(axis)}
    available = []
    for side in ("mesial", "distal"):
        bc = pts[f"{side}_bc"]
        if bc is None:
            continue
        try:
            res = _side(SideLandmarks(pts[f"{side}_cej"], bc), tuple(pts["apex"]), axis)
        except PBLValidationError as exc:
            return {**empty, "status": "invalid", "error": str(exc)}
        out[side] = {"defect_px": res.defect_px, "root_px": res.root_px, "pbl_pct": res.pbl_pct}
        available.append(res.pbl_pct)
    if not available:
        return empty
    # With one surface we do not know the worse side, so this is only a minimum stage.
    out["minimum_stage"] = stage_pbl(max(available))
    return out


def _distance(a: Sequence[float] | None, b: Sequence[float] | None) -> float | None:
    if a is None or b is None:
        return None
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _warn(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _boundary_warnings(value: float, prefix: str) -> list[dict[str, str]]:
    out = []
    for boundary in STAGE_BOUNDARIES:
        gap = value - boundary
        if abs(gap) <= BOUNDARY_WARNING_PP:
            if gap == 0:
                message = f"{prefix} PBL is exactly at the {boundary:g}% cutoff."
            else:
                distance = _shown(abs(gap), lambda rounded: rounded > 0)
                direction = "above" if gap > 0 else "below"
                unit = "point" if float(distance) == 1 else "points"
                message = f"{prefix} PBL is {distance} percentage {unit} {direction} the {boundary:g}% cutoff."
            out.append(_warn("NEAR_STAGE_BOUNDARY", "medium", message))
    return out


def _shown(value: float, ok: Any) -> str:
    """Round for display. Add decimals if rounding would break the rule (e.g. 14.99 -> 15.0)."""
    for digits in range(1, 7):
        text = f"{value:.{digits}f}"
        if ok(float(text)):
            return text
    return repr(value)


def _stage_rule(value: float, stage: str) -> str:
    lo, hi = STAGE_BOUNDARIES
    if stage == "I":
        return f"{_shown(value, lambda v: v < lo)}% < {lo:g}% → Stage I"
    if stage == "II":
        return f"{lo:g}% ≤ {_shown(value, lambda v: lo <= v <= hi)}% ≤ {hi:g}% → Stage II"
    return f"{_shown(value, lambda v: v > hi)}% > {hi:g}% → Stage III/IV"


def _surface_sentence(name: str, side: Mapping[str, float] | None) -> str:
    if side is None:
        return f"{name.capitalize()}: not measurable (bone crest missing)."
    return (
        f"{name.capitalize()}: CEJ-to-crest {side['defect_px']:.1f} px ÷ CEJ-to-apex "
        f"{side['root_px']:.1f} px (both projected on the tooth long axis) = {side['pbl_pct']:.1f}%."
    )


def explain(final: Mapping[str, Any], source: str) -> str:
    """Short sentence on how the PBL and stage were calculated."""
    if source == "none" or final["status"] in ("missing", "invalid"):
        if final["status"] == "invalid":
            return f"No PBL reported: the landmark geometry was rejected ({final['error']})."
        names = ", ".join(LANDMARK_LABELS[n] for n in final["missing_landmarks"]) or "landmarks"
        return f"No PBL reported: missing {names}."
    origin = "manually corrected landmarks" if source == "manual" else "automated landmarks"
    parts = [f"Calculated from {origin}.", _surface_sentence("mesial", final["mesial"]),
             _surface_sentence("distal", final["distal"])]
    if final["status"] == "partial":
        parts.append(
            f"Only one surface can be measured. The full stage is unknown. This side "
            f"implies at least Stage {final['minimum_stage']}."
        )
    else:
        parts.append(
            f"The stage uses the worse surface ({final['worse_surface']}): "
            f"{_stage_rule(final['pbl_max_pct'], final['stage'])}."
        )
    return " ".join(parts)


PROVENANCE_FIELDS = ("reviewer_id", "saved_at_utc", "method")
MOVE_EPS_PX = 1e-6


def _compare(auto_lm: Mapping[str, Any] | None, man_lm: Mapping[str, Any]) -> dict[str, Any]:
    moved: dict[str, float | None] = {}
    changed, added, removed = [], [], []
    for name in LANDMARK_NAMES:
        a = (auto_lm or {}).get(name)
        m = man_lm[name]
        d = _distance(a, m)
        moved[name] = d
        if a is None and m is not None:
            added.append(name)
        elif a is not None and m is None:
            removed.append(name)
        elif d is not None and d > MOVE_EPS_PX:
            changed.append(name)
    return {"moved_px": moved, "changed_landmarks": changed, "added_landmarks": added, "removed_landmarks": removed}


def _manual_record(manual_in: Mapping[str, Any], auto: Mapping[str, Any] | None) -> dict[str, Any]:
    man_landmarks = clean_landmarks(manual_in.get("landmarks"))
    cmp = _compare(auto["landmarks"] if auto else None, man_landmarks)
    sigma = (auto or {}).get("sigma_px") or {}
    outside = [n for n in cmp["changed_landmarks"]
               if n in sigma and cmp["moved_px"][n] > RADIUS_95 * float(sigma[n])]
    return {
        "reviewer_id": manual_in.get("reviewer_id"),
        "saved_at_utc": manual_in.get("saved_at_utc"),
        "method": manual_in.get("method"),
        "note": manual_in.get("note"),
        "landmarks": man_landmarks,
        **cmp,
        "outside_ai_95_radius": outside,
        "measurement": measure(man_landmarks),
    }


def _history_events(tooth: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """List of saves and removals. Old inputs with no history get one "save" for their correction."""
    events = tooth.get("correction_history")
    if events is not None:
        return list(events)
    manual = tooth.get("manual")
    return [] if manual is None else [{"action": "save", **manual}]


def _history_entry(event: Mapping[str, Any], auto: Mapping[str, Any] | None) -> dict[str, Any]:
    action = event.get("action", "save")
    entry: dict[str, Any] = {
        "action": action,
        "reviewer_id": event.get("reviewer_id"),
        "saved_at_utc": event.get("saved_at_utc"),
        "method": event.get("method"),
        "note": event.get("note"),
    }
    if action == "save":
        rec = _manual_record(event, auto)
        m = rec["measurement"]
        entry.update({
            "landmarks": rec["landmarks"],
            "changed_landmarks": rec["changed_landmarks"],
            "added_landmarks": rec["added_landmarks"],
            "removed_landmarks": rec["removed_landmarks"],
            "status": m["status"],
            "pbl_max_pct": m["pbl_max_pct"],
            "stage": m["stage"],
        })
    return entry


def build_tooth_report(tooth: Mapping[str, Any]) -> dict[str, Any]:
    auto_in = tooth.get("auto")
    manual_in = tooth.get("manual")
    warnings: list[dict[str, str]] = []

    auto: dict[str, Any] | None = None
    flagged = False
    review_reasons: list[str] = []
    if auto_in is not None:
        auto_landmarks = clean_landmarks(auto_in.get("landmarks"))
        auto_meas = measure(auto_landmarks)
        probs = auto_in.get("stage_probabilities")
        ci = auto_in.get("pbl_ci95")
        stage = auto_meas["stage"]
        p_own = None if (probs is None or stage is None) else float(probs.get(stage, 0.0))
        if auto_meas["status"] != "ok":
            flagged = True
            review_reasons.append("no valid automated measurement")
        if p_own is not None and p_own < MIN_STAGE_PROBABILITY:
            flagged = True
            review_reasons.append(
                f"Stage {stage} has {p_own:.0%} Monte Carlo support (review threshold "
                f"{MIN_STAGE_PROBABILITY:.0%})"
            )
        if auto_in.get("orientation_switched"):
            flagged = True
            review_reasons.append("orientation self-check reversed the apex direction")
        auto = {
            "detector": auto_in.get("detector"),
            "landmarks": auto_landmarks,
            "sigma_px": auto_in.get("sigma_px"),
            "pbl_ci95": list(ci) if ci is not None else None,
            "stage_probabilities": probs,
            "stage_probability": p_own,
            "orientation_switched": bool(auto_in.get("orientation_switched", False)),
            "measurement": auto_meas,
        }
        if ci is not None and auto_meas["status"] == "ok":
            spanned = [b for b in STAGE_BOUNDARIES if ci[0] < b < ci[1]]
            if spanned:
                warnings.append(_warn(
                    "INTERVAL_SPANS_BOUNDARY", "info",
                    f"Automated 95% PBL interval {ci[0]:.1f}–{ci[1]:.1f}% crosses the "
                    + " and ".join(f"{b:.0f}%" for b in spanned) + " boundary.",
                ))
            width = ci[1] - ci[0]
            if width > 20:
                warnings.append(_warn(
                    "WIDE_INTERVAL", "info",
                    f"Automated 95% PBL interval is {width:.1f} pp wide.",
                ))
        if auto["orientation_switched"]:
            warnings.append(_warn(
                "ORIENTATION_SWITCHED", "medium",
                "The model reversed the apex direction. Check the apex on the image.",
            ))
        if p_own is not None and p_own < MIN_STAGE_PROBABILITY:
            warnings.append(_warn(
                "LOW_STAGE_SUPPORT", "medium",
                f"Automated Stage {stage} has {p_own:.0%} Monte Carlo support "
                f"(below {MIN_STAGE_PROBABILITY:.0%}).",
            ))

    manual: dict[str, Any] | None = None
    traceable = True
    if manual_in is not None:
        manual = _manual_record(manual_in, auto)
        if manual["outside_ai_95_radius"]:
            warnings.append(_warn(
                "CORRECTION_OUTSIDE_AI_95", "info",
                "Correction moved " + ", ".join(LANDMARK_LABELS[n] for n in manual["outside_ai_95_radius"])
                + " beyond the automated 95% radius.",
            ))
        missing_prov = [k for k in PROVENANCE_FIELDS if not manual_in.get(k)]
        manual["traceable"] = traceable = not missing_prov
        if missing_prov:
            warnings.append(_warn(
                "CORRECTION_PROVENANCE_MISSING", "high",
                "Manual correction has no " + ", ".join(missing_prov) + "; it is kept in the record but not "
                "used for the reported values until it is attributed to a reviewer.",
            ))
        if manual["added_landmarks"] or manual["removed_landmarks"]:
            parts = []
            if manual["added_landmarks"]:
                parts.append("added " + ", ".join(LANDMARK_LABELS[n] for n in manual["added_landmarks"]))
            if manual["removed_landmarks"]:
                parts.append("removed " + ", ".join(LANDMARK_LABELS[n] for n in manual["removed_landmarks"]))
            warnings.append(_warn("CORRECTION_ADDED_OR_REMOVED", "info",
                                  "Correction " + "; ".join(parts) + " relative to the automated landmarks."))

    history = [_history_entry(e, auto) for e in _history_events(tooth)]

    # Which values go in the report: a valid, signed correction first, then the AI result.
    if manual is not None and not traceable:
        # A correction with no reviewer is kept, but not reported.
        source, final = ("auto", auto["measurement"]) if auto is not None else ("none", measure(None))
    elif manual is not None and manual["measurement"]["status"] in ("ok", "partial"):
        source, final = "manual", manual["measurement"]
    elif manual is not None:
        source, final = "none", manual["measurement"]
        warnings.append(_warn(
            "CORRECTION_INVALID", "high",
            "Check the edited points. The report cannot calculate PBL from them.",
        ))
    elif auto is not None:
        source, final = "auto", auto["measurement"]
    else:
        source, final = "none", measure(None)

    if final["status"] == "missing":
        warnings.append(_warn(
            "MISSING_LANDMARKS", "high",
            "Missing " + ", ".join(LANDMARK_LABELS[n] for n in final["missing_landmarks"])
            + "; PBL not reported.",
        ))
        source = "none"
    elif final["status"] == "invalid":
        warnings.append(_warn("INVALID_GEOMETRY", "high", f"Geometry rejected: {final['error']}"))
        source = "none"
    elif final["status"] == "partial":
        warnings.append(_warn(
            "SINGLE_SURFACE_ONLY", "high",
            "Missing " + ", ".join(LANDMARK_LABELS[n] for n in final["missing_landmarks"])
            + f"; stage not assigned (measured surface implies at least Stage {final['minimum_stage']}).",
        ))
    else:
        label = "Reported" if source == "auto" else "Corrected"
        warnings.extend(_boundary_warnings(final["pbl_max_pct"], label))

    if source == "manual":
        auto_stage = auto["measurement"]["stage"] if auto else None
        if auto_stage is not None and final["stage"] is not None and auto_stage != final["stage"]:
            warnings.append(_warn(
                "STAGE_CHANGED_BY_CORRECTION", "medium",
                f"Manual correction changed the stage from {auto_stage} to {final['stage']}.",
            ))
        warnings.append(_warn(
            "MANUAL_NO_MODEL_UNCERTAINTY", "info",
            "The model interval applies only to the original measurement.",
        ))
    if flagged and (manual is None or not traceable):
        warnings.append(_warn(
            "FLAGGED_NOT_REVIEWED", "high",
            "Flagged for review (" + "; ".join(review_reasons) + ") but not yet reviewed.",
        ))

    warnings.sort(key=lambda w: SEVERITY_ORDER[w["severity"]])
    return {
        "tooth_id": tooth.get("tooth_id"),
        "label": tooth.get("label") or (f"T{tooth.get('tooth_id')}" if tooth.get("tooth_id") is not None else "T?"),
        "arch": tooth.get("arch"),
        "site": tooth.get("site"),
        "bbox": tooth.get("bbox"),
        "review_flagged": flagged,
        "review_reasons": review_reasons,
        "auto": auto,
        "manual": manual,
        "correction_history": history,
        "final": {"source": source, **final},
        "interpretation": explain(final, source),
        "warnings": warnings,
    }


REPO_ROOT = Path(__file__).resolve().parents[1]


def history_line(number: int, event: Mapping[str, Any]) -> str:
    """One line of the correction history, used by the App and the PDF."""
    who = event.get("reviewer_id") or "unknown"
    when = event.get("saved_at_utc") or "—"
    if event["action"] == "remove":
        return f"{number}. removed by {who} at {when}"
    pbl = "not measurable" if event["pbl_max_pct"] is None else f"{event['pbl_max_pct']:.1f}%"
    return f"{number}. saved by {who} at {when}: {pbl}, Stage {event['stage'] or '—'} ({event['status']})"


def upload_key(raw: bytes) -> str:
    """Key for an uploaded case. Uses the file content, so two files with the same name never mix."""
    return "upload|" + hashlib.sha256(raw).hexdigest()


def resolve_image(path: str | None) -> Path | None:
    """Find the image file (absolute or relative to the repo). None if it does not exist."""
    if not path:
        return None
    for candidate in (Path(path), REPO_ROOT / path):
        if candidate.is_file():
            return candidate
    return None


def build_case_report(case: Mapping[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    teeth_in = case.get("teeth") or []
    case_warnings: list[dict[str, str]] = []
    case_id = case.get("case_id")
    if not case_id:
        case_id = "UNIDENTIFIED"
        case_warnings.append(_warn("MISSING_CASE_ID", "high", "Case identifier missing."))
    if not teeth_in:
        case_warnings.append(_warn("NO_TEETH", "high", "Case contains no tooth records."))
    image = case.get("image") or {}
    if not image.get("path"):
        case_warnings.append(_warn("NO_IMAGE", "medium", "No radiograph attached; report is tabular only."))
    elif resolve_image(image["path"]) is None:
        case_warnings.append(_warn("IMAGE_NOT_FOUND", "medium",
                                   f"Radiograph file not found: {image['path']}; report is tabular only."))

    teeth = [build_tooth_report(t) for t in teeth_in]
    ids = [t["tooth_id"] for t in teeth]
    dupes = sorted({str(i) for i in ids if ids.count(i) > 1})
    if dupes:
        case_warnings.append(_warn("DUPLICATE_TOOTH_ID", "high",
                                   "Duplicate tooth identifiers in case: " + ", ".join(dupes)
                                   + ". Rows are listed in input order; check which tooth each row refers to."))

    staged = [t for t in teeth if t["final"]["stage"] is not None]
    counts = {s: sum(t["final"]["stage"] == s for t in staged) for s in STAGES}
    highest = max((t["final"]["stage"] for t in staged), key=STAGES.index, default=None)
    worst = max(staged, key=lambda t: t["final"]["pbl_max_pct"], default=None)
    summary = {
        "teeth_total": len(teeth),
        "teeth_staged": len(staged),
        "teeth_not_staged": len(teeth) - len(staged),
        "stage_counts": counts,
        "highest_tooth_stage": highest,
        "highest_pbl_tooth": worst["label"] if worst else None,
        "highest_pbl_pct": worst["final"]["pbl_max_pct"] if worst else None,
        "teeth_flagged": sum(t["review_flagged"] for t in teeth),
        "teeth_manually_corrected": sum(t["manual"] is not None for t in teeth),
        "correction_events": sum(len(t["correction_history"]) for t in teeth),
        "teeth_reported_from_manual": sum(t["final"]["source"] == "manual" for t in teeth),
        "teeth_with_high_warnings": sum(any(w["severity"] == "high" for w in t["warnings"]) for t in teeth),
        "stage_note": (
            "This summary covers the measured teeth on this image only."
        ),
    }
    return {
        "report_version": REPORT_VERSION,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "case_id": case_id,
        "image": image,
        "source": case.get("source"),
        "method": {
            "pbl_definition": "PBL (%) = 100 × CEJ-to-crest distance / CEJ-to-apex distance. "
                              "Both distances are measured along the axis from the CEJ midpoint to the apex. "
                              "Each surface has its own PBL.",
            "stage_rule": f"From the worse surface: < {STAGE_BOUNDARIES[0]:.0f}% Stage I; "
                          f"{STAGE_BOUNDARIES[0]:.0f}–{STAGE_BOUNDARIES[1]:.0f}% Stage II; "
                          f"> {STAGE_BOUNDARIES[1]:.0f}% Stage III/IV.",
            "boundary_warning_pp": BOUNDARY_WARNING_PP,
            "review_min_stage_probability": MIN_STAGE_PROBABILITY,
            "calculator": "week3.pbl_calculator.calculate_tooth_pbl",
        },
        "disclaimer": DISCLAIMER,
        "summary": summary,
        "case_warnings": case_warnings,
        "teeth": teeth,
    }
