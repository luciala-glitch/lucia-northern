"""Durable local studies, fixed tooth locations and transactional duplicate protection."""

from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from week3.exports import validate_record

DEFAULT_SETTINGS = {
    "mode": "routine",
    "target": None,
    "conditions": ["raw"],
    "rounds": 1,
}
LEGACY_SETTINGS = {
    "mode": "research",
    "target": 15,
    "conditions": ["raw", "he", "clahe"],
    "rounds": 2,
}


class StudyStore:
    def __init__(self, path=None):
        self.path = Path(
            path
            or os.environ.get(
                "PBL_STUDY_DB", Path(__file__).with_name("data") / "studies.sqlite3"
            )
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS studies(id TEXT PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP, archived INTEGER DEFAULT 0);
            CREATE UNIQUE INDEX IF NOT EXISTS one_active ON studies(archived) WHERE archived=0;
            CREATE TABLE IF NOT EXISTS images(study TEXT, name TEXT, digest TEXT, data BLOB, PRIMARY KEY(study,name));
            CREATE TABLE IF NOT EXISTS teeth(study TEXT, id INTEGER, image TEXT, x INTEGER, y INTEGER, confirmed INTEGER DEFAULT 1, PRIMARY KEY(study,id));
            CREATE TABLE IF NOT EXISTS records(study TEXT, tooth INTEGER, condition TEXT, round INTEGER, payload TEXT, PRIMARY KEY(study,tooth,condition,round));
            CREATE TABLE IF NOT EXISTS settings(study TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE IF NOT EXISTS amendments(study TEXT, tooth INTEGER, condition TEXT, round INTEGER, payload TEXT, created TEXT, reason TEXT, reopened TEXT);
            CREATE TABLE IF NOT EXISTS drafts(study TEXT, tooth INTEGER, condition TEXT, round INTEGER, payload TEXT, PRIMARY KEY(study,tooth,condition,round));
            """)
            # Existing studies retain their original research plan on first upgrade.
            db.execute(
                "INSERT OR IGNORE INTO settings SELECT id, ? FROM studies",
                (json.dumps(LEGACY_SETTINGS),),
            )
            # Additive upgrades only: existing rows keep NULL (unknown), never guessed.
            for table, column in (("images", "midline"), ("records", "created")):
                existing = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    kind = "INTEGER" if column == "midline" else "TEXT"
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def connect(self):
        """One transaction per block; the connection is always closed afterwards."""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def active(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM studies WHERE archived=0").fetchone()
            if row:
                return row["id"]
            sid = uuid4().hex
            db.execute("INSERT INTO studies(id) VALUES(?)", (sid,))
            db.execute(
                "INSERT INTO settings VALUES(?,?)", (sid, json.dumps(DEFAULT_SETTINGS))
            )
            return sid

    @staticmethod
    def writable(db, sid):
        if not db.execute(
            "SELECT 1 FROM studies WHERE id=? AND archived=0", (sid,)
        ).fetchone():
            raise ValueError(
                "This study was archived. Reopen the current study before recording."
            )

    def image(self, sid, name, data):
        digest = hashlib.sha256(data).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            row = db.execute(
                "SELECT digest FROM images WHERE study=? AND name=?", (sid, name)
            ).fetchone()
            if row and row["digest"] != digest:
                raise ValueError(
                    "A different image has this filename. Rename it before adding it."
                )
            db.execute(
                "INSERT OR IGNORE INTO images(study,name,digest,data) VALUES(?,?,?,?)",
                (sid, name, digest, data),
            )
        return digest

    def midline(self, sid, name):
        """Confirmed dental-midline x for an image, or None if not yet confirmed."""
        with self.connect() as db:
            row = db.execute(
                "SELECT midline FROM images WHERE study=? AND name=?", (sid, name)
            ).fetchone()
            return row["midline"] if row else None

    def set_midline(self, sid, name, x, width):
        # -1 / width encode a midline beyond the left / right edge (periapicals).
        if type(x) is not int or not -1 <= x <= width:
            raise ValueError("Midline must be an integer pixel column.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            if not db.execute(
                "UPDATE images SET midline=? WHERE study=? AND name=?", (x, sid, name)
            ).rowcount:
                raise ValueError("Add this image first.")

    def image_data(self, sid, name):
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM images WHERE study=? AND name=?", (sid, name)
            ).fetchone()
            return bytes(row["data"]) if row else None

    def teeth(self, sid):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM teeth WHERE study=? ORDER BY id", (sid,)
                )
            ]

    def register(self, sid, image, xy, size):
        x, y = xy
        if any(type(v) is not int for v in xy) or not (
            0 <= x < size[0] and 0 <= y < size[1]
        ):
            raise ValueError("Choose a location inside the image.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            if not db.execute(
                "SELECT 1 FROM images WHERE study=? AND name=?", (sid, image)
            ).fetchone():
                raise ValueError("Add this image first.")
            teeth = list(db.execute("SELECT * FROM teeth WHERE study=?", (sid,)))
            for t in teeth:
                if (
                    t["image"] == image
                    and ((t["x"] - x) ** 2 + (t["y"] - y) ** 2) ** 0.5 < size[0] * 0.025
                ):
                    raise ValueError(
                        f"This location is close to Tooth {t['id']}. Select that tooth instead; each physical tooth needs one ID."
                    )
            tid = next(
                i for i in range(1, len(teeth) + 2) if i not in {t["id"] for t in teeth}
            )
            db.execute("INSERT INTO teeth VALUES(?,?,?,?,?,1)", (sid, tid, image, x, y))
            return tid

    def records(self, sid):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM records WHERE study=? ORDER BY tooth,condition,round",
                    (sid,),
                )
            ]

    def record_times(self, sid):
        """UTC save time per (tooth, condition, round); None for imported records."""
        with self.connect() as db:
            return {
                (r["tooth"], r["condition"], r["round"]): r["created"]
                for r in db.execute(
                    "SELECT tooth,condition,round,created FROM records WHERE study=?",
                    (sid,),
                )
            }

    def save(self, sid, record):
        validate_record(record)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            t = db.execute(
                "SELECT * FROM teeth WHERE study=? AND id=?", (sid, record["tooth_id"])
            ).fetchone()
            if not t or t["image"] != record["image_id"] or not t["confirmed"]:
                raise ValueError(
                    "Register and confirm this tooth on its fixed image first."
                )
            try:
                db.execute(
                    "INSERT INTO records(study,tooth,condition,round,payload,created)"
                    " VALUES(?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                    (
                        sid,
                        record["tooth_id"],
                        record["condition"],
                        record["round"],
                        json.dumps(record),
                    ),
                )
            except sqlite3.IntegrityError:
                raise ValueError(
                    "This tooth is already recorded for this condition and round."
                ) from None
            db.execute(
                "DELETE FROM drafts WHERE study=? AND tooth=? AND condition=? AND round=?",
                (sid, record["tooth_id"], record["condition"], record["round"]),
            )

    def reopen(self, sid, tid, condition, rnd, reason):
        """Move a recorded reading to the amendment log so it can be re-marked.

        The original payload, its save time and the reason are kept; nothing is
        deleted from the study's history.
        """
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ValueError("Give a short reason (at least 5 characters).")
        key = (sid, tid, condition, rnd)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            row = db.execute(
                "SELECT payload, created FROM records WHERE study=? AND tooth=? AND condition=? AND round=?",
                key,
            ).fetchone()
            if not row:
                raise ValueError("Only a recorded reading can be reopened.")
            db.execute(
                "INSERT INTO amendments VALUES(?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (*key, row["payload"], row["created"], reason),
            )
            db.execute(
                "DELETE FROM records WHERE study=? AND tooth=? AND condition=? AND round=?",
                key,
            )

    def amendments(self, sid):
        with self.connect() as db:
            return [
                {
                    "tooth_id": r["tooth"],
                    "condition": r["condition"],
                    "round": r["round"],
                    "reason": r["reason"],
                    "originally_saved": r["created"],
                    "reopened": r["reopened"],
                    "original_record": json.loads(r["payload"]),
                }
                for r in db.execute(
                    "SELECT * FROM amendments WHERE study=? ORDER BY rowid", (sid,)
                )
            ]

    def draft(self, sid, tid, condition, rnd, points=None):
        key = (sid, tid, condition, rnd)
        with self.connect() as db:
            if points is None:
                row = db.execute(
                    "SELECT payload FROM drafts WHERE study=? AND tooth=? AND condition=? AND round=?",
                    key,
                ).fetchone()
                return json.loads(row[0]) if row else {}
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            if db.execute(
                "SELECT 1 FROM records WHERE study=? AND tooth=? AND condition=? AND round=?",
                key,
            ).fetchone():
                return
            db.execute(
                "INSERT OR REPLACE INTO drafts VALUES(?,?,?,?,?)",
                (*key, json.dumps(points)),
            )

    def restart(self, sid):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            db.execute("UPDATE studies SET archived=1 WHERE id=?", (sid,))
            new = uuid4().hex
            db.execute("INSERT INTO studies(id) VALUES(?)", (new,))
            db.execute(
                "INSERT INTO settings VALUES(?,?)", (new, json.dumps(DEFAULT_SETTINGS))
            )
            return new

    def archives(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,created,(SELECT COUNT(*) FROM records WHERE study=studies.id) AS count FROM studies WHERE archived=1 ORDER BY rowid DESC"
                )
            ]

    def resume(self, sid):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM studies WHERE id=? AND archived=1", (sid,)
            ).fetchone():
                raise ValueError("Archived study not found.")
            db.execute("UPDATE studies SET archived=1 WHERE archived=0")
            db.execute("UPDATE studies SET archived=0 WHERE id=?", (sid,))

    def migrate(self, sid, records):
        """Atomic legacy import. Keep uncertain locations explicitly unconfirmed."""
        for r in records:
            validate_record(r)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            for r in records:
                key = (sid, r["tooth_id"], r["condition"], r["round"])
                old = db.execute(
                    "SELECT payload FROM records WHERE study=? AND tooth=? AND condition=? AND round=?",
                    key,
                ).fetchone()
                if old and json.loads(old[0]) != r:
                    raise ValueError(
                        "Import conflicts with a saved record. No records were changed."
                    )
                t = db.execute(
                    "SELECT image FROM teeth WHERE study=? AND id=?",
                    (sid, r["tooth_id"]),
                ).fetchone()
                if t and t[0] != r["image_id"]:
                    raise ValueError(
                        "One study ID refers to different images. Import into a separate study."
                    )
                a, b = r["landmarks"]["mesial"]["cej"], r["landmarks"]["distal"]["cej"]
                db.execute(
                    "INSERT OR IGNORE INTO teeth VALUES(?,?,?,?,?,0)",
                    (
                        sid,
                        r["tooth_id"],
                        r["image_id"],
                        (a[0] + b[0]) // 2,
                        (a[1] + b[1]) // 2,
                    ),
                )
                db.execute(
                    "INSERT OR IGNORE INTO records(study,tooth,condition,round,payload)"
                    " VALUES(?,?,?,?,?)",
                    (*key, json.dumps(r)),
                )

    def confirm(self, sid, tid):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            db.execute(
                "UPDATE teeth SET confirmed=1 WHERE study=? AND id=?", (sid, tid)
            )

    def settings(self, sid):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM settings WHERE study=?", (sid,)
            ).fetchone()
            if not row:
                raise ValueError("Study settings not found.")
            return json.loads(row[0])

    def configure(self, sid, mode, target=None, conditions=None, rounds=1):
        if mode not in ("routine", "research"):
            raise ValueError("Choose routine or research mode.")
        if mode == "routine":
            target, conditions, rounds = None, ["raw"], 1
        if target is not None and (type(target) is not int or target < 1):
            raise ValueError("Target tooth count must be a positive integer.")
        if (
            not isinstance(conditions, list)
            or not conditions
            or len(set(conditions)) != len(conditions)
            or any(c not in ("raw", "he", "clahe") for c in conditions)
        ):
            raise ValueError("Select at least one valid image condition.")
        if type(rounds) is not int or rounds < 1:
            raise ValueError("Reading rounds must be a positive integer.")
        value = dict(mode=mode, target=target, conditions=conditions, rounds=rounds)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.writable(db, sid)
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES(?,?)", (sid, json.dumps(value))
            )


def reading_order(ids, seed):
    """Deterministic shuffle per reading, so a refresh keeps the same order but
    each condition/round presents teeth in a different sequence (less recall)."""
    import random

    order = list(ids)
    random.Random(seed).shuffle(order)
    return order
