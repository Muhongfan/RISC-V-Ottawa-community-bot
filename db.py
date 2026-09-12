"""
SQLite persistence for the RISC-V onboarding bot.

Everything needed to resume a user's session after a bot restart lives here:
profile, current state, and PRIVATE misconception records. Nothing in this
module ever formats data for posting to a public channel -- that boundary is
enforced by keeping misconception data out of any "draft" object entirely.
"""

import sqlite3
import json
import time
from contextlib import contextmanager

DB_PATH = "riscv_bot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    goal TEXT,
    programming_level TEXT,
    hardware_experience TEXT,
    weekly_hours INTEGER,
    track TEXT,
    current_lab_code TEXT,
    selected_project TEXT,
    created_at REAL,
    updated_at REAL
);

-- Private. Never joined into any public-facing query/draft.
CREATE TABLE IF NOT EXISTS misconceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at REAL
);

-- Holds a drafted public post until the user explicitly confirms it.
CREATE TABLE IF NOT EXISTS pending_confirmations (
    user_id TEXT PRIMARY KEY,
    channel_id TEXT,
    draft_text TEXT,
    created_at REAL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def get_user(user_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_or_update_user(user_id: str, **fields):
    now = time.time()
    existing = get_user(user_id)
    with get_conn() as conn:
        if existing:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE users SET {sets}, updated_at = ? WHERE user_id = ?",
                (*fields.values(), now, user_id),
            )
        else:
            fields.setdefault("state", "PROFILE_IN_PROGRESS")
            cols = ["user_id", "created_at", "updated_at"] + list(fields.keys())
            vals = [user_id, now, now] + list(fields.values())
            placeholders = ", ".join("?" for _ in vals)
            conn.execute(
                f"INSERT INTO users ({', '.join(cols)}) VALUES ({placeholders})", vals
            )


def set_state(user_id: str, state: str):
    create_or_update_user(user_id, state=state)


def record_misconception(user_id: str, tag: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO misconceptions (user_id, tag, resolved, created_at) VALUES (?, ?, 0, ?)",
            (user_id, tag, time.time()),
        )


def resolve_misconception(user_id: str, tag: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE misconceptions SET resolved = 1 WHERE user_id = ? AND tag = ? "
            "AND id = (SELECT id FROM misconceptions WHERE user_id = ? AND tag = ? "
            "ORDER BY id DESC LIMIT 1)",
            (user_id, tag, user_id, tag),
        )


def stash_confirmation(user_id: str, channel_id: str, draft_text: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_confirmations (user_id, channel_id, draft_text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, channel_id, draft_text, time.time()),
        )


def get_confirmation(user_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pending_confirmations WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def clear_confirmation(user_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_confirmations WHERE user_id = ?", (user_id,))