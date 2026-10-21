"""Tests for app.parser.parse_line."""

from __future__ import annotations

import json

import pytest

from app.parser import _moisture_pct, parse_line

# Calibration constants matching config.json (all 16 sensors use these values)
DRY = 26000
WET = 12000

# ---------------------------------------------------------------------------
# Test lines
# ---------------------------------------------------------------------------

# Exact line captured from the real development board (8 channels, dev 0+1,
# no temperatures or battery because the firmware is still incomplete).
ACTUAL_LINE = (
    '{"channels":['
    '{"dev":0,"ch":0,"status":0,"raw":4781},'
    '{"dev":0,"ch":1,"status":0,"raw":4755},'
    '{"dev":0,"ch":2,"status":0,"raw":4728},'
    '{"dev":0,"ch":3,"status":0,"raw":4772},'
    '{"dev":1,"ch":0,"status":0,"raw":25351},'
    '{"dev":1,"ch":1,"status":0,"raw":24649},'
    '{"dev":1,"ch":2,"status":0,"raw":23800},'
    '{"dev":1,"ch":3,"status":0,"raw":23156}'
    ']}'
)

# Synthetic full line: all 16 channels, temperatures, battery, one err channel.
FULL_LINE = json.dumps(
    {
        "channels": (
            # 15 ok channels with raw=15000
            [{"dev": d, "ch": c, "status": 0, "raw": 15000}
             for d in range(4) for c in range(4)
             if not (d == 3 and c == 3)]
            # one err channel (dev=3, ch=3)
            + [{"dev": 3, "ch": 3, "status": 1, "raw": 0}]
        ),
        "air_temp_c": 22.4,
        "soil_temp_c": 18.1,
        "battery": {"voltage": 3.91, "percent": 76},
    }
)


# ---------------------------------------------------------------------------
# Actual hardware line (8 channels, no temps/battery)
# ---------------------------------------------------------------------------

class TestActualHardwareLine:
    """Parse the exact line emitted by the current development board."""

    def test_returns_reading(self):
        assert parse_line(ACTUAL_LINE) is not None

    def test_eight_channels(self):
        r = parse_line(ACTUAL_LINE)
        assert len(r.channels) == 8

    def test_no_temps_or_battery(self):
        r = parse_line(ACTUAL_LINE)
        assert r.air_temp_c is None
        assert r.soil_temp_c is None
        assert r.battery is None

    def test_all_channels_ok(self):
        r = parse_line(ACTUAL_LINE)
        assert all(ch.status == "ok" for ch in r.channels)

    def test_dev0_raw_below_wet_raw_clamped_to_100(self):
        # dev=0 raw values (~4700) are far below wet_raw=12000 → 100 %
        r = parse_line(ACTUAL_LINE)
        dev0 = [ch for ch in r.channels if ch.dev == 0]
        for ch in dev0:
            assert ch.moisture_pct == pytest.approx(100.0)

    def test_dev1_moisture_computed(self):
        # dev=1, ch=0, raw=25351 → (26000-25351)/(26000-12000)*100 ≈ 4.6 %
        r = parse_line(ACTUAL_LINE)
        ch = next(c for c in r.channels if c.dev == 1 and c.ch == 0)
        expected = (DRY - 25351) / (DRY - WET) * 100
        assert ch.moisture_pct == pytest.approx(expected)

    def test_channel_ids_correct(self):
        r = parse_line(ACTUAL_LINE)
        ids = {(ch.dev, ch.ch) for ch in r.channels}
        assert ids == {(0, 0), (0, 1), (0, 2), (0, 3),
                       (1, 0), (1, 1), (1, 2), (1, 3)}

    def test_timestamp_present(self):
        assert parse_line(ACTUAL_LINE).timestamp is not None


# ---------------------------------------------------------------------------
# Full 16-channel line with temperatures and battery
# ---------------------------------------------------------------------------

class TestFullLine:
    def test_returns_reading(self):
        assert parse_line(FULL_LINE) is not None

    def test_sixteen_channels(self):
        assert len(parse_line(FULL_LINE).channels) == 16

    def test_scalar_fields(self):
        r = parse_line(FULL_LINE)
        assert r.air_temp_c == pytest.approx(22.4)
        assert r.soil_temp_c == pytest.approx(18.1)

    def test_battery(self):
        r = parse_line(FULL_LINE)
        assert r.battery is not None
        assert r.battery.voltage == pytest.approx(3.91)
        assert r.battery.percent == pytest.approx(76)

    def test_ok_channel_moisture(self):
        # raw=15000 → (26000-15000)/(26000-12000)*100 ≈ 78.57 %
        expected = (DRY - 15000) / (DRY - WET) * 100
        r = parse_line(FULL_LINE)
        ok_channels = [ch for ch in r.channels if ch.status == "ok"]
        for ch in ok_channels:
            assert ch.moisture_pct == pytest.approx(expected)

    def test_err_channel_no_moisture(self):
        r = parse_line(FULL_LINE)
        err_ch = next(c for c in r.channels if c.status == "err")
        assert err_ch.dev == 3 and err_ch.ch == 3
        assert err_ch.moisture_pct is None


