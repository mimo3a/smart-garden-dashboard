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


def history_buckets(minutes: int, max_points: int) -> list[dict]:
    """Return time-bucketed aggregated readings for the last *minutes* minutes.

    Splits the window into at most *max_points* even buckets and AVGs values
    per bucket entirely in SQL (no raw rows loaded into Python).

    Bucket numbering is relative to the cutoff epoch so that a window of
    T = minutes*60 seconds with bucket width b = T//max_points + 1 seconds
    always produces at most max_points buckets (proof: floor(T/b) ≤ N-1).

    Each entry: ts, air_temp_c, soil_temp_c, battery_percent,
    channels (list of {dev, ch, moisture_pct}).
    """
    now = _utcnow()
    cutoff_dt = now - timedelta(minutes=minutes)
    cutoff = cutoff_dt.isoformat()
    # Integer epoch of the cutoff; bucket indices are relative to this origin
    # so the entire window [0, T) maps to buckets [0, max_points).
    cutoff_epoch = int(cutoff_dt.timestamp())
    # b = T//N + 1 guarantees at most N buckets for any span ≤ T seconds.
    bucket_secs = (minutes * 60) // max_points + 1

    params = {"b": bucket_secs, "cutoff": cutoff, "ce": cutoff_epoch}

    conn = _connect(_DB_PATH)
    try:
        # ── reading-level aggregates ──────────────────────────────────────
        reading_rows = conn.execute(
            """
            SELECT
                CAST((CAST(strftime('%s', ts) AS INTEGER) - :ce) / :b AS INTEGER) AS bucket,
                MIN(ts)              AS ts,
                AVG(air_temp_c)      AS air_temp_c,
                AVG(soil_temp_c)     AS soil_temp_c,
                AVG(battery_percent) AS battery_percent
            FROM readings
            WHERE ts >= :cutoff
              AND strftime('%s', ts) IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket ASC
            """,
            params,
        ).fetchall()

        if not reading_rows:
            return []

        # ── channel-level aggregates (JOIN avoids a second trip per bucket) ─
        channel_rows = conn.execute(
            """
            SELECT
                CAST((CAST(strftime('%s', r.ts) AS INTEGER) - :ce) / :b AS INTEGER) AS bucket,
                cv.dev,
                cv.ch,
                AVG(cv.moisture_pct) AS moisture_pct
            FROM readings r
            JOIN channel_values cv ON cv.reading_id = r.id
            WHERE r.ts >= :cutoff
              AND strftime('%s', r.ts) IS NOT NULL
              AND cv.status = 'ok'
              AND cv.moisture_pct IS NOT NULL
            GROUP BY bucket, cv.dev, cv.ch
            ORDER BY bucket ASC, cv.dev ASC, cv.ch ASC
            """,
            params,
        ).fetchall()

        # ── merge ─────────────────────────────────────────────────────────
        buckets: dict[int, dict] = {}
        for row in reading_rows:
            buckets[row["bucket"]] = {
                "ts": row["ts"],
                "air_temp_c": row["air_temp_c"],
                "soil_temp_c": row["soil_temp_c"],
                "battery_percent": row["battery_percent"],
                "channels": [],
            }
        for row in channel_rows:
            b = buckets.get(row["bucket"])
            if b is not None:
                b["channels"].append({
                    "dev": row["dev"],
                    "ch": row["ch"],
                    "moisture_pct": row["moisture_pct"],
                })

        return list(buckets.values())
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
