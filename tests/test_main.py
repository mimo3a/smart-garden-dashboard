"""API tests for app.main using FastAPI TestClient."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import re

import app.db as db_module
import app.main as main_module
from app.db import init_db, insert_reading
from app.main import _row_to_reading
from app.models import AdcChannel, BatteryReading, Reading
from app.serial_reader import DataSource

# Frozen reference time used by deterministic time-window tests.
_FIXED_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# NullDataSource – no background thread, no inserts
# ---------------------------------------------------------------------------

class NullDataSource(DataSource):
    def start(self, callback) -> None:
        pass

    def stop(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient backed by a fresh temp DB with no background simulator."""
    db_path = tmp_path / "test.db"

    monkeypatch.setattr(main_module, "_args", argparse.Namespace(
        db=str(db_path),
        keep_days=30,
        simulate=True,
        port=None,
        baud=115200,
        host="127.0.0.1",
    ))
    # Replace SimulatorReader so the lifespan starts nothing in the background.
    monkeypatch.setattr(main_module, "SimulatorReader", lambda: NullDataSource())

    # Pre-initialise DB so tests can insert data before (and after) TestClient starts.
    init_db(db_path)

    with TestClient(main_module.app) as c:
        yield c


@pytest.fixture()
def frozen_client(tmp_path, monkeypatch):
    """client with db._utcnow frozen to _FIXED_NOW for deterministic bucket tests."""
    db_path = tmp_path / "frozen.db"

    monkeypatch.setattr(main_module, "_args", argparse.Namespace(
        db=str(db_path),
        keep_days=30,
        simulate=True,
        port=None,
        baud=115200,
        host="127.0.0.1",
    ))
    monkeypatch.setattr(main_module, "SimulatorReader", lambda: NullDataSource())
    monkeypatch.setattr(db_module, "_utcnow", lambda: _FIXED_NOW)

    init_db(db_path)

    with TestClient(main_module.app) as c:
        yield c


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def make_reading(
    *,
    ts: datetime | None = None,
    air_temp: float = 22.0,
    soil_temp: float = 18.0,
    battery_v: float = 3.9,
    battery_pct: float = 75.0,
) -> Reading:
    # Values chosen to be within all default thresholds so no alerts fire normally.
    return Reading(
        timestamp=ts or _now(),
        channels=[
            AdcChannel(dev=0, ch=0, raw=15000, status="ok", moisture_pct=55.0),
            AdcChannel(dev=0, ch=1, raw=16000, status="ok", moisture_pct=40.0),
        ],
        air_temp_c=air_temp,
        soil_temp_c=soil_temp,
        battery=BatteryReading(voltage=battery_v, percent=battery_pct),
    )


# ---------------------------------------------------------------------------
# GET /api/latest
# ---------------------------------------------------------------------------