# ---------------------------------------------------------------------------
# Broken / non-JSON input
# ---------------------------------------------------------------------------

class TestBrokenJson:
    def test_garbage_returns_none(self):
        assert parse_line("not valid json {{{") is None

    def test_empty_string_returns_none(self):
        assert parse_line("") is None

    def test_truncated_json_returns_none(self):
        assert parse_line('{"channels":') is None

    def test_boot_message_returns_none(self):
        assert parse_line("USART1 PA9 OK") is None

    def test_other_boot_message_returns_none(self):
        assert parse_line("System clock configured") is None


# ---------------------------------------------------------------------------
# Non-object JSON values
# ---------------------------------------------------------------------------

class TestNonObjectJson:
    def test_json_array_returns_none(self):
        assert parse_line("[1, 2, 3]") is None

    def test_json_integer_returns_none(self):
        assert parse_line("123") is None

    def test_json_null_returns_none(self):
        assert parse_line("null") is None

    def test_json_string_returns_none(self):
        assert parse_line('"hello"') is None


# ---------------------------------------------------------------------------
# Missing optional fields
# ---------------------------------------------------------------------------

class TestMissingOptionalFields:
    def test_missing_battery_is_none(self):
        line = json.dumps({
            "channels": [{"dev": 0, "ch": 0, "status": 0, "raw": 15000}],
            "air_temp_c": 20.0,
        })
        r = parse_line(line)
        assert r is not None
        assert r.battery is None
        assert r.air_temp_c == pytest.approx(20.0)

    def test_missing_temps_are_none(self):
        line = json.dumps({
            "channels": [{"dev": 0, "ch": 0, "status": 0, "raw": 15000}],
            "battery": {"voltage": 3.8, "percent": 65},
        })
        r = parse_line(line)
        assert r.air_temp_c is None
        assert r.soil_temp_c is None
        assert r.battery is not None


# ---------------------------------------------------------------------------
# Channel status handling (integer on wire)
# ---------------------------------------------------------------------------

class TestChannelStatus:
    def test_status_0_is_ok(self):
        line = json.dumps({"channels": [{"dev": 0, "ch": 0, "status": 0, "raw": 15000}]})
        r = parse_line(line)
        assert r.channels[0].status == "ok"
        assert r.channels[0].moisture_pct is not None

    def test_status_1_is_err(self):
        line = json.dumps({"channels": [{"dev": 0, "ch": 0, "status": 1, "raw": 0}]})
        r = parse_line(line)
        assert r.channels[0].status == "err"
        assert r.channels[0].moisture_pct is None

    def test_status_nonzero_int_is_err(self):
        line = json.dumps({"channels": [{"dev": 0, "ch": 0, "status": 255, "raw": 0}]})
        r = parse_line(line)
        assert r.channels[0].status == "err"

    def test_missing_status_treated_as_err(self):
        # _safe_int(None) → None, None ≠ 0 → "err"
        line = json.dumps({"channels": [{"dev": 0, "ch": 0, "raw": 15000}]})
        r = parse_line(line)
        assert r.channels[0].status == "err"


# ---------------------------------------------------------------------------
# Channel entry validation
# ---------------------------------------------------------------------------

class TestChannelValidation:
    def test_missing_dev_discards_channel(self):
        line = json.dumps({"channels": [
            {"ch": 0, "status": 0, "raw": 15000},               # no dev → discard
            {"dev": 1, "ch": 0, "status": 0, "raw": 15000},     # valid → keep
        ]})
        r = parse_line(line)
        assert len(r.channels) == 1
        assert r.channels[0].dev == 1

    def test_missing_ch_discards_channel(self):
        line = json.dumps({"channels": [
            {"dev": 0, "status": 0, "raw": 15000},              # no ch → discard
            {"dev": 0, "ch": 1, "status": 0, "raw": 15000},    # valid → keep
        ]})
        r = parse_line(line)
        assert len(r.channels) == 1
        assert r.channels[0].ch == 1

    def test_non_dict_channel_entry_discarded(self):
        line = json.dumps({"channels": [
            42,
            {"dev": 0, "ch": 0, "status": 0, "raw": 15000},
        ]})
        r = parse_line(line)
        assert len(r.channels) == 1

    def test_channels_null_yields_empty_list(self):
        # No channels but has battery → not discarded as empty
        line = json.dumps({"channels": None, "battery": {"voltage": 3.8, "percent": 65}})
        r = parse_line(line)
        assert r is not None
        assert r.channels == []


