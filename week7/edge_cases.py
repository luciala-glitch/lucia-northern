"""Four broken inputs made from a real demo case, to test missing and incomplete data.

The report should not give a stage when points are missing or wrong, and it
should list every problem as a warning.
"""

from __future__ import annotations

import copy
from typing import Any

from week7.cases import build_demo_cases


def _base() -> dict[str, Any]:
    cases = {c["case_id"]: c for c in build_demo_cases()}
    return copy.deepcopy(cases["DENPAR-TEST-5"])


def build_edge_cases() -> list[dict[str, Any]]:
    out = []

    c = _base()
    c["case_id"] = "EDGE-missing-apex"
    c["source"] = {**c["source"], "edge_case": "apex removed from T1 automated landmarks"}
    c["teeth"][0]["auto"]["landmarks"]["apex"] = None
    c["teeth"][0]["manual"] = None
    out.append(c)

    c = _base()
    c["case_id"] = "EDGE-one-surface"
    c["source"] = {**c["source"], "edge_case": "distal bone crest removed from T2; no correction"}
    c["teeth"][1]["auto"]["landmarks"]["distal_bc"] = None
    c["teeth"][1]["manual"] = None
    out.append(c)

    c = _base()
    c["case_id"] = "EDGE-invalid-correction"
    c["source"] = {**c["source"], "edge_case": "T3 correction puts mesial crest above the CEJ"}
    t = c["teeth"][2]
    bad = copy.deepcopy(t["auto"]["landmarks"])
    cej = bad["mesial_cej"]
    apex = bad["apex"]
    bad["mesial_bc"] = [cej[0] - 0.3 * (apex[0] - cej[0]), cej[1] - 0.3 * (apex[1] - cej[1])]
    t["manual"] = {"landmarks": bad, "reviewer_id": "edge-test", "saved_at_utc": "2026-11-19T12:00:00+00:00",
                   "method": "synthetic invalid correction", "note": None}
    out.append(c)

    out.append({
        "case_id": None,
        "image": {},
        "source": {"edge_case": "no case id, no image, one tooth with no data, duplicate id"},
        "teeth": [
            {"tooth_id": 1, "label": None, "arch": None, "site": None, "bbox": None, "auto": None, "manual": None},
            {"tooth_id": 1, "auto": {"landmarks": {"mesial_cej": [10, 10], "distal_cej": ["x", 10]}}},
        ],
    })
    return out
