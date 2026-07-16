"""SQLite persistence with per-trial commits."""
import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("LOCTEST_DB") or os.path.join(
    os.path.dirname(__file__), "localization.db"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant TEXT NOT NULL,
    condition TEXT NOT NULL,
    device_name TEXT NOT NULL,
    mode TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS cmaa_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    trial_index INTEGER NOT NULL,
    delta REAL NOT NULL,
    high_side INTEGER NOT NULL,
    response_side INTEGER,
    correct INTEGER,
    response_ms INTEGER,
    UNIQUE(session_id, trial_index)
);
CREATE TABLE IF NOT EXISTS abx_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    trial_index INTEGER NOT NULL,
    x_is_a INTEGER NOT NULL,
    response_is_a INTEGER,
    correct INTEGER,
    response_ms INTEGER,
    UNIQUE(session_id, trial_index)
);
CREATE TABLE IF NOT EXISTS ext_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    trial_index INTEGER NOT NULL,
    target_az REAL NOT NULL,
    rating INTEGER,
    response_ms INTEGER,
    UNIQUE(session_id, trial_index)
);
CREATE TABLE IF NOT EXISTS width_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    trial_index INTEGER NOT NULL,
    a_first INTEGER NOT NULL,
    chose_a INTEGER,
    response_ms INTEGER,
    UNIQUE(session_id, trial_index)
);
CREATE TABLE IF NOT EXISTS masked_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    trial_index INTEGER NOT NULL,
    level_db REAL NOT NULL,
    target_first INTEGER NOT NULL,
    response_first INTEGER,
    correct INTEGER,
    response_ms INTEGER,
    UNIQUE(session_id, trial_index)
);
CREATE TABLE IF NOT EXISTS pref_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    trial_index INTEGER NOT NULL,
    a_first INTEGER NOT NULL,
    chose_a INTEGER,
    response_ms INTEGER,
    UNIQUE(session_id, trial_index)
);
"""


@contextmanager
def connect():
    """Yield a connection that commits on success and always closes."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init():
    with connect() as connection:
        connection.executescript(SCHEMA)


def create_session(participant, condition, device_name, mode, config,
                   created_at):
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO sessions "
            "(participant, condition, device_name, mode, created_at, "
            "config_json) VALUES (?,?,?,?,?,?)",
            (
                participant, condition, device_name, mode, created_at,
                json.dumps(config),
            ),
        )
        return cursor.lastrowid


def save_trial(session_id, trial):
    """Insert or replace one localization trial."""
    with connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO trials "
            "(session_id, trial_index, target_az, response_az, "
            "signed_error, abs_error, front_back_confusion, "
            "left_right_confusion, replay_count, response_ms) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                trial["trial_index"],
                trial["target_az"],
                trial["response_az"],
                trial["signed_error"],
                trial["abs_error"],
                int(trial["front_back_confusion"]),
                int(trial["left_right_confusion"]),
                trial["replay_count"],
                trial["response_ms"],
            ),
        )


def save_cmaa_trial(session_id, trial):
    """Insert or replace one CMAA trial."""
    with connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO cmaa_trials "
            "(session_id, trial_index, delta, high_side, response_side, "
            "correct, response_ms) VALUES (?,?,?,?,?,?,?)",
            (
                session_id,
                trial["trial_index"],
                trial["delta"],
                trial["high_side"],
                trial["response_side"],
                trial["correct"],
                trial["response_ms"],
            ),
        )


def save_abx_trial(session_id, trial):
    """Insert or replace one ABX trial."""
    with connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO abx_trials "
            "(session_id, trial_index, x_is_a, response_is_a, correct, "
            "response_ms) VALUES (?,?,?,?,?,?)",
            (
                session_id,
                trial["trial_index"],
                trial["x_is_a"],
                trial["response_is_a"],
                trial["correct"],
                trial["response_ms"],
            ),
        )


def save_ext_trial(session_id, trial):
    """Insert or replace one externalization trial."""
    with connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO ext_trials "
            "(session_id, trial_index, target_az, rating, response_ms) "
            "VALUES (?,?,?,?,?)",
            (
                session_id,
                trial["trial_index"],
                trial["target_az"],
                trial["rating"],
                trial["response_ms"],
            ),
        )