class TestApiLatest:
    def test_404_when_db_empty(self, client):
        assert client.get("/api/latest").status_code == 404

    def test_200_after_insert(self, client):
        insert_reading(make_reading(), source="test")
        assert client.get("/api/latest").status_code == 200

    def test_response_shape(self, client):
        insert_reading(make_reading(), source="test")
        body = client.get("/api/latest").json()
        for key in ("ts", "source", "air_temp_c", "channels"):
            assert key in body

    def test_channels_present(self, client):
        insert_reading(make_reading(), source="test")
        body = client.get("/api/latest").json()
        assert isinstance(body["channels"], list)
        assert len(body["channels"]) == 2

    def test_channel_moisture_value(self, client):
        insert_reading(make_reading(), source="test")
        body = client.get("/api/latest").json()
        ch = next(c for c in body["channels"] if c["dev"] == 0 and c["ch"] == 0)
        assert ch["moisture_pct"] == pytest.approx(55.0)

    def test_returns_most_recent_reading(self, client):
        now = _now()
        insert_reading(Reading(timestamp=now - timedelta(minutes=5), channels=[], air_temp_c=10.0), source="test")
        insert_reading(Reading(timestamp=now - timedelta(minutes=1), channels=[], air_temp_c=20.0), source="test")
        body = client.get("/api/latest").json()
        assert body["air_temp_c"] == pytest.approx(20.0)

    def test_battery_in_response(self, client):
        insert_reading(make_reading(battery_pct=80.0), source="test")
        body = client.get("/api/latest").json()
        assert body["battery_percent"] == pytest.approx(80.0)

    def test_source_field_present(self, client):
        insert_reading(make_reading(), source="uart")
        body = client.get("/api/latest").json()
        assert body["source"] == "uart"

    def test_alerts_key_present(self, client):
        insert_reading(make_reading(), source="test")
        body = client.get("/api/latest").json()
        assert "alerts" in body

    def test_alerts_is_list(self, client):
        insert_reading(make_reading(), source="test")
        body = client.get("/api/latest").json()
        assert isinstance(body["alerts"], list)

    def test_alerts_empty_for_normal_reading(self, client):
        # make_reading: moisture ~55 %, temp 22/18 °C, battery 75 % – all within thresholds
        insert_reading(make_reading(), source="test")
        body = client.get("/api/latest").json()
        assert body["alerts"] == []

    def test_alerts_triggered_for_low_moisture(self, client):
        r = Reading(
            timestamp=_now(),
            channels=[AdcChannel(dev=0, ch=0, raw=25500, status="ok", moisture_pct=5.0)],
        )
        insert_reading(r, source="test")
        body = client.get("/api/latest").json()
        assert any(a["type"] == "soil_moisture_low" for a in body["alerts"])

    def test_alerts_triggered_for_sensor_error(self, client):
        r = Reading(
            timestamp=_now(),
            channels=[AdcChannel(dev=0, ch=0, raw=0, status="err", moisture_pct=None)],
        )
        insert_reading(r, source="test")
        body = client.get("/api/latest").json()
        assert any(a["type"] == "sensor_error" for a in body["alerts"])

    def test_alerts_triggered_for_high_air_temp(self, client):
        insert_reading(make_reading(air_temp=40.0), source="test")
        body = client.get("/api/latest").json()
        assert any(a["type"] == "air_temp_high" for a in body["alerts"])

    def test_alerts_triggered_for_low_battery(self, client):
        insert_reading(make_reading(battery_pct=5.0, battery_v=3.06), source="test")
        body = client.get("/api/latest").json()
        assert any(a["type"] == "battery_low" for a in body["alerts"])


# ---------------------------------------------------------------------------
# GET /api/history
# ---------------------------------------------------------------------------

