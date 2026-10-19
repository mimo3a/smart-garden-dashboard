"""Tests for app.parser.parse_line."""

from __future__ import annotations

import json

import pytest

from app.parser import _moisture_pct, parse_line

# Exact example from AGENTS.md
VALID_LINE = json.dumps(
    {
        "adc": [
            {"ch": 0, "raw": 15234, "status": "ok"},
            {"ch": 1, "raw": 14980, "status": "ok"},
            {"ch": 2, "raw": 0, "status": "err"},
            {"ch": 3, "raw": 16012, "status": "ok"},
        ],
        "air_temp_c": 22.4,
        "soil_temp_c": 18.1,
        "battery": {"voltage": 3.91, "percent": 76},
    }
)

# Calibration constants matching config.json
DRY = 26000
WET = 12000


class TestValidLine:
    def test_returns_reading(self):
        assert parse_line(VALID_LINE) is not None

    def test_scalar_fields(self):
        r = parse_line(VALID_LINE)
        assert r.air_temp_c == pytest.approx(22.4)
        assert r.soil_temp_c == pytest.approx(18.1)

    def test_battery(self):
        r = parse_line(VALID_LINE)
        assert r.battery is not None
        assert r.battery.voltage == pytest.approx(3.91)
        assert r.battery.percent == pytest.approx(76)

    def test_adc_channel_count(self):
        r = parse_line(VALID_LINE)
        assert len(r.adc) == 4

    def test_moisture_ch0(self):
        # (26000 - 15234) / (26000 - 12000) * 100
        expected = (DRY - 15234) / (DRY - WET) * 100
        r = parse_line(VALID_LINE)
        assert r.adc[0].moisture_pct == pytest.approx(expected)

    def test_moisture_ch1(self):
        expected = (DRY - 14980) / (DRY - WET) * 100
        r = parse_line(VALID_LINE)
        assert r.adc[1].moisture_pct == pytest.approx(expected)

    def test_timestamp_present(self):
        r = parse_line(VALID_LINE)
        assert r.timestamp is not None


class TestBrokenJson:
    def test_garbage_input(self):
        assert parse_line("not valid json {{{") is None

    def test_empty_string(self):
        assert parse_line("") is None

    def test_truncated_json(self):
        assert parse_line('{"adc":') is None


class TestMissingBattery:
    def test_battery_is_none(self):
        line = json.dumps({"adc": [], "air_temp_c": 20.0, "soil_temp_c": 15.0})
        r = parse_line(line)
        assert r is not None
        assert r.battery is None

    def test_other_fields_intact(self):
        line = json.dumps({"adc": [], "air_temp_c": 20.0, "soil_temp_c": 15.0})
        r = parse_line(line)
        assert r.air_temp_c == pytest.approx(20.0)


class TestChannelWithErr:
    def test_moisture_is_none_for_err(self):
        line = json.dumps({"adc": [{"ch": 0, "raw": 15000, "status": "err"}]})
        r = parse_line(line)
        assert r is not None
        assert r.adc[0].moisture_pct is None

    def test_ok_channels_still_computed(self):
        line = json.dumps(
            {
                "adc": [
                    {"ch": 0, "raw": 0, "status": "err"},
                    {"ch": 1, "raw": 15000, "status": "ok"},
                ]
            }
        )
        r = parse_line(line)
        assert r.adc[0].moisture_pct is None
        assert r.adc[1].moisture_pct is not None


class TestRawOutsideCalibration:
    def test_raw_above_dry_clamps_to_zero(self):
        # raw > dry_raw → negative pct → clamp to 0.0
        line = json.dumps({"adc": [{"ch": 0, "raw": 30000, "status": "ok"}]})
        r = parse_line(line)
        assert r.adc[0].moisture_pct == pytest.approx(0.0)

    def test_raw_below_wet_clamps_to_hundred(self):
        # raw < wet_raw → pct > 100 → clamp to 100.0
        line = json.dumps({"adc": [{"ch": 0, "raw": 5000, "status": "ok"}]})
        r = parse_line(line)
        assert r.adc[0].moisture_pct == pytest.approx(100.0)

    def test_moisture_pct_helper_clamps(self):
        assert _moisture_pct(30000, DRY, WET) == pytest.approx(0.0)
        assert _moisture_pct(5000, DRY, WET) == pytest.approx(100.0)
        assert 0.0 <= _moisture_pct(19000, DRY, WET) <= 100.0


class TestNonObjectJson:
    """Fix 1: valid JSON that is not an object must return None, not AttributeError."""

    def test_json_array(self):
        assert parse_line("[1, 2, 3]") is None

    def test_json_integer(self):
        assert parse_line("123") is None

    def test_json_null(self):
        assert parse_line("null") is None

    def test_json_string(self):
        assert parse_line('"hello"') is None


class TestAdcNullOrNonDict:
    """Fix 2: 'adc': null or non-dict channel entries must not crash."""

    def test_adc_null_returns_reading_with_empty_adc(self):
        line = json.dumps({"adc": None, "air_temp_c": 20.0})
        r = parse_line(line)
        assert r is not None
        assert r.adc == []

    def test_adc_not_a_list(self):
        line = json.dumps({"adc": "bad"})
        r = parse_line(line)
        assert r is not None
        assert r.adc == []

    def test_adc_channel_is_integer(self):
        line = json.dumps({"adc": [42, {"ch": 1, "raw": 15000, "status": "ok"}]})
        r = parse_line(line)
        assert r is not None
        # integer entry discarded; valid entry kept
        assert len(r.adc) == 1
        assert r.adc[0].ch == 1

    def test_adc_channel_is_string(self):
        line = json.dumps({"adc": ["bad", {"ch": 0, "raw": 15000, "status": "ok"}]})
        r = parse_line(line)
        assert r is not None
        assert len(r.adc) == 1


class TestWrongFieldTypes:
    """Fix 3: non-numeric scalar fields must not raise ValidationError."""

    def test_air_temp_string_becomes_none(self):
        line = json.dumps({"adc": [], "air_temp_c": "abc", "soil_temp_c": 15.0})
        r = parse_line(line)
        assert r is not None
        assert r.air_temp_c is None
        assert r.soil_temp_c == pytest.approx(15.0)

    def test_soil_temp_string_becomes_none(self):
        line = json.dumps({"adc": [], "air_temp_c": 20.0, "soil_temp_c": "hot"})
        r = parse_line(line)
        assert r is not None
        assert r.soil_temp_c is None

    def test_raw_string_gives_no_moisture(self):
        # Channel stays in the list but raw=None → moisture_pct=None
        line = json.dumps({"adc": [{"ch": 0, "raw": "x", "status": "ok"}]})
        r = parse_line(line)
        assert r is not None
        assert len(r.adc) == 1
        assert r.adc[0].moisture_pct is None


class TestMissingChKey:
    """Fix 4: channel entries without 'ch' must be discarded, not mapped to ch=0."""

    def test_channel_without_ch_is_discarded(self):
        line = json.dumps({"adc": [{"raw": 15000, "status": "ok"}]})
        r = parse_line(line)
        assert r is not None
        assert r.adc == []

    def test_valid_channel_kept_alongside_discarded(self):
        line = json.dumps(
            {
                "adc": [
                    {"raw": 15000, "status": "ok"},       # no "ch" → discard
                    {"ch": 2, "raw": 15000, "status": "ok"},  # valid → keep
                ]
            }
        )
        r = parse_line(line)
        assert r is not None
        assert len(r.adc) == 1
        assert r.adc[0].ch == 2
