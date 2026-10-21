"""Check sensor readings against configured thresholds and emit alerts."""

from __future__ import annotations

from typing import Optional

from app.models import Reading

# Canonical set of all alert type strings produced by check_alerts().
# Tests and demo mode derive their expected sets from this constant.
ALL_ALERT_TYPES: frozenset[str] = frozenset({
    "sensor_error",
    "soil_moisture_low",
    "air_temp_low",
    "air_temp_high",
    "soil_temp_low",
    "soil_temp_high",
    "battery_low",
})


def check_alerts(reading: Reading, config: dict) -> list[dict]:
    """Return active alerts for *reading* based on *config* thresholds.

    Each alert: {type, severity, message, dev, ch}.
    dev/ch are None for alerts not tied to a specific channel.
    Boundary values do NOT trigger alerts (strict < / >).
    Missing values (None) are silently skipped.
    """
    alerts: list[dict] = []
    thresholds = config.get("thresholds", {})

    sensor_names: dict[tuple[int, int], str] = {
        (s["dev"], s["ch"]): s.get("name", f"Sensor {s['dev']}:{s['ch']}")
        for s in config.get("sensors", [])
    }

    def _name(dev: int, ch: int) -> str:
        return sensor_names.get((dev, ch), f"Sensor {dev}:{ch}")

    # ── Channel alerts ────────────────────────────────────────────────────────
    soil_min: Optional[float] = thresholds.get("soil_moisture_min_percent")
    for ch in reading.channels:
        name = _name(ch.dev, ch.ch)
        if ch.status == "err":
            alerts.append({
                "type": "sensor_error",
                "severity": "error",
                "message": f"Sensorfehler: {name}",
                "dev": ch.dev,
                "ch": ch.ch,
            })
        elif soil_min is not None and ch.moisture_pct is not None:
            if ch.moisture_pct < soil_min:
                alerts.append({
                    "type": "soil_moisture_low",
                    "severity": "warning",
                    "message": f"Bodenfeuchte zu niedrig: {name} ({ch.moisture_pct:.1f} %)",
                    "dev": ch.dev,
                    "ch": ch.ch,
                })

    # ── Air temperature ───────────────────────────────────────────────────────
    air_min: Optional[float] = thresholds.get("air_temp_min_c")
    air_max: Optional[float] = thresholds.get("air_temp_max_c")
    if reading.air_temp_c is not None:
        if air_min is not None and reading.air_temp_c < air_min:
            alerts.append({
                "type": "air_temp_low",
                "severity": "warning",
                "message": f"Lufttemperatur zu niedrig: {reading.air_temp_c:.1f} °C",
                "dev": None,
                "ch": None,
            })
        if air_max is not None and reading.air_temp_c > air_max:
            alerts.append({
                "type": "air_temp_high",
                "severity": "warning",
                "message": f"Lufttemperatur zu hoch: {reading.air_temp_c:.1f} °C",
                "dev": None,
                "ch": None,
            })

    # ── Soil temperature ──────────────────────────────────────────────────────
    soil_t_min: Optional[float] = thresholds.get("soil_temp_min_c")
    soil_t_max: Optional[float] = thresholds.get("soil_temp_max_c")
    if reading.soil_temp_c is not None:
        if soil_t_min is not None and reading.soil_temp_c < soil_t_min:
            alerts.append({
                "type": "soil_temp_low",
                "severity": "warning",
                "message": f"Bodentemperatur zu niedrig: {reading.soil_temp_c:.1f} °C",
                "dev": None,
                "ch": None,
            })
        if soil_t_max is not None and reading.soil_temp_c > soil_t_max:
            alerts.append({
                "type": "soil_temp_high",
                "severity": "warning",
                "message": f"Bodentemperatur zu hoch: {reading.soil_temp_c:.1f} °C",
                "dev": None,
                "ch": None,
            })

    # ── Battery ───────────────────────────────────────────────────────────────
    batt_min: Optional[float] = thresholds.get("battery_min_percent")
    if reading.battery is not None and batt_min is not None:
        if reading.battery.percent < batt_min:
            alerts.append({
                "type": "battery_low",
                "severity": "warning",
                "message": f"Batterie schwach: {reading.battery.percent:.0f} %",
                "dev": None,
                "ch": None,
            })

    return alerts