class TestApiHistory:
    def test_empty_db_returns_empty_list(self, client):
        r = client.get("/api/history?minutes=60&max_points=300")
        assert r.status_code == 200
        assert r.json() == []

    def test_default_params_accepted(self, client):
        assert client.get("/api/history").status_code == 200

    # ── parameter validation ────────────────────────────────────────────────

    def test_minutes_below_minimum_rejected(self, client):
        assert client.get("/api/history?minutes=0").status_code == 422

    def test_minutes_above_maximum_rejected(self, client):
        assert client.get("/api/history?minutes=1441").status_code == 422

    def test_max_points_below_minimum_rejected(self, client):
        assert client.get("/api/history?max_points=9").status_code == 422

    def test_max_points_above_maximum_rejected(self, client):
        assert client.get("/api/history?max_points=1001").status_code == 422

    def test_boundary_minutes_accepted(self, client):
        assert client.get("/api/history?minutes=1").status_code == 200
        assert client.get("/api/history?minutes=1440").status_code == 200

    def test_boundary_max_points_accepted(self, client):
        assert client.get("/api/history?max_points=10").status_code == 200
        assert client.get("/api/history?max_points=1000").status_code == 200

    # ── data content ────────────────────────────────────────────────────────

    def test_recent_reading_included(self, client):
        insert_reading(make_reading(), source="test")
        rows = client.get("/api/history?minutes=60").json()
        assert len(rows) >= 1

    def test_old_reading_excluded(self, client):
        insert_reading(
            Reading(timestamp=_now() - timedelta(hours=2), channels=[], air_temp_c=5.0),
            source="test",
        )
        rows = client.get("/api/history?minutes=60").json()
        assert rows == []

    def test_bucket_has_required_keys(self, client):
        insert_reading(make_reading(), source="test")
        row = client.get("/api/history?minutes=60").json()[0]
        for key in ("ts", "air_temp_c", "soil_temp_c", "battery_percent", "channels"):
            assert key in row

    def test_channels_in_bucket(self, client):
        insert_reading(make_reading(), source="test")
        row = client.get("/api/history?minutes=60").json()[0]
        assert isinstance(row["channels"], list)
        assert any(c["dev"] == 0 and c["ch"] == 0 for c in row["channels"])

    def test_channel_has_dev_ch_moisture(self, client):
        insert_reading(make_reading(), source="test")
        ch = client.get("/api/history?minutes=60").json()[0]["channels"][0]
        for key in ("dev", "ch", "moisture_pct"):
            assert key in ch

    def test_results_ordered_ascending(self, client):
        now = _now()
        insert_reading(Reading(timestamp=now - timedelta(minutes=20), channels=[], air_temp_c=10.0), source="test")
        insert_reading(Reading(timestamp=now - timedelta(minutes=5),  channels=[], air_temp_c=20.0), source="test")
        rows = client.get("/api/history?minutes=60&max_points=300").json()
        assert len(rows) >= 2
        assert rows[0]["ts"] <= rows[-1]["ts"]

    def test_bucketing_caps_result_count(self, client):
        """120 readings over 60 minutes with max_points=10 → at most 10 buckets."""
        now = _now()
        for i in range(120):
            insert_reading(
                Reading(
                    timestamp=now - timedelta(seconds=i * 30),
                    channels=[],
                    air_temp_c=float(i % 20),
                ),
                source="test",
            )
        rows = client.get("/api/history?minutes=60&max_points=10").json()
        assert len(rows) <= 10

    def test_bucket_averages_temperature(self, frozen_client):
        """Two readings forced into the same bucket → averaged air temperature = 15.0 exactly.

        With _utcnow frozen to _FIXED_NOW:
          minutes=1, max_points=10  →  b = 60//10 + 1 = 7 s
          cutoff_epoch = int((_FIXED_NOW - 60 s).timestamp())
          Reading at _FIXED_NOW - 10 s  →  relative = 50  →  bucket = floor(50/7) = 7
          Reading at _FIXED_NOW -  8 s  →  relative = 52  →  bucket = floor(52/7) = 7
        Both in bucket 7; AVG(10, 20) = 15.0.
        """
        insert_reading(
            Reading(timestamp=_FIXED_NOW - timedelta(seconds=10), channels=[], air_temp_c=10.0),
            source="test",
        )
        insert_reading(
            Reading(timestamp=_FIXED_NOW - timedelta(seconds=8), channels=[], air_temp_c=20.0),
            source="test",
        )
        rows = frozen_client.get("/api/history?minutes=1&max_points=10").json()
        assert len(rows) == 1
        assert rows[0]["air_temp_c"] == pytest.approx(15.0)

    def test_err_channel_excluded_from_bucket(self, client):
        """Channels with status='err' must not appear in bucket moisture data."""
        r = Reading(
            timestamp=_now(),
            channels=[AdcChannel(dev=2, ch=2, raw=0, status="err", moisture_pct=None)],
        )
        insert_reading(r, source="test")
        rows = client.get("/api/history?minutes=60").json()
        all_chs = [c for row in rows for c in row["channels"]]
        assert all_chs == []


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------

class TestApiConfig:
    def test_returns_200(self, client):
        assert client.get("/api/config").status_code == 200

    def test_has_sensors_key(self, client):
        assert "sensors" in client.get("/api/config").json()

    def test_has_thresholds_key(self, client):
        assert "thresholds" in client.get("/api/config").json()

    def test_sensors_have_dev_and_ch(self, client):
        for sensor in client.get("/api/config").json()["sensors"]:
            assert "dev" in sensor
            assert "ch" in sensor

    def test_thresholds_has_moisture_min(self, client):
        thresh = client.get("/api/config").json()["thresholds"]
        assert "soil_moisture_min_percent" in thresh


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

