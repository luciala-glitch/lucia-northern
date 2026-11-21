"""Make the PDF, CSV, JSON and figure for every demo case and edge case.

    python -m week7.build_reports            # writes week7/reports/
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from week7.cases import build_demo_cases, reference_values
from week7.edge_cases import build_edge_cases
from week7.export import safe_slug, to_csv, to_json, to_pdf
from week7.figures import render_case_figure
from week7.report import build_case_report, resolve_image

OUT = Path(__file__).resolve().parent / "reports"
FIXED_TIME = "2026-11-19T12:00:00+00:00"  # fixed time, so rebuilt files can be compared


def export_case(case: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    report = build_case_report(case, generated_at=FIXED_TIME)
    slug = safe_slug(report["case_id"])
    folder = out_dir / slug
    folder.mkdir(parents=True, exist_ok=True)
    image = resolve_image((case.get("image") or {}).get("path"))
    fig = render_case_figure(report, image, folder / f"{slug}_annotated.png")
    (folder / f"{slug}.csv").write_text(to_csv(report), encoding="utf-8")
    (folder / f"{slug}.json").write_text(to_json(report, case), encoding="utf-8")
    to_pdf(report, fig, folder / f"{slug}.pdf")
    return report


def main() -> None:
    cases_dir, edge_dir = OUT / "cases", OUT / "edge_cases"
    ref = reference_values()
    summary_rows = []
    for case in build_demo_cases():
        report = export_case(case, cases_dir)
        for t in report["teeth"]:
            r = ref[(report["case_id"], t["tooth_id"])]
            a = t["auto"]["measurement"]
            summary_rows.append({
                "case_id": report["case_id"],
                "tooth": t["label"],
                "auto_pbl": round(a["pbl_max_pct"], 2),
                "auto_stage": a["stage"],
                "auto_p_stage": round(t["auto"]["stage_probability"], 3),
                "flagged": t["review_flagged"],
                "corrected": t["manual"] is not None,
                "reported_source": t["final"]["source"],
                "reported_pbl": round(t["final"]["pbl_max_pct"], 2),
                "reported_stage": t["final"]["stage"],
                "reference_pbl": round(r["pbl_max_pct"], 2),
                "reference_stage": r["stage"],
                "warnings": ";".join(w["code"] for w in t["warnings"]),
            })
    for case in build_edge_cases():
        export_case(case, edge_dir)
    with (OUT / "all_cases_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)
    n = len(summary_rows)
    stats = {
        "cases": len({r["case_id"] for r in summary_rows}),
        "teeth": n,
        "flagged": sum(r["flagged"] for r in summary_rows),
        "corrected": sum(r["corrected"] for r in summary_rows),
        "auto_stage_agrees_with_reference": sum(r["auto_stage"] == r["reference_stage"] for r in summary_rows),
        "reported_stage_agrees_with_reference": sum(r["reported_stage"] == r["reference_stage"] for r in summary_rows),
        "note": "36 teeth from 19 radiographs: a demonstration sample, too small for accuracy claims. "
                "Corrections are simulated from the reference, so agreement after correction is optimistic.",
    }
    (OUT / "all_cases_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
