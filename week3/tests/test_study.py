"""Critical persistence scenarios, using isolated local databases."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from week3.study import StudyStore
from week3.exports import make_record
from week3.pbl_calculator import ToothLandmarks, SideLandmarks


def record(tid=1, condition="raw", rnd=1):
    return make_record(
        "sample.jpg",
        tid,
        condition,
        rnd,
        ToothLandmarks(
            SideLandmarks((40, 20), (40, 40)),
            SideLandmarks((60, 20), (60, 50)),
            (50, 120),
        ),
    )


@pytest.fixture
def prepared(tmp_path):
    s = StudyStore(tmp_path / "study.sqlite3")
    sid = s.active()
    s.image(sid, "sample.jpg", b"original")
    s.register(sid, "sample.jpg", (50, 20), (200, 200))
    return s, sid


def test_reload_and_round_condition_identity(prepared):
    s, sid = prepared
    for condition in ["raw", "he", "clahe"]:
        for rnd in [1, 2]:
            s.save(sid, record(condition=condition, rnd=rnd))
    with pytest.raises(ValueError, match="already recorded"):
        s.save(sid, record())
    reopened = StudyStore(s.path)
    assert reopened.active() == sid and len(reopened.records(sid)) == 6
    assert len(reopened.teeth(sid)) == 1


def test_double_save_is_atomic(prepared):
    s, sid = prepared

    def save(_):
        try:
            s.save(sid, record())
            return "saved"
        except ValueError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, range(2))) == ["duplicate", "saved"]
    assert len(s.records(sid)) == 1


def test_draft_survives_reload_but_not_other_readings(prepared):
    s, sid = prepared
    p = {"mesial.cej": [40, 20]}
    s.draft(sid, 1, "raw", 1, p)
    assert StudyStore(s.path).draft(sid, 1, "raw", 1) == p
    assert s.draft(sid, 1, "he", 1) == {} and s.draft(sid, 1, "raw", 2) == {}
    s.save(sid, record())
    assert s.draft(sid, 1, "raw", 1) == {}
    s.draft(sid, 1, "raw", 1, p)
    assert s.draft(sid, 1, "raw", 1) == {}


def test_restart_archive_resume_and_stale_writer(prepared):
    s, sid = prepared
    s.save(sid, record())
    s.draft(sid, 1, "he", 1, {"apex": [50, 120]})
    new = s.restart(sid)
    assert s.active() == new and s.teeth(new) == [] and s.records(new) == []
    assert s.archives()[0]["count"] == 1
    for operation in [
        lambda: s.save(sid, record(condition="he")),
        lambda: s.register(sid, "sample.jpg", (150, 20), (200, 200)),
        lambda: s.draft(sid, 1, "he", 1, {}),
    ]:
        with pytest.raises(ValueError, match="archived"):
            operation()
    s.resume(sid)
    assert s.active() == sid and len(s.records(sid)) == 1
    assert s.image_data(sid, "sample.jpg") == b"original"
    assert s.draft(sid, 1, "he", 1) == {"apex": [50, 120]}


def test_registration_guards(prepared):
    s, sid = prepared
    with pytest.raises(ValueError, match="close to Tooth 1"):
        s.register(sid, "sample.jpg", (51, 20), (200, 200))
    with pytest.raises(ValueError, match="inside"):
        s.register(sid, "sample.jpg", (-1, 20), (200, 200))
    with pytest.raises(ValueError, match="different image"):
        s.image(sid, "sample.jpg", b"other")
    with pytest.raises(ValueError, match="Register and confirm"):
        s.save(sid, record(tid=2))
    s.image(sid, "other.jpg", b"other")
    for n in range(2, 16):
        s.register(sid, "other.jpg", (n * 10, 100), (200, 200))
    s.register(sid, "other.jpg", (190, 100), (200, 200))
    assert len(s.teeth(sid)) == 16


def test_migration_is_atomic_and_requires_location_confirmation(tmp_path):
    s = StudyStore(tmp_path / "study.db")
    sid = s.active()
    s.migrate(sid, [record()])
    assert not s.teeth(sid)[0]["confirmed"]
    with pytest.raises(ValueError, match="confirm"):
        s.save(sid, record(condition="he"))
    s.confirm(sid, 1)
    s.save(sid, record(condition="he"))
    conflicting = record(rnd=2)
    conflicting["image_id"] = "other.jpg"
    with pytest.raises(ValueError, match="different images"):
        s.migrate(sid, [record(tid=2), conflicting])
    assert [t["id"] for t in s.teeth(sid)] == [1]
    assert len(s.records(sid)) == 2
    with pytest.raises(ValueError, match="conflicts"):
        r = record()
        r["landmarks"]["mesial"]["bc"] = [40, 45]
        # Generate a valid but different record, rather than relying on schema failure.
        from week3.exports import landmarks_from_record

        s.migrate(
            sid, [make_record("sample.jpg", 1, "raw", 1, landmarks_from_record(r))]
        )
    assert (
        s.records(sid)[1 if s.records(sid)[0]["condition"] == "he" else 0] == record()
    )


def test_new_routine_and_configured_plan_survive_restart(prepared):
    s, sid = prepared
    assert s.settings(sid) == dict(
        mode="routine", target=None, conditions=["raw"], rounds=1
    )
    s.save(sid, record())
    s.configure(sid, "research", 5, ["raw", "clahe"], 3)
    s.draft(sid, 1, "clahe", 3, {"mesial.cej": [40, 20]})
    reopened = StudyStore(s.path)
    assert reopened.settings(sid)["rounds"] == 3
    s.configure(sid, "routine")
    assert s.records(sid) == [record()]
    assert s.draft(sid, 1, "clahe", 3) == {"mesial.cej": [40, 20]}
    new = s.restart(sid)
    assert s.settings(new)["mode"] == "routine"
    s.resume(sid)
    assert s.settings(sid)["mode"] == "routine"


def test_existing_database_keeps_legacy_plan(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE studies(id TEXT PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP, archived INTEGER DEFAULT 0)"
        )
        db.execute("INSERT INTO studies(id) VALUES('existing')")
    db.close()
    s = StudyStore(path)
    assert s.settings("existing") == dict(
        mode="research", target=15, conditions=["raw", "he", "clahe"], rounds=2
    )
    s.configure("existing", "research", 3, ["he"], 4)
    assert StudyStore(path).settings("existing")["target"] == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(mode="bad"),
        dict(mode="research", conditions=[]),
        dict(mode="research", conditions=["x"]),
        dict(mode="research", conditions=["raw"], rounds=0),
        dict(mode="research", conditions=["raw"], target=0),
    ],
)
def test_invalid_settings_do_not_change_plan(prepared, kwargs):
    s, sid = prepared
    before = s.settings(sid)
    with pytest.raises(ValueError):
        s.configure(sid, **kwargs)
    assert s.settings(sid) == before


def test_upgrade_adds_timestamp_and_midline_columns_without_touching_rows(tmp_path):
    path = tmp_path / "before_upgrade.db"
    db = sqlite3.connect(path)
    with db:
        db.executescript("""
        CREATE TABLE studies(id TEXT PRIMARY KEY, created TEXT, archived INTEGER DEFAULT 0);
        CREATE TABLE images(study TEXT, name TEXT, digest TEXT, data BLOB, PRIMARY KEY(study,name));
        CREATE TABLE records(study TEXT, tooth INTEGER, condition TEXT, round INTEGER, payload TEXT, PRIMARY KEY(study,tooth,condition,round));
        INSERT INTO studies(id) VALUES('old');
        INSERT INTO images VALUES('old','x.png','d',x'00');
        INSERT INTO records VALUES('old',1,'raw',1,'{}');
        """)
    db.close()
    s = StudyStore(path)
    # Unknown history stays unknown rather than being backfilled with a guess.
    assert s.record_times("old") == {(1, "raw", 1): None}
    assert s.midline("old", "x.png") is None
    StudyStore(path)  # a second open must not try to add the columns again


def test_saved_records_are_timestamped_and_midline_is_validated(prepared):
    s, sid = prepared
    s.save(sid, record())
    created = s.record_times(sid)[(1, "raw", 1)]
    assert created.endswith("Z") and len(created) == 20
    s.set_midline(sid, "sample.jpg", 50, 100)
    assert s.midline(sid, "sample.jpg") == 50
    s.set_midline(sid, "sample.jpg", -1, 100)  # midline beyond the left edge
    assert s.midline(sid, "sample.jpg") == -1
    for bad in (101, -2, 5.0, True):
        with pytest.raises(ValueError):
            s.set_midline(sid, "sample.jpg", bad, 100)
    with pytest.raises(ValueError):
        s.set_midline(sid, "missing.png", 10, 100)


def test_orientation_helpers():
    from PIL import Image
    import numpy as np
    from week3.orientation import (
        estimate_midline,
        is_panoramic,
        mesial_side,
        swapped_surfaces,
    )

    # A mirror-symmetric pattern about column 120 of a 200-px-wide image.
    xs = np.arange(200)
    row = (np.abs(xs - 120) * 7 % 255).astype(np.uint8)
    image = Image.fromarray(np.tile(row, (60, 1)))
    x, score = estimate_midline(image)
    assert abs(x - 120) <= 1 and score > 0.8
    assert is_panoramic((2041, 1024)) and not is_panoramic((800, 1000))
    assert mesial_side(50, 100) == "right"
    assert mesial_side(150, 100) == "left"
    assert mesial_side(50, -1) == "left"  # midline beyond the left edge
    assert mesial_side(50, None) is None and mesial_side(100, 100) is None
    points = {"mesial.cej": (40, 0), "distal.cej": (60, 0), "mesial.bc": (70, 5),
              "distal.bc": (50, 5)}
    assert swapped_surfaces(points, "right") == ["cej"]
    assert swapped_surfaces(points, "left") == ["bc"]
    assert swapped_surfaces(points, None) == []
    with pytest.raises(ValueError):
        estimate_midline(Image.new("L", (10, 10)))


def test_reopen_moves_reading_to_amendment_log(prepared):
    s, sid = prepared
    s.save(sid, record())
    with pytest.raises(ValueError):
        s.reopen(sid, 1, "raw", 1, "  ")
    with pytest.raises(ValueError):
        s.reopen(sid, 1, "he", 1, "misclick on crest")  # nothing recorded there
    s.reopen(sid, 1, "raw", 1, "misclick on crest")
    assert s.records(sid) == []
    (entry,) = s.amendments(sid)
    assert entry["original_record"] == record()
    assert entry["originally_saved"] and entry["reopened"].endswith("Z")
    s.save(sid, record())  # the reading can be recorded again
    assert len(s.records(sid)) == 1
    s.restart(sid)
    with pytest.raises(ValueError):
        s.reopen(sid, 1, "raw", 1, "archived studies are read-only")


def test_reading_order_is_reproducible_and_differs_between_readings():
    from week3.study import reading_order

    ids = list(range(1, 16))
    first = reading_order(ids, "study:raw:1")
    assert first == reading_order(ids, "study:raw:1")
    assert sorted(first) == ids
    assert first != reading_order(ids, "study:raw:2")
