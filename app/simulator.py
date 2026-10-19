"""Generates realistic fake sensor readings for use without physical hardware."""

from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Optional

from app.models import Reading
from app.parser import parse_line
from app.serial_reader import DataSource

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"
_NUM_CHANNELS = 4


def _load_calibration_by_channel() -> dict[int, dict]:
    """Load per-channel calibration from config.json; fall back to defaults on error."""
    defaults = {ch: {"dry_raw": 26000, "wet_raw": 12000} for ch in range(_NUM_CHANNELS)}
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as fh:
            cfg = json.load(fh)
        cal = {entry["channel"]: entry for entry in cfg.get("calibration", [])}
        return cal if cal else defaults
    except Exception:
        return defaults


def _moisture_to_raw(pct: float, dry_raw: int, wet_raw: int) -> int:
    """Convert moisture % to raw ADC value (inverse of the parser's _moisture_pct).

    Clamps the result to the plausible sensor range [wet_raw - 2000, dry_raw + 2000].
    """
    raw = dry_raw - (pct / 100.0) * (dry_raw - wet_raw)
    return int(round(max(wet_raw - 2000, min(dry_raw + 2000, raw))))


def _day_cycle_target() -> float:
    """Target air temperature from a sinusoidal UTC day cycle.

    Peak ~26 °C at 14:00 UTC, trough ~10 °C at 02:00 UTC.
    """
    secs = time.time() % 86400
    # angle = π/2 when secs = 50400 (14:00 UTC) → sin = 1 → maximum
    angle = (secs - 28800) / 86400 * 2 * math.pi
    return 18.0 + 8.0 * math.sin(angle)


def simulate(interval: float = 1.0, seed: Optional[int] = None) -> Iterator[str]:
    """Yield one JSON line per *interval* seconds with realistic random-walk dynamics.

    Dynamics:
    - Soil moisture per channel: slow evaporation drift, occasional watering jump.
    - Air temperature: sinusoidal day cycle (UTC) with Gaussian noise.
    - Soil temperature: follows air temperature with thermal inertia.
    - Battery: slow, monotonic discharge.

    Fault injection (~2 % overall):
    - ~1 % of iterations: yield a malformed JSON line so the parser's error path is hit.
    - ~0.5 % per channel per iteration: status "err" instead of "ok".

    Args:
        interval: Seconds to sleep between yields (pass 0 in tests).
        seed:     Optional seed for the internal RNG (for reproducible tests).
    """
    rng = random.Random(seed)
    calibration = _load_calibration_by_channel()

    # ── initial state ────────────────────────────────────────────────────────
    moisture: list[float] = [rng.uniform(50.0, 75.0) for _ in range(_NUM_CHANNELS)]
    air_temp: float = _day_cycle_target() + rng.gauss(0, 1.0)
    soil_temp: float = air_temp - rng.uniform(2.0, 5.0)
    battery_pct: float = rng.uniform(70.0, 90.0)

    while True:
        # ── fault injection: broken JSON line (~1 %) ─────────────────────────
        if rng.random() < 0.01:
            yield '{"adc": [broken'
            time.sleep(interval)
            continue

        # ── air temperature: day-cycle pull + Gaussian noise ─────────────────
        air_temp += 0.05 * (_day_cycle_target() - air_temp) + rng.gauss(0, 0.1)
        air_temp = max(-10.0, min(50.0, air_temp))

        # ── soil temperature: thermal inertia (follows air slowly) ───────────
        soil_temp += 0.01 * (air_temp - soil_temp) + rng.gauss(0, 0.03)
        soil_temp = max(-10.0, min(45.0, soil_temp))

        # ── battery: slow monotonic discharge ────────────────────────────────
        battery_pct -= rng.uniform(0.003, 0.008)
        battery_pct = max(0.0, min(100.0, battery_pct))
        battery_voltage = 3.0 + battery_pct / 100.0 * 1.2

        # ── soil moisture + ADC channels ─────────────────────────────────────
        adc_list = []
        for ch in range(_NUM_CHANNELS):
            if rng.random() < 0.005:                   # watering event
                moisture[ch] = rng.uniform(75.0, 98.0)
            else:
                moisture[ch] -= rng.uniform(0.03, 0.10)
            moisture[ch] = max(5.0, min(100.0, moisture[ch]))

            if rng.random() < 0.005:                   # err channel (~0.5 %)
                adc_list.append({"ch": ch, "raw": 0, "status": "err"})
            else:
                cal = calibration.get(ch, {"dry_raw": 26000, "wet_raw": 12000})
                raw = _moisture_to_raw(moisture[ch], cal["dry_raw"], cal["wet_raw"])
                adc_list.append({"ch": ch, "raw": raw, "status": "ok"})

        yield json.dumps(
            {
                "adc": adc_list,
                "air_temp_c": round(air_temp, 1),
                "soil_temp_c": round(soil_temp, 1),
                "battery": {
                    "voltage": round(battery_voltage, 2),
                    "percent": round(battery_pct, 1),
                },
            }
        )
        time.sleep(interval)


# ---------------------------------------------------------------------------
# SimulatorReader — same DataSource interface as SerialReader
# ---------------------------------------------------------------------------

class SimulatorReader(DataSource):
    """Wraps the simulate() generator in a background thread.

    Inherits the same DataSource interface as SerialReader so main.py can
    treat both sources identically::

        source = SimulatorReader()          # or SerialReader(port, baud)
        source.start(on_reading)
        ...
        source.stop()
    """

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, callback: Callable[[Reading], None]) -> None:
        """Start the simulator thread and deliver readings to *callback*."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(callback,),
            daemon=True,
            name="simulator",
        )
        self._thread.start()
        logger.info("SimulatorReader started")

    def stop(self) -> None:
        """Signal the simulator thread to stop and block until it finishes."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        logger.info("SimulatorReader stopped")

    def _run(self, callback: Callable[[Reading], None]) -> None:
        for line in simulate(interval=0):
            if self._stop_event.is_set():
                break
            reading = parse_line(line)
            if reading is not None:
                callback(reading)
            # Interruptible 1-second sleep; returns True immediately if stop() was called.
            if self._stop_event.wait(1.0):
                break