def save_width_trial(session_id, trial):
    """Insert or replace one soundstage-width trial."""
    with connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO width_trials "
            "(session_id, trial_index, a_first, chose_a, response_ms) "
            "VALUES (?,?,?,?,?)",
            (
                session_id,
                trial["trial_index"],
                trial["a_first"],
                trial["chose_a"],
                trial["response_ms"],
            ),
        )


def save_masked_trial(session_id, trial):
    """Insert or replace one masked-detection trial."""
    with connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO masked_trials "
            "(session_id, trial_index, level_db, target_first, "
            "response_first, correct, response_ms) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                session_id,
                trial["trial_index"],
                trial["level_db"],
                trial["target_first"],
                trial["response_first"],
                trial["correct"],
                trial["response_ms"],
            ),
        )


def save_pref_trial(session_id, trial):
    """Insert or replace one preference A/B trial."""
    with connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO pref_trials "
            "(session_id, trial_index, a_first, chose_a, response_ms) "
            "VALUES (?,?,?,?,?)",
            (
                session_id,
                trial["trial_index"],
                trial["a_first"],
                trial["chose_a"],
                trial["response_ms"],
            ),
        )


def mark_completed(session_id):
    with connect() as connection:
        connection.execute(
            "UPDATE sessions SET completed = 1 WHERE id = ?",
            (session_id,),
        )