# ---------------------------------------------------------------------------
# Wrong scalar types
# ---------------------------------------------------------------------------

class TestWrongFieldTypes:
    def test_air_temp_string_becomes_none(self):
        line = json.dumps({"channels": [{"dev": 0, "ch": 0, "status": 0, "raw": 15000}],
                           "air_temp_c": "hot"})
        r = parse_line(line)
        assert r.air_temp_c is None

    def test_raw_string_gives_no_moisture(self):
        line = json.dumps({"channels": [{"dev": 0, "ch": 0, "status": 0, "raw": "x"}]})
        r = parse_line(line)
        assert len(r.channels) == 1
        assert r.channels[0].moisture_pct is None

    def test_unknown_sensor_gives_no_moisture(self):
        # dev=9 is not in config.json → no calibration entry → moisture_pct None
        line = json.dumps({"channels": [{"dev": 9, "ch": 0, "status": 0, "raw": 15000}]})
        r = parse_line(line)
        assert r.channels[0].moisture_pct is None


# ---------------------------------------------------------------------------
# Raw value clamping
# ---------------------------------------------------------------------------

class TestRawOutsideCalibration:
    def test_above_dry_raw_clamps_to_zero(self):
        line = json.dumps({"channels": [{"dev": 0, "ch": 0, "status": 0, "raw": 30000}]})
        assert parse_line(line).channels[0].moisture_pct == pytest.approx(0.0)

    def test_below_wet_raw_clamps_to_hundred(self):
        line = json.dumps({"channels": [{"dev": 0, "ch": 0, "status": 0, "raw": 5000}]})
        assert parse_line(line).channels[0].moisture_pct == pytest.approx(100.0)

    def test_moisture_pct_helper_clamps(self):
        assert _moisture_pct(30000, DRY, WET) == pytest.approx(0.0)
        assert _moisture_pct(5000, DRY, WET) == pytest.approx(100.0)
        assert 0.0 <= _moisture_pct(19000, DRY, WET) <= 100.0


# ---------------------------------------------------------------------------
# Empty-reading guard
# ---------------------------------------------------------------------------

class TestEmptyReading:
    def test_empty_object_returns_none(self):
        assert parse_line("{}") is None

    def test_channels_null_no_other_data_returns_none(self):
        assert parse_line(json.dumps({"channels": None})) is None

    def test_empty_channels_no_other_data_returns_none(self):
        assert parse_line(json.dumps({"channels": []})) is None

    def test_all_channels_discarded_no_other_data_returns_none(self):
        # Channel missing dev → discarded; nothing left
        assert parse_line(json.dumps({"channels": [{"ch": 0, "status": 0, "raw": 1}]})) is None

    def test_battery_only_is_kept(self):
        r = parse_line(json.dumps({"battery": {"voltage": 3.8, "percent": 65}}))
        assert r is not None
        assert r.battery is not None

    def test_air_temp_only_is_kept(self):
        r = parse_line(json.dumps({"air_temp_c": 22.0}))
        assert r is not None
        assert r.air_temp_c == pytest.approx(22.0)


# ---------------------------------------------------------------------------
# Duplicate (dev, ch) entries
# ---------------------------------------------------------------------------

class TestDuplicateChannels:
    def test_duplicate_dev_ch_keeps_last(self):
        line = json.dumps({"channels": [
            {"dev": 0, "ch": 0, "status": 0, "raw": 15000},  # first
            {"dev": 0, "ch": 0, "status": 0, "raw": 20000},  # second – wins
        ]})
        r = parse_line(line)
        assert len(r.channels) == 1
        assert r.channels[0].raw == 20000

    def test_duplicate_logs_warning(self, caplog):
        import logging
        line = json.dumps({"channels": [
            {"dev": 0, "ch": 0, "status": 0, "raw": 15000},
            {"dev": 0, "ch": 0, "status": 0, "raw": 20000},
        ]})
        with caplog.at_level(logging.WARNING, logger="app.parser"):
            parse_line(line)
        assert "Duplicate" in caplog.text

    def test_three_duplicates_keeps_last(self):
        line = json.dumps({"channels": [
            {"dev": 1, "ch": 2, "status": 0, "raw": 10000},
            {"dev": 1, "ch": 2, "status": 0, "raw": 15000},
            {"dev": 1, "ch": 2, "status": 0, "raw": 20000},  # wins
        ]})
        r = parse_line(line)
        assert len(r.channels) == 1
        assert r.channels[0].raw == 20000

    def test_non_duplicate_channels_unaffected(self):
        line = json.dumps({"channels": [
            {"dev": 0, "ch": 0, "status": 0, "raw": 15000},
            {"dev": 0, "ch": 1, "status": 0, "raw": 16000},
            {"dev": 1, "ch": 0, "status": 0, "raw": 17000},
        ]})
        r = parse_line(line)
        assert len(r.channels) == 3
