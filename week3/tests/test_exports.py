import copy
import json
import jsonschema
import pytest
from dataclasses import replace
from week3.exports import (
    make_record,
    json_export,
    csv_export,
    csv_import,
    validate_record,
)
from week3.pbl_calculator import PBLValidationError
from week3.comparison import compare_conditions
from week3.tests.test_engine import tooth


def record(condition="raw", rnd=1):
    return make_record("fixture", 1, condition, rnd, tooth())


def test_json_csv_lossless_roundtrip():
    records = [record(), record("clahe", 2), record("he")]
    assert json.loads(json_export(records)) == records
    assert csv_import(csv_export(records)) == records
    assert csv_export([]) == ""
    assert json_export([]).strip() == "[]"


@pytest.mark.parametrize(
    "field,value",
    [
        ("condition", "unknown"),
        ("tooth_id", "1"),
        ("tooth_id", True),
        ("round", 0),
        ("image_id", ""),
    ],
)
def test_schema_metadata(field, value):
    r = record()
    r[field] = value
    with pytest.raises(jsonschema.ValidationError):
        validate_record(r)


def test_semantic_and_schema_validation():
    r = record()
    r["metrics"]["mesial_pbl_pct"] = 99
    with pytest.raises(PBLValidationError):
        validate_record(r)
    r = record()
    r["extra"] = "forbidden"
    with pytest.raises(jsonschema.ValidationError):
        validate_record(r)
    r = record()
    r["landmarks"]["apex"][0] = 1.25
    with pytest.raises(jsonschema.ValidationError):
        validate_record(r)
    with pytest.raises(PBLValidationError):
        make_record("f", 1, "raw", 1, replace(tooth(), apex=(50.5, 120)))


def test_missing_contrast_is_not_reported_as_zero_variance():
    out = compare_conditions([record()])
    assert out["matched_triplets"] == 0
    assert out["conditions"]["raw"]["coordinate_rmsd_vs_raw_px"] is None
    with pytest.raises(ValueError):
        compare_conditions([record(), record()])


def test_matched_contrast_and_repeat_variance():
    records = [record(c, r) for c in ("raw", "he", "clahe") for r in (1, 2)]
    # Translate all landmarks on he by (3,4); matching PBL/axis unchanged.
    from week3.pbl_calculator import ToothLandmarks, SideLandmarks

    for r in (1, 2):
        lm = tooth()

        def shift(p):
            return (p[0] + 3, p[1] + 4)

        changed = ToothLandmarks(
            SideLandmarks(shift(lm.mesial.cej), shift(lm.mesial.bc)),
            SideLandmarks(shift(lm.distal.cej), shift(lm.distal.bc)),
            shift(lm.apex),
        )
        records = [
            x for x in records if not (x["condition"] == "he" and x["round"] == r)
        ]
        records.append(make_record("fixture", 1, "he", r, changed))
    out = compare_conditions(records)
    assert out["matched_triplets"] == 2
    assert out["conditions"]["he"]["coordinate_rmsd_vs_raw_px"] == 5
    assert out["conditions"]["raw"]["coordinate_rmsd_vs_raw_px"] is None
    assert out["conditions"]["he"]["round_coordinate_rmsd_px"] == 0
    assert out["conditions"]["he"]["mean_within_landmark_coordinate_variance_px2"] == 0


@pytest.mark.parametrize(
    "image_id", ["[scan].png", "[1]", "=HYPERLINK(1)", "-1", "@x", "'quoted", "123"]
)
def test_csv_types_follow_columns_and_escape_formulas(image_id):
    r = make_record(image_id, 1, "raw", 1, tooth())
    text = csv_export([r])
    assert not text.splitlines()[1].startswith(("=", "+", "-", "@"))
    assert csv_import(text) == [r]


@pytest.mark.parametrize(
    "content", ["image_id,tooth_id\nabc\n", "image_id,tooth_id\na,1,extra\n"]
)
def test_malformed_csv_rows_raise_value_error(content):
    with pytest.raises(ValueError):
        csv_import(content)


def test_recomputed_metrics_tolerate_rounding_but_not_float_ids():
    r = record()
    r["metrics"]["mesial_pbl_pct"] += 1e-13
    validate_record(r)
    for path, value in [(("tooth_id",), 1.0), (("landmarks", "apex"), [50.0, 120])]:
        r = copy.deepcopy(record())
        target = r
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(PBLValidationError):
            validate_record(r)


def test_merge_records_appends_and_rejects_duplicates():
    from week3.exports import merge_records

    existing = [record()]
    merged = merge_records(existing, [record("he")])
    assert merged == [record(), record("he")]
    assert existing == [record()]
    with pytest.raises(ValueError):
        merge_records(existing, [record()])
    with pytest.raises(ValueError):
        merge_records([], [record("he"), record("he")])
    with pytest.raises(ValueError):
        merge_records([], {"not": "a list"})
