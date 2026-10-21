"""Tests for app.config (get_config / get_calibration)."""

from __future__ import annotations

import json
import os

import pytest

import app.config as config_module
from app.config import _reset_cache, get_calibration, get_config


@pytest.fixture(autouse=True)
def reset_config_cache():
    _reset_cache()
    yield
    _reset_cache()


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------

class TestGetConfig:
    def test_loads_from_file(self, tmp_path, monkeypatch):
        cfg = {"sensors": [], "thresholds": {}}
        f = tmp_path / "config.json"
        f.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        assert get_config() == cfg

    def test_caches_result(self, tmp_path, monkeypatch):
        cfg = {"sensors": [], "thresholds": {}}
        f = tmp_path / "config.json"
        f.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        first = get_config()
        second = get_config()
        assert first is second  # same object → cache hit

    def test_missing_file_returns_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_module, "_CONFIG_PATH", tmp_path / "nonexistent.json")
        assert get_config() == {}

    def test_returns_last_valid_when_file_gone(self, tmp_path, monkeypatch):
        cfg = {"sensors": [{"dev": 0, "ch": 0, "name": "X", "dry_raw": 26000, "wet_raw": 12000}]}
        f = tmp_path / "config.json"
        f.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        get_config()   # populate cache
        f.unlink()
        assert get_config() == cfg  # retains last valid

    def test_retries_after_broken_json(self, tmp_path, monkeypatch):
        """First call with broken JSON returns {}; after fixing the file succeeds."""
        cfg = {"sensors": [], "thresholds": {}}
        f = tmp_path / "config.json"
        f.write_text("not valid json {{ broken", encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        assert get_config() == {}   # no valid cache yet
        # Overwrite with valid JSON – _cached is None so next call reloads regardless of mtime
        f.write_text(json.dumps(cfg), encoding="utf-8")
        assert get_config() == cfg

    def test_reloads_on_mtime_change(self, tmp_path, monkeypatch):
        cfg1 = {"sensors": [], "thresholds": {"a": 1}}
        cfg2 = {"sensors": [], "thresholds": {"a": 2}}
        f = tmp_path / "config.json"
        f.write_text(json.dumps(cfg1), encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        get_config()  # loads cfg1 and caches mtime

        # Rewrite and bump mtime by +1 s so the cache misses
        f.write_text(json.dumps(cfg2), encoding="utf-8")
        stat = f.stat()
        os.utime(f, (stat.st_atime, stat.st_mtime + 1.0))

        assert get_config() == cfg2

    def test_keeps_last_valid_when_file_corrupted_after_load(self, tmp_path, monkeypatch):
        """If the file becomes invalid after a successful load, return the last valid config."""
        cfg = {"sensors": [], "thresholds": {}}
        f = tmp_path / "config.json"
        f.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        get_config()  # loads and caches

        # Corrupt the file and bump mtime so the cache miss triggers a reload attempt
        f.write_text("{broken json", encoding="utf-8")
        stat = f.stat()
        os.utime(f, (stat.st_atime, stat.st_mtime + 1.0))

        assert get_config() == cfg  # retains last valid


# ---------------------------------------------------------------------------
# get_calibration
# ---------------------------------------------------------------------------

class TestGetCalibration:
    def test_returns_dict_keyed_by_int_tuple(self, tmp_path, monkeypatch):
        entry = {"dev": 0, "ch": 1, "dry_raw": 26000, "wet_raw": 12000}
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"sensors": [entry]}), encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        cal = get_calibration()
        assert (0, 1) in cal

    def test_empty_on_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_module, "_CONFIG_PATH", tmp_path / "nonexistent.json")
        assert get_calibration() == {}

    def test_skips_entries_missing_dev_or_ch(self, tmp_path, monkeypatch):
        sensors = [
            {"ch": 0, "dry_raw": 26000, "wet_raw": 12000},          # missing dev
            {"dev": 1, "dry_raw": 26000, "wet_raw": 12000},          # missing ch
            {"dev": 0, "ch": 0, "dry_raw": 26000, "wet_raw": 12000}, # valid
        ]
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"sensors": sensors}), encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        cal = get_calibration()
        assert list(cal.keys()) == [(0, 0)]

    def test_key_types_are_int(self, tmp_path, monkeypatch):
        entry = {"dev": "2", "ch": "3", "dry_raw": 26000, "wet_raw": 12000}
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"sensors": [entry]}), encoding="utf-8")
        monkeypatch.setattr(config_module, "_CONFIG_PATH", f)
        cal = get_calibration()
        key = list(cal.keys())[0]
        assert isinstance(key[0], int) and isinstance(key[1], int)
        assert key == (2, 3)
