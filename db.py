"""SQLite persistence. Per-trial commit so a crash loses at most the current trial."""
import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "localization.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant TEXT NOT NULL,
    condition TEXT NOT NULL,
    device_name TEXT NOT NULL,
    mode TEXT NOT NULL,              -- 'practice' | 'main'
    created_at TEXT NOT NULL,
    config_json TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    trial_index INTEGER NOT NULL,
    target_az REAL NOT NULL,
    response_az REAL,
    signed_error REAL,
    abs_error REAL,
    front_back_confusion INTEGER,
    left_right_confusion INTEGER,
    replay_count INTEGER NOT NULL DEFAULT 0,
    response_ms INTEGER,
    UNIQUE(session_id, trial_index)
);
"""


@contextmanager
def connect():
    """Connection that commits on success and always closes (Windows file-lock safety)."""
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with connect() as c:
        c.executescript(SCHEMA)


def create_session(participant, condition, device_name, mode, config, created_at):
    with connect() as c:
        cur = c.execute(
            "INSERT INTO sessions (participant, condition, device_name, mode, created_at, config_json) "
            "VALUES (?,?,?,?,?,?)",
            (participant, condition, device_name, mode, created_at, json.dumps(config)),
        )
        return cur.lastrowid


def save_trial(session_id, trial):
    """Insert or replace one trial. Committed immediately (context-manager commit)."""
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO trials "
            "(session_id, trial_index, target_az, response_az, signed_error, abs_error, "
            " front_back_confusion, left_right_confusion, replay_count, response_ms) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                session_id, trial["trial_index"], trial["target_az"], trial["response_az"],
                trial["signed_error"], trial["abs_error"],
                int(trial["front_back_confusion"]), int(trial["left_right_confusion"]),
                trial["replay_count"], trial["response_ms"],
            ),
        )


def mark_completed(session_id):
    with connect() as c:
        c.execute("UPDATE sessions SET completed = 1 WHERE id = ?", (session_id,))


def get_session(session_id):
    with connect() as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_trials(session_id):
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM trials WHERE session_id = ? AND response_az IS NOT NULL "
            "ORDER BY trial_index", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def completed_trial_indices(session_id):
    """trial_index set that already has a response -- for resume."""
    with connect() as c:
        rows = c.execute(
            "SELECT trial_index FROM trials WHERE session_id = ? AND response_az IS NOT NULL",
            (session_id,)
        ).fetchall()
        return {r["trial_index"] for r in rows}


def list_sessions():
    with connect() as c:
        rows = c.execute(
            "SELECT s.*, "
            "(SELECT COUNT(*) FROM trials t WHERE t.session_id = s.id AND t.response_az IS NOT NULL) "
            "AS n_trials FROM sessions s ORDER BY s.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    # Self-check on a temp DB.
    import tempfile
    DB_PATH = os.path.join(tempfile.gettempdir(), "loctest_selfcheck.db")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init()
    sid = create_session("P1", "ROG_APO", "Speakers 7.1", "main",
                         {"seed": 5, "azimuth_step": 30, "reps": 6}, "2026-07-12T10:00:00")
    t = dict(trial_index=0, target_az=30.0, response_az=28.0, signed_error=-2.0, abs_error=2.0,
             front_back_confusion=False, left_right_confusion=False, replay_count=1, response_ms=1500)
    save_trial(sid, t)
    assert completed_trial_indices(sid) == {0}
    assert len(get_trials(sid)) == 1
    # Replace same index (idempotent per-trial commit).
    t["response_az"] = 32.0
    save_trial(sid, t)
    assert len(get_trials(sid)) == 1 and get_trials(sid)[0]["response_az"] == 32.0
    mark_completed(sid)
    assert get_session(sid)["completed"] == 1
    assert list_sessions()[0]["n_trials"] == 1
    os.remove(DB_PATH)
    print("db.py selfcheck OK")