def get_session(session_id):
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def get_trials(session_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM trials "
            "WHERE session_id = ? AND response_az IS NOT NULL "
            "ORDER BY trial_index",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_cmaa_trials(session_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM cmaa_trials "
            "WHERE session_id = ? AND response_side IS NOT NULL "
            "ORDER BY trial_index",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_abx_trials(session_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM abx_trials "
            "WHERE session_id = ? AND response_is_a IS NOT NULL "
            "ORDER BY trial_index",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_ext_trials(session_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM ext_trials "
            "WHERE session_id = ? AND rating IS NOT NULL "
            "ORDER BY trial_index",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_width_trials(session_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM width_trials "
            "WHERE session_id = ? AND chose_a IS NOT NULL "
            "ORDER BY trial_index",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_masked_trials(session_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM masked_trials "
            "WHERE session_id = ? AND response_first IS NOT NULL "
            "ORDER BY trial_index",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_pref_trials(session_id):
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM pref_trials "
            "WHERE session_id = ? AND chose_a IS NOT NULL "
            "ORDER BY trial_index",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def completed_trial_indices(session_id):
    """Return answered localization trial indexes."""
    with connect() as connection:
        rows = connection.execute(
            "SELECT trial_index FROM trials "
            "WHERE session_id = ? AND response_az IS NOT NULL",
            (session_id,),
        ).fetchall()
        return {row["trial_index"] for row in rows}


def list_sessions():
    with connect() as connection:
        rows = connection.execute(
            "SELECT s.*, "
            "((SELECT COUNT(*) FROM trials t "
            "  WHERE t.session_id = s.id "
            "  AND t.response_az IS NOT NULL) + "
            " (SELECT COUNT(*) FROM cmaa_trials c "
            "  WHERE c.session_id = s.id "
            "  AND c.response_side IS NOT NULL) + "
            " (SELECT COUNT(*) FROM abx_trials a "
            "  WHERE a.session_id = s.id "
            "  AND a.response_is_a IS NOT NULL) + "
            " (SELECT COUNT(*) FROM ext_trials e "
            "  WHERE e.session_id = s.id "
            "  AND e.rating IS NOT NULL) + "
            " (SELECT COUNT(*) FROM width_trials w "
            "  WHERE w.session_id = s.id "
            "  AND w.chose_a IS NOT NULL) + "
            " (SELECT COUNT(*) FROM masked_trials m "
            "  WHERE m.session_id = s.id "
            "  AND m.response_first IS NOT NULL) + "
            " (SELECT COUNT(*) FROM pref_trials p "
            "  WHERE p.session_id = s.id "
            "  AND p.chose_a IS NOT NULL)) AS n_trials "
            "FROM sessions s ORDER BY s.created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


if __name__ == "__main__":
    import tempfile

    DB_PATH = os.path.join(
        tempfile.gettempdir(), "loctest_selfcheck.db"
    )
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init()

    sid = create_session(
        "P1", "ROG_APO", "Speakers 7.1", "main",
        {"seed": 5, "azimuth_step": 30, "reps": 6},
        "2026-07-12T10:00:00",
    )
    trial = {
        "trial_index": 0,
        "target_az": 30.0,
        "response_az": 28.0,
        "signed_error": -2.0,
        "abs_error": 2.0,
        "front_back_confusion": False,
        "left_right_confusion": False,
        "replay_count": 1,
        "response_ms": 1500,
    }
    save_trial(sid, trial)
    assert completed_trial_indices(sid) == {0}
    assert len(get_trials(sid)) == 1

    trial["response_az"] = 32.0
    save_trial(sid, trial)
    assert len(get_trials(sid)) == 1
    assert get_trials(sid)[0]["response_az"] == 32.0

    cmaa_sid = create_session(
        "P2", "ROG_APO", "Speakers 7.1", "cmaa",
        {
            "seed": 7,
            "output_mode": "folddown",
            "peak_dbfs": -12,
            "ref_az": 0,
            "test_type": "cmaa",
        },
        "2026-07-12T11:00:00",
    )
    cmaa_trial = {
        "trial_index": 0,
        "delta": 15.0,
        "high_side": 1,
        "response_side": 1,
        "correct": 1,
        "response_ms": 900,
    }
    save_cmaa_trial(cmaa_sid, cmaa_trial)
    assert len(get_cmaa_trials(cmaa_sid)) == 1

    cmaa_trial["response_side"] = -1
    cmaa_trial["correct"] = 0
    save_cmaa_trial(cmaa_sid, cmaa_trial)
    saved = get_cmaa_trials(cmaa_sid)
    assert len(saved) == 1
    assert saved[0]["response_side"] == -1

    new_sid = create_session(
        "P3", "ROG_APO", "Speakers 7.1", "new-tests",
        {"seed": 9},
        "2026-07-12T12:00:00",
    )

    abx_trial = {
        "trial_index": 0,
        "x_is_a": 1,
        "response_is_a": 1,
        "correct": 1,
        "response_ms": 800,
    }
    save_abx_trial(new_sid, abx_trial)
    assert len(get_abx_trials(new_sid)) == 1
    abx_trial["response_is_a"] = 0
    abx_trial["correct"] = 0
    save_abx_trial(new_sid, abx_trial)
    saved = get_abx_trials(new_sid)
    assert len(saved) == 1
    assert saved[0]["response_is_a"] == 0

    ext_trial = {
        "trial_index": 0,
        "target_az": 45.0,
        "rating": 4,
        "response_ms": 1100,
    }
    save_ext_trial(new_sid, ext_trial)
    assert len(get_ext_trials(new_sid)) == 1
    ext_trial["rating"] = 5
    save_ext_trial(new_sid, ext_trial)
    saved = get_ext_trials(new_sid)
    assert len(saved) == 1
    assert saved[0]["rating"] == 5

    width_trial = {
        "trial_index": 0,
        "a_first": 1,
        "chose_a": 0,
        "response_ms": 950,
    }
    save_width_trial(new_sid, width_trial)
    assert len(get_width_trials(new_sid)) == 1
    width_trial["chose_a"] = 1
    save_width_trial(new_sid, width_trial)
    saved = get_width_trials(new_sid)
    assert len(saved) == 1
    assert saved[0]["chose_a"] == 1

    masked_trial = {
        "trial_index": 0,
        "level_db": -32.0,
        "target_first": 1,
        "response_first": 1,
        "correct": 1,
        "response_ms": 1000,
    }
    save_masked_trial(new_sid, masked_trial)
    assert len(get_masked_trials(new_sid)) == 1
    masked_trial["response_first"] = 0
    masked_trial["correct"] = 0
    save_masked_trial(new_sid, masked_trial)
    saved = get_masked_trials(new_sid)
    assert len(saved) == 1
    assert saved[0]["response_first"] == 0

    pref_trial = {
        "trial_index": 0,
        "a_first": 0,
        "chose_a": 1,
        "response_ms": 875,
    }
    save_pref_trial(new_sid, pref_trial)
    assert len(get_pref_trials(new_sid)) == 1
    pref_trial["chose_a"] = 0
    save_pref_trial(new_sid, pref_trial)
    saved = get_pref_trials(new_sid)
    assert len(saved) == 1
    assert saved[0]["chose_a"] == 0

    sessions = list_sessions()
    assert sessions[0]["n_trials"] == 5
    assert sessions[1]["n_trials"] == 1
    assert sessions[2]["n_trials"] == 1

    mark_completed(sid)
    assert get_session(sid)["completed"] == 1

    os.remove(DB_PATH)
    print("db.py selfcheck OK")
