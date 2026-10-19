"""Tests for app.simulator."""

from __future__ import annotations

from itertools import islice

import pytest

from app.parser import _moisture_pct, parse_line
from app.simulator import _moisture_to_raw, simulate

# Use interval=0 everywhere so tests don't actually sleep.
# Fixed seed=0 makes every run deterministic.
SEED = 0


def _take(gen, n: int) -> list:
    return list(islice(gen, n))


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

class TestOutputShape:
    def test_yields_strings(self):
        lines = _take(simulate(interval=0, seed=SEED), 5)
        assert all(isinstance(line, str) for line in lines)

    def test_valid_lines_have_four_adc_channels(self):
        for line in _take(simulate(interval=0, seed=SEED), 30):
            r = parse_line(line)
            if r is not None:
                assert len(r.adc) == 4

    def test_valid_lines_have_battery(self):
        for line in _take(simulate(interval=0, seed=SEED), 30):
            r = parse_line(line)
            if r is not None:
                assert r.battery is not None

    def test_most_lines_parse_successfully(self):
        lines = _take(simulate(interval=0, seed=SEED), 200)
        valid = sum(1 for line in lines if parse_line(line) is not None)
        # With ~1 % broken-line rate, expect ≥ 185/200 valid
        assert valid >= 185


# ---------------------------------------------------------------------------
# Value ranges
# ---------------------------------------------------------------------------

class TestValueRanges:
    def setup_method(self):
        self.readings = [
            parse_line(line)
            for line in _take(simulate(interval=0, seed=SEED), 100)
        ]
        self.valid = [r for r in self.readings if r is not None]

    def test_air_temp_in_range(self):
        for r in self.valid:
            assert -10.0 <= r.air_temp_c <= 50.0

    def test_soil_temp_in_range(self):
        for r in self.valid:
            assert -10.0 <= r.soil_temp_c <= 45.0

    def test_battery_percent_in_range(self):
        for r in self.valid:
            assert 0.0 <= r.battery.percent <= 100.0

    def test_battery_voltage_in_range(self):
        for r in self.valid:
            # 3.0 V at 0 %, 4.2 V at 100 %
            assert 3.0 <= r.battery.voltage <= 4.2

    def test_ok_channels_moisture_in_range(self):
        for r in self.valid:
            for ch in r.adc:
                if ch.status == "ok":
                    assert 0.0 <= ch.moisture_pct <= 100.0

    def test_soil_temp_close_to_air_temp(self):
        # Soil temp cannot diverge wildly from air temp
        for r in self.valid:
            assert abs(r.soil_temp_c - r.air_temp_c) < 20.0


# ---------------------------------------------------------------------------
# Dynamics
# ---------------------------------------------------------------------------

class TestDynamics:
    def test_battery_decreases_over_time(self):
        # Battery is always discharged (never recharged), so after enough steps
        # the last reading must be strictly lower than the first.
        valid = []
        for line in _take(simulate(interval=0, seed=SEED), 400):
            r = parse_line(line)
            if r is not None and r.battery is not None:
                valid.append(r.battery.percent)
        # 300+ steps × ≥ 0.003 %/step = ≥ 0.9 % discharge → clearly detectable
        assert len(valid) >= 200
        assert valid[-1] < valid[0]

    def test_soil_temp_lags_air_temp(self):
        # Collect sequential readings and verify soil temp changes more slowly
        # than air temp (smaller step-to-step deltas).
        air_deltas, soil_deltas = [], []
        prev = None
        for line in _take(simulate(interval=0, seed=SEED), 100):
            r = parse_line(line)
            if r is None:
                continue
            if prev is not None:
                air_deltas.append(abs(r.air_temp_c - prev.air_temp_c))
                soil_deltas.append(abs(r.soil_temp_c - prev.soil_temp_c))
            prev = r
        assert sum(air_deltas) > sum(soil_deltas)


# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------

class TestFaultInjection:
    def test_broken_lines_occur(self):
        # P(zero broken in 500 steps | p=0.01) ≈ 0.7 % — effectively impossible
        # with a fixed seed.
        lines = _take(simulate(interval=0, seed=SEED), 500)
        broken = [line for line in lines if parse_line(line) is None]
        assert len(broken) >= 1

    def test_err_channels_occur(self):
        err_count = 0
        for line in _take(simulate(interval=0, seed=SEED), 500):
            r = parse_line(line)
            if r is not None:
                err_count += sum(1 for ch in r.adc if ch.status == "err")
        assert err_count >= 1

    def test_broken_lines_are_minority(self):
        lines = _take(simulate(interval=0, seed=SEED), 200)
        broken_ratio = sum(1 for line in lines if parse_line(line) is None) / len(lines)
        assert broken_ratio < 0.10   # never more than 10 %


# ---------------------------------------------------------------------------
# _moisture_to_raw helper
# ---------------------------------------------------------------------------

class TestMoistureToRaw:
    DRY, WET = 26000, 12000

    def test_dry_boundary(self):
        assert _moisture_to_raw(0.0, self.DRY, self.WET) == self.DRY

    def test_wet_boundary(self):
        assert _moisture_to_raw(100.0, self.DRY, self.WET) == self.WET

    def test_midpoint(self):
        assert _moisture_to_raw(50.0, self.DRY, self.WET) == 19000

    def test_roundtrip_with_parser(self):
        """_moisture_to_raw must be the exact inverse of the parser's _moisture_pct."""
        for pct in [0.0, 10.0, 25.0, 50.0, 75.0, 90.0, 100.0]:
            raw = _moisture_to_raw(pct, self.DRY, self.WET)
            recovered = _moisture_pct(raw, self.DRY, self.WET)
            assert recovered == pytest.approx(pct, abs=0.01)
