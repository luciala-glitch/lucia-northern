"""Review tooth measurements and edit landmarks in Streamlit."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from week4.constants import LANDMARK_NAMES  # noqa: E402
from week7.cases import build_demo_cases  # noqa: E402
from week7.edge_cases import build_edge_cases  # noqa: E402
from week7.export import safe_slug, to_csv, to_json, to_pdf  # noqa: E402
from week7.figures import render_case_figure, render_tooth_zoom  # noqa: E402
from week7.report import (  # noqa: E402
    LANDMARK_LABELS, build_case_report, clean_landmarks, history_line, resolve_image, upload_key,
)

APP_METHOD = "manual entry in Week 7 reporting app"
st.set_page_config(page_title="PBL clinical report (Week 7)", layout="wide")


@st.cache_data
def _demo_cases() -> dict[str, dict]:
    cases = {c["case_id"]: c for c in build_demo_cases()}
    for c in build_edge_cases():
        cases[f"[edge] {c['case_id'] or 'no case id'}"] = c
    return cases


def _pct(value: float | None) -> str:
    return "not measurable" if value is None else f"{value:.1f}%"


def _workdir() -> Path:
    if "workdir" not in st.session_state:
        st.session_state["workdir"] = tempfile.mkdtemp(prefix="pbl_week7_")
    return Path(st.session_state["workdir"])


def _history(tooth: dict[str, Any]) -> list[dict[str, Any]]:
    """Get the tooth's history. The first time, start it from the existing correction."""
    if "correction_history" not in tooth:
        history = []
        if tooth.get("manual") is not None:
            history.append({"action": "save", **tooth["manual"]})
        tooth["correction_history"] = history
    return tooth["correction_history"]


def source_label(tooth: dict[str, Any]) -> str:
    source = tooth["final"]["source"]
    correction = tooth["manual"]
    if source == "manual":
        if str(correction.get("method") or "").startswith("SIMULATED"):
            return "Simulated correction"
        return f"Reviewer correction ({correction.get('reviewer_id')})"
    if source == "auto":
        if correction is not None and not correction.get("traceable", True):
            return "Automated (unattributed correction not used)"
        return "Automated"
    return "Not reported"


def _names(keys: list[str]) -> str:
    return ", ".join(LANDMARK_LABELS[k] for k in keys)


def _stage_text(meas: dict[str, Any] | None) -> str:
    if not meas:
        return "—"
    if meas["pbl_max_pct"] is not None:
        return f"{meas['pbl_max_pct']:.1f}% · Stage {meas['stage']}"
    if meas.get("minimum_stage"):
        return f"one surface only · at least Stage {meas['minimum_stage']}"
    return "not measurable"


def _flash_text(t: dict[str, Any], flash: dict[str, Any]) -> tuple[str, str]:
    who, label = flash["reviewer"], t["label"]
    now = source_label(t)
    if flash["action"] == "remove":
        return "info", f"Correction removed for {label} by {who}. The report now uses: {now}."
    if t["final"]["source"] == "manual" and t["manual"] and t["manual"]["reviewer_id"] == who:
        return "success", f"Saved for {label} by {who}. The report now uses this correction ({_stage_text(t['final'])})."
    reasons = "; ".join(w["message"] for w in t["warnings"] if w["severity"] == "high") or "see warnings"
    return "error", f"Saved for {label} by {who}, but the report does not use it: {reasons} Reported values: {now}."


st.title("Clinical PBL Report")
st.caption("Research prototype for dental review.")
st.session_state.setdefault("cases", {})
st.session_state.setdefault("form_version", {})
st.session_state.setdefault("flash", {})
st.session_state.setdefault("discard_pending", None)

with st.sidebar:
    st.header("Case")
    mode = st.radio("Source", ["Demo case (DenPAR test set)", "Upload case JSON"])
    if mode.startswith("Demo"):
        demos = _demo_cases()
        cid = st.selectbox("Case", list(demos))
        simulated = st.checkbox("Include simulated corrections", value=True,
                                help="Demo corrections move the two most-uncertain landmarks of each flagged "
                                     "tooth to the DenPAR reference. Untick to start from AI-only results.")
        source = copy.deepcopy(demos[cid])
        if not simulated:
            for t in source["teeth"]:
                t["manual"] = None
        case_key = f"demo|{cid}|{simulated}"
    else:
        up = st.file_uploader("Case JSON (input format, or a Week 7 report JSON)", type="json")
        if up is None:
            st.stop()
        raw = up.getvalue()
        data = json.loads(raw)
        source = data.get("input_case", data)
        case_key = upload_key(raw)
    if case_key not in st.session_state["cases"]:
        st.session_state["cases"][case_key] = copy.deepcopy(source)

    edited = [f"T{t.get('tooth_id')}" if not t.get("label") else t["label"]
              for t, o in zip(st.session_state["cases"][case_key].get("teeth") or [], source.get("teeth") or [])
              if t != o]
    if st.button("Discard my edits for this case", disabled=not edited, key=f"discard|{case_key}"):
        st.session_state["discard_pending"] = case_key
    if st.session_state["discard_pending"] == case_key and edited:
        st.warning(f"This clears the corrections you saved or removed in this session for {', '.join(edited)} "
                   "and restores the case as loaded. Exports you already downloaded are not affected.")
        k1, k2 = st.columns(2)
        if k1.button("Confirm discard", key=f"discard_ok|{case_key}"):
            st.session_state["cases"][case_key] = copy.deepcopy(source)
            st.session_state["form_version"][case_key] = st.session_state["form_version"].get(case_key, 0) + 1
            st.session_state["flash"].pop(case_key, None)
            st.session_state["discard_pending"] = None
            st.rerun()
        if k2.button("Cancel", key=f"discard_no|{case_key}"):
            st.session_state["discard_pending"] = None
            st.rerun()

