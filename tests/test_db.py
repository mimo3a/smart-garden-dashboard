"""Tests for app.db – SQLite persistence layer."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

import app.db as db_module
from app.db import init_db, insert_reading, latest_reading, purge_older_than, readings_since
from app.models import AdcChannel, BatteryReading, Reading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def make_reading(
    *,
    ts: datetime | None = None,
    moisture: float = 55.0,
    raw: int = 18000,
    air_temp: float = 22.0,
    soil_temp: float = 18.0,
    battery_v: float = 3.9,
    battery_pct: float = 75.0,
) -> Reading:
    return Reading(
        timestamp=ts or _now(),
        channels=[
            AdcChannel(dev=0, ch=0, raw=raw, status="ok", moisture_pct=moisture),
            AdcChannel(dev=0, ch=1, raw=raw, status="ok", moisture_pct=moisture),
            AdcChannel(dev=1, ch=2, raw=raw, status="err", moisture_pct=None),
        ],
        air_temp_c=air_temp,
        soil_temp_c=soil_temp,
        battery=BatteryReading(voltage=battery_v, percent=battery_pct),
    )


@pytest.fixture(autouse=False)
def tmp_db(tmp_path):
    """Initialise a fresh DB in a temp directory and point the module at it."""
    path = tmp_path / "test.db"
    init_db(path)
    yield path


@pytest.fixture()
def frozen_db(tmp_path, monkeypatch):
    """DB with _utcnow frozen to _FIXED_NOW for deterministic time-window tests."""
    path = tmp_path / "frozen.db"
    init_db(path)
    monkeypatch.setattr(db_module, "_utcnow", lambda: _FIXED_NOW)
    yield path


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_creates_readings_table(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='readings'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_creates_channel_values_table(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='channel_values'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_creates_ts_index(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='readings_ts'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_creates_channel_values_index(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND name='channel_values_reading_id'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_idempotent(self, tmp_db):
        init_db(tmp_db)  # second call must not raise


# ---------------------------------------------------------------------------
# insert_reading
# ---------------------------------------------------------------------------

class TestInsertReading:
    def test_insert_does_not_raise(self, tmp_db):
        insert_reading(make_reading(), source="test")

    def test_readings_row_count_increments(self, tmp_db):
        insert_reading(make_reading(), source="test")
        insert_reading(make_reading(), source="test")
        conn = sqlite3.connect(str(tmp_db))
        count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        conn.close()
        assert count == 2

    def test_ok_channel_values_stored(self, tmp_db):
        insert_reading(make_reading(moisture=60.0, raw=17000), source="test")
        row = latest_reading()
        ch = next(c for c in row["channels"] if c["dev"] == 0 and c["ch"] == 0)
        assert ch["moisture_pct"] == pytest.approx(60.0)
        assert ch["raw"] == 17000
        assert ch["status"] == "ok"

    def test_second_ok_channel_stored(self, tmp_db):
        insert_reading(make_reading(moisture=42.0, raw=19500), source="test")
        row = latest_reading()
        ch = next(c for c in row["channels"] if c["dev"] == 0 and c["ch"] == 1)
        assert ch["moisture_pct"] == pytest.approx(42.0)
        assert ch["status"] == "ok"

    def test_err_channel_stored_correctly(self, tmp_db):
        insert_reading(make_reading(), source="test")
        row = latest_reading()
        ch = next(c for c in row["channels"] if c["dev"] == 1 and c["ch"] == 2)
        assert ch["status"] == "err"
        assert ch["moisture_pct"] is None

    def test_all_three_channels_stored(self, tmp_db):
        insert_reading(make_reading(), source="test")
        row = latest_reading()
        assert len(row["channels"]) == 3

    def test_dev7_channel_stored(self, tmp_db):
        """Channels with dev >= 4 must be stored without clipping or silently dropped."""
        r = Reading(
            timestamp=_now(),
            channels=[
                AdcChannel(dev=7, ch=3, raw=22000, status="ok", moisture_pct=30.0),
            ],
        )
        insert_reading(r, source="test")
        row = latest_reading()
        assert len(row["channels"]) == 1
        ch = row["channels"][0]
        assert ch["dev"] == 7
        assert ch["ch"] == 3
        assert ch["raw"] == 22000
        assert ch["moisture_pct"] == pytest.approx(30.0)

    def test_battery_stored(self, tmp_db):
        insert_reading(make_reading(battery_v=3.75, battery_pct=60.0), source="test")
        row = latest_reading()
        assert row["battery_voltage"] == pytest.approx(3.75)
        assert row["battery_percent"] == pytest.approx(60.0)

    def test_temps_stored(self, tmp_db):
        insert_reading(make_reading(air_temp=25.5, soil_temp=19.2), source="test")
        row = latest_reading()
        assert row["air_temp_c"] == pytest.approx(25.5)
        assert row["soil_temp_c"] == pytest.approx(19.2)

    def test_source_stored(self, tmp_db):
        insert_reading(make_reading(), source="simulator")
        assert latest_reading()["source"] == "simulator"

    def test_no_battery_stored_as_null(self, tmp_db):
        r = Reading(
            timestamp=_now(),
            channels=[AdcChannel(dev=0, ch=0, raw=15000, status="ok", moisture_pct=55.0)],
        )
        insert_reading(r, source="test")
        row = latest_reading()
        assert row["battery_voltage"] is None
        assert row["battery_percent"] is None

    def test_no_temps_stored_as_null(self, tmp_db):
        r = Reading(
            timestamp=_now(),
            channels=[AdcChannel(dev=0, ch=0, raw=15000, status="ok", moisture_pct=55.0)],
        )
        insert_reading(r, source="test")
        row = latest_reading()
        assert row["air_temp_c"] is None
        assert row["soil_temp_c"] is None

    def test_reading_with_no_channels_stores_empty_list(self, tmp_db):
        r = Reading(timestamp=_now(), channels=[], air_temp_c=21.0)
        insert_reading(r, source="test")
        row = latest_reading()
        assert row["channels"] == []
        assert row["air_temp_c"] == pytest.approx(21.0)

    def test_cascade_channels_deleted_with_reading(self, tmp_db):
        insert_reading(make_reading(), source="test")
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("PRAGMA foreign_keys=ON")
        rid = conn.execute("SELECT id FROM readings").fetchone()[0]
        conn.execute("DELETE FROM readings WHERE id = ?", (rid,))
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM channel_values").fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# latest_reading
# ---------------------------------------------------------------------------

class TestLatestReading:
    def test_empty_db_returns_none(self, tmp_db):
        assert latest_reading() is None

    def test_returns_most_recent_by_timestamp(self, tmp_db):
        now = _now()
        insert_reading(
            Reading(timestamp=now - timedelta(minutes=30), channels=[], air_temp_c=20.0),
            source="test",
        )
        insert_reading(
            Reading(timestamp=now - timedelta(minutes=5), channels=[], air_temp_c=25.0),
            source="test",
        )
        assert latest_reading()["air_temp_c"] == pytest.approx(25.0)

    def test_returns_dict(self, tmp_db):
        insert_reading(make_reading(), source="test")
        assert isinstance(latest_reading(), dict)

    def test_channels_key_present(self, tmp_db):
        insert_reading(make_reading(), source="test")
        assert "channels" in latest_reading()

    def test_channels_contain_dev_and_ch(self, tmp_db):
        insert_reading(make_reading(), source="test")
        for ch in latest_reading()["channels"]:
            assert "dev" in ch and "ch" in ch

    def test_ts_field_present(self, tmp_db):
        insert_reading(make_reading(), source="test")
        row = latest_reading()
        assert "ts" in row and row["ts"]


# ---------------------------------------------------------------------------
# readings_since
# ---------------------------------------------------------------------------

class TestReadingsSince:
    def test_empty_db_returns_empty_list(self, tmp_db):
        assert readings_since(60) == []

    def test_recent_reading_included(self, tmp_db):
        insert_reading(make_reading(ts=_now() - timedelta(minutes=10)), source="test")
        assert len(readings_since(30)) == 1

    def test_old_reading_excluded(self, tmp_db):
        insert_reading(make_reading(ts=_now() - timedelta(hours=2)), source="test")
        assert readings_since(60) == []

    def test_cutoff_is_inclusive(self, frozen_db):
        """ts >= cutoff is inclusive: a reading timestamped exactly at the cutoff is returned,
        while one 1 second earlier is not."""
        cutoff = _FIXED_NOW - timedelta(minutes=60)
        insert_reading(
            Reading(timestamp=cutoff, channels=[], air_temp_c=1.0), source="test"
        )
        insert_reading(
            Reading(timestamp=cutoff - timedelta(seconds=1), channels=[], air_temp_c=2.0),
            source="test",
        )
        temps = [r["air_temp_c"] for r in readings_since(60)]
        assert 1.0 in temps       # exactly at cutoff → included by >=
        assert 2.0 not in temps   # 1 second before cutoff → excluded

    def test_results_ordered_ascending(self, tmp_db):
        now = _now()
        insert_reading(
            Reading(timestamp=now - timedelta(minutes=20), channels=[], air_temp_c=10.0),
            source="test",
        )
        insert_reading(
            Reading(timestamp=now - timedelta(minutes=5), channels=[], air_temp_c=20.0),
            source="test",
        )
        rows = readings_since(60)
        assert rows[0]["air_temp_c"] == pytest.approx(10.0)
        assert rows[1]["air_temp_c"] == pytest.approx(20.0)

    def test_returns_list_of_dicts(self, tmp_db):
        insert_reading(make_reading(), source="test")
        rows = readings_since(60)
        assert isinstance(rows, list) and isinstance(rows[0], dict)

    def test_channels_included_in_result(self, tmp_db):
        insert_reading(make_reading(), source="test")
        row = readings_since(60)[0]
        assert "channels" in row
        assert len(row["channels"]) == 3

    def test_mixed_old_and_new(self, tmp_db):
        now = _now()
        insert_reading(
            Reading(timestamp=now - timedelta(hours=3), channels=[], air_temp_c=5.0),
            source="test",
        )
        insert_reading(
            Reading(timestamp=now - timedelta(minutes=10), channels=[], air_temp_c=20.0),
            source="test",
        )
        rows = readings_since(60)
        assert len(rows) == 1
        assert rows[0]["air_temp_c"] == pytest.approx(20.0)

    def test_reading_with_no_channels_has_empty_list(self, tmp_db):
        r = Reading(timestamp=_now(), channels=[], air_temp_c=15.0)
        insert_reading(r, source="test")
        row = readings_since(10)[0]
        assert row["channels"] == []


# ---------------------------------------------------------------------------
# purge_older_than
# ---------------------------------------------------------------------------

class TestPurgeOlderThan:
    def test_empty_db_returns_zero(self, frozen_db):
        assert purge_older_than(30) == 0

    def test_purges_old_readings(self, frozen_db):
        insert_reading(
            Reading(timestamp=_FIXED_NOW - timedelta(days=10), channels=[], air_temp_c=1.0),
            source="test",
        )
        insert_reading(
            Reading(timestamp=_FIXED_NOW - timedelta(hours=1), channels=[], air_temp_c=2.0),
            source="test",
        )
        deleted = purge_older_than(7)
        assert deleted == 1
        assert latest_reading()["air_temp_c"] == pytest.approx(2.0)

    def test_returns_count_of_deleted_rows(self, frozen_db):
        for i in range(3):
            insert_reading(
                Reading(
                    timestamp=_FIXED_NOW - timedelta(days=10 + i),
                    channels=[],
                    air_temp_c=float(i),
                ),
                source="test",
            )
        assert purge_older_than(7) == 3

    def test_within_threshold_not_deleted(self, frozen_db):
        insert_reading(
            Reading(timestamp=_FIXED_NOW - timedelta(days=3), channels=[], air_temp_c=5.0),
            source="test",
        )
        assert purge_older_than(7) == 0
        assert latest_reading() is not None

    def test_cascade_deletes_channel_values(self, frozen_db):
        r = Reading(
            timestamp=_FIXED_NOW - timedelta(days=10),
            channels=[AdcChannel(dev=0, ch=0, raw=15000, status="ok", moisture_pct=55.0)],
        )
        insert_reading(r, source="test")
        purge_older_than(7)
        conn = sqlite3.connect(str(frozen_db))
        count = conn.execute("SELECT COUNT(*) FROM channel_values").fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_inserts_all_succeed(self, tmp_db):
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(10):
                    insert_reading(make_reading(), source="thread")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

        conn = sqlite3.connect(str(tmp_db))
        count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        conn.close()
        assert count == 50

    def test_concurrent_reads_while_writing(self, tmp_db):
        errors: list[Exception] = []
        stop = threading.Event()

        def writer() -> None:
            for _ in range(20):
                try:
                    insert_reading(make_reading(), source="writer")
                except Exception as exc:
                    errors.append(exc)

        def reader() -> None:
            while not stop.is_set():
                try:
                    latest_reading()
                    readings_since(60)
                except Exception as exc:
                    errors.append(exc)

        reader_threads = [threading.Thread(target=reader) for _ in range(3)]
        writer_thread = threading.Thread(target=writer)

        for t in reader_threads:
            t.start()
        writer_thread.start()
        writer_thread.join()
        stop.set()
        for t in reader_threads:
            t.join()

        assert errors == [], f"Concurrent read/write errors: {errors}"
