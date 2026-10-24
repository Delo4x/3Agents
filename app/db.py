"""SQLite storage: events (live feed), opinions, trades, equity."""
import json
import os
import sqlite3
import threading
import time

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init(_conn)
    return _conn


def _init(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, agent TEXT, kind TEXT, text TEXT, data TEXT
        );
        CREATE TABLE IF NOT EXISTS opinions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, agent TEXT, symbol TEXT, bias TEXT, confidence INTEGER, reason TEXT
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, side TEXT, units REAL, entry REAL, sl REAL, tp REAL,
            opened_ts REAL, closed_ts REAL, exit REAL, pnl REAL, status TEXT,
            confidence REAL, risk_pct REAL, reason TEXT, close_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS equity (
            ts REAL PRIMARY KEY, balance REAL
        );
        CREATE TABLE IF NOT EXISTS seen (
            key TEXT PRIMARY KEY, ts REAL
        );
        """
    )
    c.commit()


def execute(sql: str, params: tuple = ()) -> int:
    with _lock:
        cur = conn().execute(sql, params)
        conn().commit()
        return cur.lastrowid


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, params).fetchall()]


def add_event(agent: str, kind: str, text: str, data: dict | None = None) -> dict:
    ts = time.time()
    eid = execute(
        "INSERT INTO events (ts, agent, kind, text, data) VALUES (?,?,?,?,?)",
        (ts, agent, kind, text, json.dumps(data or {}, ensure_ascii=False)),
    )
    return {"id": eid, "ts": ts, "agent": agent, "kind": kind, "text": text, "data": data or {}}


def recent_events(limit: int = 200) -> list[dict]:
    rows = query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["data"] = json.loads(r["data"] or "{}")
    return list(reversed(rows))


def mark_seen(key: str) -> bool:
    """Returns True if the key is new."""
    with _lock:
        try:
            conn().execute("INSERT INTO seen (key, ts) VALUES (?,?)", (key, time.time()))
            conn().commit()
            return True
        except sqlite3.IntegrityError:
            return False


def prune() -> None:
    week = time.time() - 7 * 86400
    execute("DELETE FROM seen WHERE ts < ?", (week,))
    execute("DELETE FROM events WHERE ts < ?", (time.time() - 3 * 86400,))