case = st.session_state["cases"][case_key]
report = build_case_report(case)
s = report["summary"]
work = _workdir()
slug = safe_slug(report["case_id"])

st.subheader(f"Case {report['case_id']}")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Teeth in case", s["teeth_total"])
c2.metric("Highest tooth stage", s["highest_tooth_stage"] or "—")
c3.metric("Highest PBL", "—" if s["highest_pbl_pct"] is None else f"{s['highest_pbl_pct']:.1f}% ({s['highest_pbl_tooth']})")
c4.metric("Flagged for review", s["teeth_flagged"])
c5.metric("Teeth using corrected values", s["teeth_reported_from_manual"],
          help="Includes simulated edits in demo cases. Counts only edits used in the final report.")
for w in report["case_warnings"]:
    st.error(f"{w['code']}: {w['message']}")

image_path = resolve_image((case.get("image") or {}).get("path"))
fig = render_case_figure(report, image_path, work / f"{slug}_figure.png")
st.image(str(fig), width="stretch")

st.subheader("Tooth-level measurements")
rows = []
for t in report["teeth"]:
    f, a = t["final"], t["auto"]
    am = a["measurement"] if a else None
    rows.append({
        "Tooth": t["label"],
        "Reported from": source_label(t),
        "Mesial %": None if not f["mesial"] else round(f["mesial"]["pbl_pct"], 1),
        "Distal %": None if not f["distal"] else round(f["distal"]["pbl_pct"], 1),
        "PBL (worse) %": None if f["pbl_max_pct"] is None else round(f["pbl_max_pct"], 1),
        "Stage": f["stage"] or (f"≥{f['minimum_stage']}" if f["minimum_stage"] else "—"),
        "AI PBL %": None if not am or am["pbl_max_pct"] is None else round(am["pbl_max_pct"], 1),
        "AI stage": (am or {}).get("stage") or "—",
        "AI P(stage)": None if not a or a["stage_probability"] is None else round(a["stage_probability"], 2),
        "AI 95% interval": "—" if not a or not a["pbl_ci95"] else "{:.1f}–{:.1f}%".format(*a["pbl_ci95"]),
        "Flagged": "yes" if t["review_flagged"] else "",
        "Warnings": ", ".join(w["code"] for w in t["warnings"] if w["severity"] != "info"),
    })
st.dataframe(rows, width="stretch", hide_index=True)
with st.expander("How to read the tooth stage"):
    st.write("Each stage uses bone loss on this X-ray. The side with more bone loss sets the tooth stage. "
             "The report groups stages III and IV together.")
    st.write("A patient diagnosis also needs clinical findings. This report does not assess attachment loss, "
             "tooth loss, complexity or grade.")

