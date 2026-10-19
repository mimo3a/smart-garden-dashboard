"""Parse and validate a single JSON line received via UART into a Reading."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.models import AdcChannel, BatteryReading, Reading

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"
_calibration_cache: Optional[dict[tuple[int, int], dict]] = None


def _load_calibration() -> dict[tuple[int, int], dict]:
    """Return sensor calibration keyed by (dev, ch), loaded once from config.json."""
    global _calibration_cache
    if _calibration_cache is not None:
        return _calibration_cache
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as fh:
            cfg = json.load(fh)
        _calibration_cache = {
            (entry["dev"], entry["ch"]): entry
            for entry in cfg.get("sensors", [])
        }
    except Exception as exc:
        logger.warning("Could not load calibration from %s: %s", _CONFIG_PATH, exc)
        _calibration_cache = {}
    return _calibration_cache


def _moisture_pct(raw: int, dry_raw: int, wet_raw: int) -> float:
    """Convert raw ADC value to soil moisture %, clamped to 0–100.

    dry_raw maps to 0 %, wet_raw maps to 100 %.
    """
    if dry_raw == wet_raw:
        return 0.0
    pct = (dry_raw - raw) / (dry_raw - wet_raw) * 100.0
    return max(0.0, min(100.0, pct))


def _safe_float(value: Any) -> Optional[float]:
    """Return float(value), or None if conversion fails."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Cannot convert %r to float, using None", value)
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Return int(value), or None if conversion fails."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Cannot convert %r to int, using None", value)
        return None


def parse_line(line: str) -> Optional[Reading]:
    """Parse a single UART JSON line into a Reading; return None on invalid input.

    Expected wire format::

        {"channels":[{"dev":0,"ch":0,"status":0,"raw":15234}, ...],
         "air_temp_c":22.4,"soil_temp_c":18.1,
         "battery":{"voltage":3.91,"percent":76}}

    Rules:
    - ``status`` is an integer: 0 = ok, any other value = err.
    - ``air_temp_c``, ``soil_temp_c``, ``battery`` are optional.
    - Fewer than 16 channels are allowed (partial hardware build).
    - Non-JSON lines (e.g. boot messages) are discarded and return None.
    - Lines with no usable data (no channels, no temps, no battery) return None.
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON line: %r", line[:120])
        return None

    if not isinstance(data, dict):
        logger.warning(
            "JSON is not an object (got %s): %r", type(data).__name__, line[:120]
        )
        return None

    calibration = _load_calibration()
    channels: list[AdcChannel] = []
    raw_channels = data.get("channels")

    if raw_channels is not None:
        if not isinstance(raw_channels, list):
            logger.warning(
                "'channels' is not a list (%s), ignoring", type(raw_channels).__name__
            )
        else:
            for ch_data in raw_channels:
                if not isinstance(ch_data, dict):
                    logger.warning(
                        "Channel entry is not an object (%r), discarding", ch_data
                    )
                    continue

                dev_idx = _safe_int(ch_data.get("dev"))
                ch_idx = _safe_int(ch_data.get("ch"))

                if dev_idx is None or ch_idx is None:
                    logger.warning(
                        "Channel entry missing 'dev' or 'ch', discarding: %r", ch_data
                    )
                    continue

                raw = _safe_int(ch_data.get("raw"))
                # status is an integer on the wire: 0 = ok, anything else = err
                status_int = _safe_int(ch_data.get("status"))
                status = "ok" if status_int == 0 else "err"

                moisture: Optional[float] = None
                cal_key = (dev_idx, ch_idx)
                if status == "ok" and raw is not None and cal_key in calibration:
                    cal = calibration[cal_key]
                    moisture = _moisture_pct(raw, cal["dry_raw"], cal["wet_raw"])

                try:
                    channels.append(
                        AdcChannel(
                            dev=dev_idx,
                            ch=ch_idx,
                            raw=raw,
                            status=status,
                            moisture_pct=moisture,
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "Skipping invalid channel %r: %s", ch_data, exc
                    )

    battery: Optional[BatteryReading] = None
    batt_data = data.get("battery")
    if batt_data is not None:
        try:
            battery = BatteryReading(
                voltage=batt_data["voltage"],
                percent=batt_data["percent"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping malformed battery data: %s", exc)

    air_temp_c = _safe_float(data.get("air_temp_c"))
    soil_temp_c = _safe_float(data.get("soil_temp_c"))

    if not channels and air_temp_c is None and soil_temp_c is None and battery is None:
        logger.warning("No usable data in line, discarding: %r", line[:120])
        return None

    try:
        return Reading(
            timestamp=datetime.now(tz=timezone.utc),
            channels=channels,
            air_temp_c=air_temp_c,
            soil_temp_c=soil_temp_c,
            battery=battery,
        )
    except Exception as exc:
        logger.warning("Could not construct Reading: %s", exc)
        return None
