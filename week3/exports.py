"""Strict assignment schema, metric recomputation, and lossless flattened CSV."""

from __future__ import annotations
import csv
from io import StringIO
import json
import math
from pathlib import Path
from typing import Any
import jsonschema
from week3.pbl_calculator import (
    SideLandmarks,
    ToothLandmarks,
    calculate_tooth_pbl,
    PBLValidationError,
)

SCHEMA_PATH = Path(__file__).with_name("measurement.schema.json")
SCHEMA = json.loads(SCHEMA_PATH.read_text())


def landmarks_from_record(record: dict[str, Any]) -> ToothLandmarks:
    lm = record["landmarks"]
    return ToothLandmarks(
        SideLandmarks(**lm["mesial"]), SideLandmarks(**lm["distal"]), tuple(lm["apex"])
    )


def make_record(
    image_id: str,
    tooth_id: int,
    condition: str,
    round_number: int,
    landmarks: ToothLandmarks,
) -> dict[str, Any]:
    # Integer pixel coordinates are required; do not silently round measurements.
    values = [
        landmarks.mesial.cej,
        landmarks.mesial.bc,
        landmarks.distal.cej,
        landmarks.distal.bc,
        landmarks.apex,
    ]
    if any(any(v != int(v) for v in p) for p in values):
        raise PBLValidationError(
            "Export requires integer original-image pixel coordinates"
        )
    result = calculate_tooth_pbl(landmarks)
    record = {
        "image_id": image_id,
        "tooth_id": tooth_id,
        "condition": condition,
        "round": round_number,
        "long_axis_vector": list(result.long_axis_vector),
        "landmarks": {
            "mesial": {
                "cej": list(map(int, landmarks.mesial.cej)),
                "bc": list(map(int, landmarks.mesial.bc)),
            },
            "distal": {
                "cej": list(map(int, landmarks.distal.cej)),
                "bc": list(map(int, landmarks.distal.bc)),
            },
            "apex": list(map(int, landmarks.apex)),
        },
        "metrics": {
            "mesial_pbl_pct": result.mesial.pbl_pct,
            "distal_pbl_pct": result.distal.pbl_pct,
            "pbl_max_pct": result.pbl_max_pct,
            "stage": result.stage,
        },
    }
    jsonschema.validate(record, SCHEMA)
    return record


INTEGER_FIELDS = ("tooth_id", "round")


def _same(stored: Any, expected: Any) -> bool:
    """Structural equality; floats agree to 1e-9 so platform rounding is tolerated."""
    if isinstance(expected, float):
        return isinstance(stored, (int, float)) and not isinstance(stored, bool) and (
            math.isclose(stored, expected, rel_tol=1e-9, abs_tol=1e-9)
        )
    if isinstance(expected, dict):
        return (
            isinstance(stored, dict)
            and stored.keys() == expected.keys()
            and all(_same(stored[k], expected[k]) for k in expected)
        )
    if isinstance(expected, list):
        return (
            isinstance(stored, list)
            and len(stored) == len(expected)
            and all(_same(a, b) for a, b in zip(stored, expected))
        )
    return type(stored) is type(expected) and stored == expected


def validate_record(record: dict[str, Any]) -> None:
    jsonschema.validate(record, SCHEMA)
    lm = record["landmarks"]
    coordinates = [*lm["mesial"].values(), *lm["distal"].values(), lm["apex"]]
    # JSON Schema accepts 1.0 as an integer; keep identities/pixels canonical ints.
    if any(type(record[f]) is not int for f in INTEGER_FIELDS) or any(
        type(v) is not int for p in coordinates for v in p
    ):
        raise PBLValidationError("IDs, rounds and pixel coordinates must be integers")
    expected = make_record(
        record["image_id"],
        record["tooth_id"],
        record["condition"],
        record["round"],
        landmarks_from_record(record),
    )
    if not _same(record, expected):
        raise PBLValidationError(
            "Stored metrics/axis do not match recomputed landmarks"
        )


def record_identity(record: dict[str, Any]) -> tuple:
    return (
        record["image_id"],
        record["tooth_id"],
        record["condition"],
        record["round"],
    )


def merge_records(
    existing: list[dict[str, Any]], incoming: object
) -> list[dict[str, Any]]:
    """Validate an imported array and append it without losing session records."""
    if not isinstance(incoming, list):
        raise ValueError("Expected a JSON array")
    seen = {record_identity(r) for r in existing}
    for record in incoming:
        validate_record(record)
        key = record_identity(record)
        if key in seen:
            raise ValueError(f"Duplicate measurement identity {key}")
        seen.add(key)
    return [*existing, *incoming]


def json_export(records: list[dict[str, Any]]) -> str:
    for record in records:
        validate_record(record)
    return json.dumps(records, indent=2, allow_nan=False) + "\n"


# Spreadsheet apps execute cells starting with these characters as formulas.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "'")
JSON_COLUMNS = ("long_axis_vector", "landmarks.")
FLOAT_COLUMNS = (
    "metrics.mesial_pbl_pct",
    "metrics.distal_pbl_pct",
    "metrics.pbl_max_pct",
)


def flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            out.update(flatten(item, name))
        elif isinstance(item, list):
            out[name] = json.dumps(item)
        elif isinstance(item, str) and item.startswith(FORMULA_PREFIXES):
            out[name] = "'" + item  # reversed by csv_import
        else:
            out[name] = item
    return out


def csv_export(records: list[dict[str, Any]]) -> str:
    json_export(records)
    buffer = StringIO()
    if records:
        rows = [flatten(r) for r in records]
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return buffer.getvalue()


def _parse_cell(name: str, text: str) -> Any:
    # Types come from the column name, never from cell content: an image_id
    # such as "[2024] scan.png" must stay a string.
    if name.startswith(JSON_COLUMNS):
        return json.loads(text)
    if name in INTEGER_FIELDS:
        return int(text)
    if name in FLOAT_COLUMNS:
        return float(text)
    if text.startswith("'") and text[1:].startswith(FORMULA_PREFIXES):
        return text[1:]
    return text


def csv_import(content: str) -> list[dict[str, Any]]:
    records = []
    for line, row in enumerate(csv.DictReader(StringIO(content)), start=2):
        if None in row or None in row.values():
            raise ValueError(f"CSV row {line} does not match the header")
        record: dict[str, Any] = {}
        for name, text in row.items():
            parts = name.split(".")
            target = record
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = _parse_cell(name, text)
        validate_record(record)
        records.append(record)
    return records
