"""SQLite access layer – store and retrieve sensor readings."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.models import Reading

_DB_PATH: Path = Path("garden.db")
_write_lock = threading.Lock()

# Replaceable in tests via monkeypatch to freeze time.
_utcnow = lambda: datetime.now(tz=timezone.utc)  # noqa: E731


_CREATE_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    source          TEXT    NOT NULL,
    air_temp_c      REAL,
    soil_temp_c     REAL,
    battery_voltage REAL,
    battery_percent REAL
)
"""

_CREATE_CHANNEL_VALUES = """
CREATE TABLE IF NOT EXISTS channel_values (
    reading_id   INTEGER NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
    dev          INTEGER NOT NULL,
    ch           INTEGER NOT NULL,
    raw          INTEGER,
    status       TEXT,
    moisture_pct REAL,
    PRIMARY KEY (reading_id, dev, ch)
)
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Optional[Path] = None) -> None:
    """Create tables and indexes; call once at startup.

    Passing *path* overrides the default ``garden.db`` — intended for tests.
    """
    global _DB_PATH
    if path is not None:
        _DB_PATH = path

    with _write_lock:
        conn = _connect(_DB_PATH)
        try:
            conn.execute(_CREATE_READINGS)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS readings_ts ON readings (ts)"
            )
            conn.execute(_CREATE_CHANNEL_VALUES)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS channel_values_reading_id"
                " ON channel_values (reading_id)"
            )
            conn.commit()
        finally:
            conn.close()


def insert_reading(reading: Reading, source: str = "uart") -> None:
    """Persist one sensor snapshot and all its channels in one transaction."""
    ts = reading.timestamp.isoformat()
    batt_v = reading.battery.voltage if reading.battery else None
    batt_pct = reading.battery.percent if reading.battery else None

    with _write_lock:
        conn = _connect(_DB_PATH)
        try:
            cur = conn.execute(
                "INSERT INTO readings"
                " (ts, source, air_temp_c, soil_temp_c, battery_voltage, battery_percent)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (ts, source, reading.air_temp_c, reading.soil_temp_c, batt_v, batt_pct),
            )
            rid = cur.lastrowid
            conn.executemany(
                "INSERT INTO channel_values (reading_id, dev, ch, raw, status, moisture_pct)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (rid, ch.dev, ch.ch, ch.raw, ch.status, ch.moisture_pct)
                    for ch in reading.channels
                ],
            )
            conn.commit()
        finally:
            conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "source": row["source"],
        "air_temp_c": row["air_temp_c"],
        "soil_temp_c": row["soil_temp_c"],
        "battery_voltage": row["battery_voltage"],
        "battery_percent": row["battery_percent"],
        "channels": [],
    }


def latest_reading() -> Optional[dict]:
    """Return the most recent reading with its channels, or None if the table is empty."""
    conn = _connect(_DB_PATH)
    try:
        row = conn.execute(
            "SELECT * FROM readings ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        result = _row_to_dict(row)
        channels = conn.execute(
            "SELECT dev, ch, raw, status, moisture_pct"
            " FROM channel_values WHERE reading_id = ? ORDER BY dev, ch",
            (result["id"],),
        ).fetchall()
        result["channels"] = [dict(c) for c in channels]
        return result
    finally:
        conn.close()


def readings_since(minutes: int) -> list[dict]:
    """Return all readings from the last *minutes* minutes, oldest first.

    Each entry contains a ``channels`` list. Uses a single LEFT JOIN so
    there are no N+1 queries.
    """
    cutoff = (_utcnow() - timedelta(minutes=minutes)).isoformat()
    conn = _connect(_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.ts, r.source,
                   r.air_temp_c, r.soil_temp_c,
                   r.battery_voltage, r.battery_percent,
                   cv.dev, cv.ch, cv.raw, cv.status, cv.moisture_pct
            FROM readings r
            LEFT JOIN channel_values cv ON cv.reading_id = r.id
            WHERE r.ts >= ?
            ORDER BY r.ts ASC, r.id ASC, cv.dev ASC, cv.ch ASC
            """,
            (cutoff,),
        ).fetchall()

        # dict preserves insertion order (Python 3.7+), so ASC order is kept.
        readings_by_id: dict[int, dict] = {}
        for row in rows:
            rid = row["id"]
            if rid not in readings_by_id:
                readings_by_id[rid] = _row_to_dict(row)
            if row["dev"] is not None:  # LEFT JOIN row with no channel → dev is NULL
                readings_by_id[rid]["channels"].append({
                    "dev": row["dev"],
                    "ch": row["ch"],
                    "raw": row["raw"],
                    "status": row["status"],
                    "moisture_pct": row["moisture_pct"],
                })
        return list(readings_by_id.values())
    finally:
        conn.close()


def purge_older_than(days: int) -> int:
    """Delete readings (and their channels via CASCADE) older than *days* days.

    Returns the number of readings deleted.
    """
    cutoff = (_utcnow() - timedelta(days=days)).isoformat()
    with _write_lock:
        conn = _connect(_DB_PATH)
        try:
            cur = conn.execute("DELETE FROM readings WHERE ts < ?", (cutoff,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