class TestStaticFiles:
    def test_root_serves_index_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_app_js_served(self, client):
        assert client.get("/app.js").status_code == 200

    def test_style_css_served(self, client):
        assert client.get("/style.css").status_code == 200

    def test_api_routes_not_shadowed_by_static(self, client):
        """API routes must take priority over the static file mount."""
        insert_reading(make_reading(), source="test")
        assert client.get("/api/latest").status_code == 200

    def test_static_files_have_no_cache_header(self, client):
        """Static files must carry Cache-Control: no-cache to prevent stale copies."""
        for path in ("/", "/style.css", "/app.js"):
            r = client.get(path)
            cc = r.headers.get("cache-control", "").lower()
            assert "no-cache" in cc, (
                f"Static path '{path}' missing Cache-Control: no-cache (got: '{cc}')"
            )

    def test_index_html_references_all_load(self, client):
        """Every local CSS/JS file referenced in index.html must return 200.

        Catches the bug where index.html used /static/style.css but StaticFiles
        is mounted at '/' (correct path: /style.css).
        """
        html = client.get("/").text
        # Collect all href/src values (covers <link href=...> and <script src=...>)
        refs = re.findall(r'(?:href|src)=["\']([^"\']+)["\']', html)
        # Keep only server-local paths (start with /, exclude protocol-relative //
        # and external URLs like https://cdn.*)
        local_refs = [
            r for r in refs
            if r.startswith("/") and not r.startswith("//") and "://" not in r
        ]
        assert local_refs, "index.html should reference at least one local CSS/JS file"
        for ref in local_refs:
            resp = client.get(ref)
            assert resp.status_code == 200, (
                f"index.html references '{ref}' but it returned HTTP {resp.status_code}"
            )


# ---------------------------------------------------------------------------
# _row_to_reading
# ---------------------------------------------------------------------------

class TestRowToReading:
    def test_valid_row_returns_reading(self):
        row = {
            "ts": "2025-01-01T12:00:00+00:00",
            "channels": [{"dev": 0, "ch": 0, "raw": 15000, "status": "ok", "moisture_pct": 55.0}],
            "air_temp_c": 22.0,
            "soil_temp_c": 18.0,
            "battery_percent": 75.0,
            "battery_voltage": 3.9,
        }
        r = _row_to_reading(row)
        assert r.air_temp_c == pytest.approx(22.0)
        assert len(r.channels) == 1

    def test_missing_dev_channel_skipped(self):
        row = {
            "ts": "2025-01-01T12:00:00+00:00",
            "channels": [
                {"ch": 0, "raw": 15000, "status": "ok", "moisture_pct": 55.0},   # no dev
                {"dev": 0, "ch": 1, "raw": 16000, "status": "ok", "moisture_pct": 40.0},
            ],
        }
        r = _row_to_reading(row)
        assert len(r.channels) == 1
        assert r.channels[0].ch == 1

    def test_missing_ch_channel_skipped(self):
        row = {
            "ts": "2025-01-01T12:00:00+00:00",
            "channels": [
                {"dev": 0, "raw": 15000, "status": "ok", "moisture_pct": 55.0},  # no ch
                {"dev": 0, "ch": 1, "raw": 16000, "status": "ok", "moisture_pct": 40.0},
            ],
        }
        r = _row_to_reading(row)
        assert len(r.channels) == 1

    def test_invalid_channel_skipped(self, caplog):
        import logging
        row = {
            "ts": "2025-01-01T12:00:00+00:00",
            "channels": [
                {"dev": "not_a_number", "ch": 0, "raw": 15000, "status": "ok", "moisture_pct": None},
                {"dev": 0, "ch": 1, "raw": 16000, "status": "ok", "moisture_pct": 40.0},
            ],
        }
        with caplog.at_level(logging.WARNING, logger="app.main"):
            r = _row_to_reading(row)
        assert any(c.ch == 1 for c in r.channels)
        assert "Skipping" in caplog.text

    def test_invalid_timestamp_falls_back_to_now(self):
        row = {"ts": "not-a-date", "channels": []}
        r = _row_to_reading(row)
        diff = abs((datetime.now(tz=timezone.utc) - r.timestamp).total_seconds())
        assert diff < 5

    def test_missing_battery_fields_gives_none(self):
        row = {"ts": "2025-01-01T12:00:00+00:00", "channels": [],
               "battery_percent": None, "battery_voltage": None}
        assert _row_to_reading(row).battery is None

    def test_battery_present(self):
        row = {"ts": "2025-01-01T12:00:00+00:00", "channels": [],
               "battery_percent": 80.0, "battery_voltage": 3.96}
        r = _row_to_reading(row)
        assert r.battery is not None
        assert r.battery.percent == pytest.approx(80.0)

    def test_empty_channels_list(self):
        row = {"ts": "2025-01-01T12:00:00+00:00", "channels": []}
        assert _row_to_reading(row).channels == []