st.subheader("Tooth review")
if report["teeth"]:
    labels = [f"{t['label']} (row {i + 1})" for i, t in enumerate(report["teeth"])]
    idx = st.selectbox("Selected tooth", range(len(labels)), format_func=lambda i: labels[i], key=f"tooth|{case_key}")
    t = report["teeth"][idx]
    tooth = case["teeth"][idx]
    same_label = sum(x["label"] == t["label"] for x in report["teeth"]) > 1
    tooth_name = labels[idx] if same_label else t["label"]  # add the row number if two teeth share an ID

    flash = st.session_state["flash"].get(case_key)
    if flash and flash["idx"] == idx:
        kind, text = _flash_text(t, flash)
        {"success": st.success, "info": st.info, "error": st.error}[kind](text)

    left, right = st.columns([1, 2])
    zoom = render_tooth_zoom(t, image_path, work / f"{slug}_tooth_{idx}.png")
    if zoom is not None:
        left.image(str(zoom), width="stretch")
    else:
        left.caption("No radiograph or tooth position available for a close-up.")
    with right:
        am = t["auto"]["measurement"] if t["auto"] else None
        st.markdown(f"**Reported from:** {source_label(t)}")
        st.markdown(f"**AI:** {_stage_text(am)}  →  **Reported:** {_stage_text(t['final'])}")
        if t["final"]["worse_surface"]:
            st.markdown(f"**Stage set by:** {t['final']['worse_surface']} surface "
                        f"({t['final'][t['final']['worse_surface']]['pbl_pct']:.1f}%)")
        m = t["manual"]
        if m:
            moved = []
            if m["changed_landmarks"]:
                moved.append("moved " + _names(m["changed_landmarks"]))
            if m["added_landmarks"]:
                moved.append("added " + _names(m["added_landmarks"]))
            if m["removed_landmarks"]:
                moved.append("removed " + _names(m["removed_landmarks"]))
            st.markdown("**Landmarks changed:** " + ("; ".join(moved) or "none"))
            st.caption(f"Correction by {m['reviewer_id'] or 'unknown'} at {m['saved_at_utc'] or '—'} · "
                       f"{m['method'] or 'method not recorded'}")
        st.write(t["interpretation"])
        if t["review_flagged"]:
            st.info("Review flag: " + "; ".join(t["review_reasons"]))
        for w in t["warnings"]:
            {"high": st.error, "medium": st.warning, "info": st.caption}[w["severity"]](f"{w['code']}: {w['message']}")
        if t["correction_history"]:
            st.markdown("**Correction history**")
            for k, e in enumerate(t["correction_history"], start=1):
                st.caption(history_line(k, e))

    st.markdown(f"#### Edit landmarks · {tooth_name}")
    st.caption("Enter pixel coordinates from the original X-ray. Leave a point blank if you cannot place it. "
               "Each save appears in the history beside the original prediction.")
    current = tooth.get("manual") or tooth.get("auto") or {}
    base = clean_landmarks(current.get("landmarks"))
    version = st.session_state["form_version"].get(case_key, 0)
    prefix = f"{case_key}|{idx}|{version}"  # separate form state for each case and tooth
    with st.form(f"form|{prefix}"):
        new: dict[str, list[float] | None] = {}
        cols = st.columns(5)
        for col, name in zip(cols, LANDMARK_NAMES):
            p = base[name]
            col.markdown(f"**{LANDMARK_LABELS[name]}**")
            x = col.number_input("x", value=None if p is None else p[0], key=f"{prefix}|{name}|x",
                                 step=1.0, format="%.2f", placeholder="not placed")
            y = col.number_input("y", value=None if p is None else p[1], key=f"{prefix}|{name}|y",
                                 step=1.0, format="%.2f", placeholder="not placed")
            new[name] = None if (x is None or y is None) else [float(x), float(y)]
        reviewer = st.text_input("Reviewer name or ID", value="", placeholder="e.g. Lucia Liao", key=f"{prefix}|reviewer")
        note = st.text_input("Note (optional)", value="", key=f"{prefix}|note")
        save = st.form_submit_button(f"Save correction for {tooth_name}")
    if save:
        if not reviewer.strip():
            st.error("Reviewer ID is required so the correction can be traced.")
        else:
            # Points the reviewer did not change keep their full precision.
            for name in LANDMARK_NAMES:
                if base[name] is not None and new[name] is not None and all(
                        round(a, 2) == round(b, 2) for a, b in zip(base[name], new[name])):
                    new[name] = base[name]
            record = {
                "landmarks": new,
                "reviewer_id": reviewer.strip(),
                "saved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "method": APP_METHOD,
                "note": note or None,
            }
            _history(tooth).append({"action": "save", **record})
            tooth["manual"] = record
            st.session_state["form_version"][case_key] = version + 1
            st.session_state["flash"][case_key] = {"idx": idx, "action": "save", "reviewer": reviewer.strip()}
            st.rerun()
    if tooth.get("manual"):
        remover = st.text_input("Reviewer ID for removal", value="", key=f"{prefix}|remover")
        if st.button(f"Remove correction for {tooth_name}", key=f"{prefix}|remove"):
            if not remover.strip():
                st.error("Reviewer ID is required to remove a correction.")
            else:
                _history(tooth).append({
                    "action": "remove", "reviewer_id": remover.strip(),
                    "saved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "method": APP_METHOD, "note": None,
                })
                tooth["manual"] = None
                st.session_state["form_version"][case_key] = version + 1
                st.session_state["flash"][case_key] = {"idx": idx, "action": "remove", "reviewer": remover.strip()}
                st.rerun()

with st.expander("All teeth: interpretation and warnings"):
    for t in report["teeth"]:
        st.markdown(f"**{t['label']}** — {source_label(t)} — {_stage_text(t['final'])}")
        st.write(t["interpretation"])
        codes = ", ".join(w["code"] for w in t["warnings"] if w["severity"] != "info")
        if codes:
            st.caption("Warnings: " + codes)

st.subheader("Export")
pdf_path = to_pdf(report, fig, work / f"{slug}.pdf")
e1, e2, e3 = st.columns(3)
e1.download_button("PDF case report", pdf_path.read_bytes(), f"{slug}.pdf", "application/pdf")
e2.download_button("CSV (tooth-level)", to_csv(report), f"{slug}.csv", "text/csv")
e3.download_button("JSON (complete case)", to_json(report, case), f"{slug}.json", "application/json")
