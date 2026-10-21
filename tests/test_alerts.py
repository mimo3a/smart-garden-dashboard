"""Tests for app.alerts.check_alerts()."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

import pytest

from app.alerts import ALL_ALERT_TYPES, check_alerts
from app.models import AdcChannel, BatteryReading, Reading
from app.simulator import _DEMO_SCENARIOS, _DEMO_STEPS_PER_SCENARIO, simulate_demo

_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

_CONFIG = {
    "sensors": [
        {"dev": 0, "ch": 0, "name": "Beet 1",  "dry_raw": 26000, "wet_raw": 12000},
        {"dev": 0, "ch": 1, "name": "Beet 2",  "dry_raw": 26000, "wet_raw": 12000},
    ],
    "thresholds": {
        "soil_moisture_min_percent": 30,
        "air_temp_min_c": 5,
        "air_temp_max_c": 35,
        "soil_temp_min_c": 5,
        "soil_temp_max_c": 30,
        "battery_min_percent": 20,
    },
}


def make_reading(
    *,
    channels=None,
    air_temp_c=None,
    soil_temp_c=None,
    battery=None,
) -> Reading:
    return Reading(
        timestamp=_NOW,
        channels=channels or [],
        air_temp_c=air_temp_c,
        soil_temp_c=soil_temp_c,
        battery=battery,
    )


def _types(alerts: list[dict]) -> list[str]:
    return [a["type"] for a in alerts]


# ---------------------------------------------------------------------------
# Soil moisture
# ---------------------------------------------------------------------------

class TestSoilMoistureAlerts:
    def test_below_threshold_triggers_alert(self):
        ch = AdcChannel(dev=0, ch=0, raw=25000, status="ok", moisture_pct=10.0)
        assert "soil_moisture_low" in _types(check_alerts(make_reading(channels=[ch]), _CONFIG))

    def test_exactly_at_threshold_no_alert(self):
        ch = AdcChannel(dev=0, ch=0, raw=19000, status="ok", moisture_pct=30.0)
        assert "soil_moisture_low" not in _types(check_alerts(make_reading(channels=[ch]), _CONFIG))

    def test_above_threshold_no_alert(self):
        ch = AdcChannel(dev=0, ch=0, raw=15000, status="ok", moisture_pct=50.0)
        assert "soil_moisture_low" not in _types(check_alerts(make_reading(channels=[ch]), _CONFIG))

    def test_none_moisture_pct_no_alert(self):
        ch = AdcChannel(dev=0, ch=0, raw=None, status="ok", moisture_pct=None)
        assert "soil_moisture_low" not in _types(check_alerts(make_reading(channels=[ch]), _CONFIG))

    def test_err_status_no_moisture_alert(self):
        ch = AdcChannel(dev=0, ch=0, raw=0, status="err", moisture_pct=None)
        assert "soil_moisture_low" not in _types(check_alerts(make_reading(channels=[ch]), _CONFIG))

    def test_alert_has_correct_dev_ch(self):
        ch = AdcChannel(dev=0, ch=1, raw=25000, status="ok", moisture_pct=5.0)
        alerts = [a for a in check_alerts(make_reading(channels=[ch]), _CONFIG)
                  if a["type"] == "soil_moisture_low"]
        assert len(alerts) == 1
        assert alerts[0]["dev"] == 0
        assert alerts[0]["ch"] == 1

    def test_sensor_name_in_message(self):
        ch = AdcChannel(dev=0, ch=0, raw=25000, status="ok", moisture_pct=10.0)
        a = next(x for x in check_alerts(make_reading(channels=[ch]), _CONFIG)
                 if x["type"] == "soil_moisture_low")
        assert "Beet 1" in a["message"]

    def test_severity_is_warning(self):
        ch = AdcChannel(dev=0, ch=0, raw=25000, status="ok", moisture_pct=10.0)
        a = next(x for x in check_alerts(make_reading(channels=[ch]), _CONFIG)
                 if x["type"] == "soil_moisture_low")
        assert a["severity"] == "warning"

    def test_just_below_threshold_triggers(self):
        ch = AdcChannel(dev=0, ch=0, raw=None, status="ok", moisture_pct=29.9)
        assert "soil_moisture_low" in _types(check_alerts(make_reading(channels=[ch]), _CONFIG))


# ---------------------------------------------------------------------------
# Sensor error
# ---------------------------------------------------------------------------

class TestSensorErrorAlerts:
    def test_err_channel_triggers_alert(self):
        ch = AdcChannel(dev=0, ch=0, raw=0, status="err", moisture_pct=None)
        assert "sensor_error" in _types(check_alerts(make_reading(channels=[ch]), _CONFIG))

    def test_ok_channel_no_sensor_error_alert(self):
        ch = AdcChannel(dev=0, ch=0, raw=15000, status="ok", moisture_pct=50.0)
        assert "sensor_error" not in _types(check_alerts(make_reading(channels=[ch]), _CONFIG))

    def test_sensor_error_has_correct_dev_ch(self):
        ch = AdcChannel(dev=1, ch=2, raw=0, status="err", moisture_pct=None)
        alerts = [a for a in check_alerts(make_reading(channels=[ch]), _CONFIG)
                  if a["type"] == "sensor_error"]
        assert len(alerts) == 1
        assert alerts[0]["dev"] == 1
        assert alerts[0]["ch"] == 2

    def test_sensor_error_severity_is_error(self):
        ch = AdcChannel(dev=0, ch=0, raw=0, status="err", moisture_pct=None)
        a = next(x for x in check_alerts(make_reading(channels=[ch]), _CONFIG)
                 if x["type"] == "sensor_error")
        assert a["severity"] == "error"

    def test_sensor_name_in_error_message(self):
        ch = AdcChannel(dev=0, ch=0, raw=0, status="err", moisture_pct=None)
        a = next(x for x in check_alerts(make_reading(channels=[ch]), _CONFIG)
                 if x["type"] == "sensor_error")
        assert "Beet 1" in a["message"]

    def test_unknown_sensor_has_fallback_name(self):
        ch = AdcChannel(dev=3, ch=3, raw=0, status="err", moisture_pct=None)
        a = next(x for x in check_alerts(make_reading(channels=[ch]), _CONFIG)
                 if x["type"] == "sensor_error")
        assert "3:3" in a["message"] or "Sensor" in a["message"]


# ---------------------------------------------------------------------------
# Air temperature
# ---------------------------------------------------------------------------

class TestAirTempAlerts:
    def test_below_min_triggers_low_alert(self):
        assert "air_temp_low" in _types(check_alerts(make_reading(air_temp_c=2.0), _CONFIG))

    def test_exactly_at_min_no_alert(self):
        assert "air_temp_low" not in _types(check_alerts(make_reading(air_temp_c=5.0), _CONFIG))

    def test_just_below_min_triggers(self):
        assert "air_temp_low" in _types(check_alerts(make_reading(air_temp_c=4.9), _CONFIG))

    def test_above_max_triggers_high_alert(self):
        assert "air_temp_high" in _types(check_alerts(make_reading(air_temp_c=38.0), _CONFIG))

    def test_exactly_at_max_no_alert(self):
        assert "air_temp_high" not in _types(check_alerts(make_reading(air_temp_c=35.0), _CONFIG))

    def test_just_above_max_triggers(self):
        assert "air_temp_high" in _types(check_alerts(make_reading(air_temp_c=35.1), _CONFIG))

    def test_in_range_no_alert(self):
        alerts = check_alerts(make_reading(air_temp_c=22.0), _CONFIG)
        assert not any(a["type"].startswith("air_temp") for a in alerts)

    def test_none_air_temp_no_alert(self):
        alerts = check_alerts(make_reading(air_temp_c=None), _CONFIG)
        assert not any(a["type"].startswith("air_temp") for a in alerts)

    def test_low_alert_dev_ch_none(self):
        a = next(x for x in check_alerts(make_reading(air_temp_c=2.0), _CONFIG)
                 if x["type"] == "air_temp_low")
        assert a["dev"] is None
        assert a["ch"] is None

    def test_high_alert_dev_ch_none(self):
        a = next(x for x in check_alerts(make_reading(air_temp_c=38.0), _CONFIG)
                 if x["type"] == "air_temp_high")
        assert a["dev"] is None
        assert a["ch"] is None


# ---------------------------------------------------------------------------
# Soil temperature
# ---------------------------------------------------------------------------

class TestSoilTempAlerts:
    def test_below_min_triggers_low_alert(self):
        assert "soil_temp_low" in _types(check_alerts(make_reading(soil_temp_c=2.0), _CONFIG))

    def test_exactly_at_min_no_alert(self):
        assert "soil_temp_low" not in _types(check_alerts(make_reading(soil_temp_c=5.0), _CONFIG))

    def test_just_below_min_triggers(self):
        assert "soil_temp_low" in _types(check_alerts(make_reading(soil_temp_c=4.9), _CONFIG))

    def test_above_max_triggers_high_alert(self):
        assert "soil_temp_high" in _types(check_alerts(make_reading(soil_temp_c=32.0), _CONFIG))

    def test_exactly_at_max_no_alert(self):
        assert "soil_temp_high" not in _types(check_alerts(make_reading(soil_temp_c=30.0), _CONFIG))

    def test_just_above_max_triggers(self):
        assert "soil_temp_high" in _types(check_alerts(make_reading(soil_temp_c=30.1), _CONFIG))

    def test_none_soil_temp_no_alert(self):
        alerts = check_alerts(make_reading(soil_temp_c=None), _CONFIG)
        assert not any(a["type"].startswith("soil_temp") for a in alerts)

    def test_dev_ch_none(self):
        a = next(x for x in check_alerts(make_reading(soil_temp_c=2.0), _CONFIG)
                 if x["type"] == "soil_temp_low")
        assert a["dev"] is None
        assert a["ch"] is None


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

class TestBatteryAlerts:
    def test_below_min_triggers_alert(self):
        r = make_reading(battery=BatteryReading(voltage=3.1, percent=5.0))
        assert "battery_low" in _types(check_alerts(r, _CONFIG))

    def test_exactly_at_min_no_alert(self):
        r = make_reading(battery=BatteryReading(voltage=3.24, percent=20.0))
        assert "battery_low" not in _types(check_alerts(r, _CONFIG))

    def test_just_below_min_triggers(self):
        r = make_reading(battery=BatteryReading(voltage=3.23, percent=19.9))
        assert "battery_low" in _types(check_alerts(r, _CONFIG))

    def test_above_min_no_alert(self):
        r = make_reading(battery=BatteryReading(voltage=3.9, percent=75.0))
        assert "battery_low" not in _types(check_alerts(r, _CONFIG))

    def test_none_battery_no_alert(self):
        assert "battery_low" not in _types(check_alerts(make_reading(battery=None), _CONFIG))

    def test_battery_alert_dev_ch_none(self):
        r = make_reading(battery=BatteryReading(voltage=3.1, percent=5.0))
        a = next(x for x in check_alerts(r, _CONFIG) if x["type"] == "battery_low")
        assert a["dev"] is None
        assert a["ch"] is None

    def test_severity_is_warning(self):
        r = make_reading(battery=BatteryReading(voltage=3.1, percent=5.0))
        a = next(x for x in check_alerts(r, _CONFIG) if x["type"] == "battery_low")
        assert a["severity"] == "warning"


# ---------------------------------------------------------------------------
# Missing / empty config
# ---------------------------------------------------------------------------

class TestMissingConfig:
    def test_empty_config_no_threshold_alerts(self):
        ch = AdcChannel(dev=0, ch=0, raw=25000, status="ok", moisture_pct=5.0)
        r = make_reading(
            channels=[ch], air_temp_c=40.0, soil_temp_c=40.0,
            battery=BatteryReading(voltage=3.0, percent=1.0),
        )
        # No thresholds → no moisture/temp/battery alerts (sensor_error not triggered: status ok)
        alerts = check_alerts(r, {})
        assert alerts == []

    def test_empty_thresholds_dict_no_alerts(self):
        ch = AdcChannel(dev=0, ch=0, raw=25000, status="ok", moisture_pct=5.0)
        r = make_reading(channels=[ch], air_temp_c=40.0, soil_temp_c=40.0,
                         battery=BatteryReading(voltage=3.0, percent=1.0))
        alerts = check_alerts(r, {"thresholds": {}})
        assert alerts == []

    def test_no_channels_no_channel_alerts(self):
        alerts = check_alerts(make_reading(), _CONFIG)
        assert not any(a["type"] in ("sensor_error", "soil_moisture_low") for a in alerts)

    def test_all_none_values_no_alerts(self):
        alerts = check_alerts(make_reading(), _CONFIG)
        assert alerts == []


# ---------------------------------------------------------------------------
# Alert structure
# ---------------------------------------------------------------------------

class TestAlertStructure:
    def test_every_alert_has_required_keys(self):
        ch = AdcChannel(dev=0, ch=0, raw=0, status="err", moisture_pct=None)
        r = make_reading(
            channels=[ch], air_temp_c=38.0, soil_temp_c=32.0,
            battery=BatteryReading(voltage=3.1, percent=5.0),
        )
        for alert in check_alerts(r, _CONFIG):
            for key in ("type", "severity", "message", "dev", "ch"):
                assert key in alert, f"Alert missing key {key!r}: {alert}"

    def test_multiple_sensors_multiple_alerts(self):
        channels = [
            AdcChannel(dev=0, ch=0, raw=25000, status="ok", moisture_pct=5.0),
            AdcChannel(dev=0, ch=1, raw=25000, status="ok", moisture_pct=5.0),
        ]
        r = make_reading(channels=channels)
        moisture_alerts = [a for a in check_alerts(r, _CONFIG)
                           if a["type"] == "soil_moisture_low"]
        assert len(moisture_alerts) == 2


# ---------------------------------------------------------------------------
# Demo mode: every alert type within one full cycle
# ---------------------------------------------------------------------------

class TestDemoMode:
    def test_all_alert_types_generated(self):
        """simulate_demo must produce every type in ALL_ALERT_TYPES within one full cycle."""
        from app.parser import parse_line

        config_path = Path(__file__).parent.parent / "config.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))

        # One complete cycle covers all len(_DEMO_SCENARIOS) scenarios.
        lines = list(islice(simulate_demo(interval=0, seed=42),
                            len(_DEMO_SCENARIOS) * _DEMO_STEPS_PER_SCENARIO))

        all_types: set[str] = set()
        for line in lines:
            reading = parse_line(line)
            if reading is not None:
                for alert in check_alerts(reading, cfg):
                    all_types.add(alert["type"])

        missing = ALL_ALERT_TYPES - all_types
        assert not missing, f"Demo-Modus erzeugt folgende Alarmtypen nicht: {missing}"

    def test_normal_scenario_produces_no_alerts(self):
        """The first scenario (normal) must not produce any alerts."""
        from app.parser import parse_line

        config_path = Path(__file__).parent.parent / "config.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))

        lines = list(islice(simulate_demo(interval=0, seed=42),
                            _DEMO_STEPS_PER_SCENARIO))
        all_alerts = []
        for line in lines:
            reading = parse_line(line)
            if reading is not None:
                all_alerts.extend(check_alerts(reading, cfg))
        assert all_alerts == [], f"Normal-Szenario erzeugt Alarme: {all_alerts}"
