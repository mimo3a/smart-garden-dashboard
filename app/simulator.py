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
_NUM_DEVS = 4
_NUM_CH = 4
_NUM_SENSORS = _NUM_DEVS * _NUM_CH  # 16 total


def _load_calibration_by_sensor() -> dict[tuple[int, int], dict]:
    """Load per-sensor calibration from config.json, keyed by (dev, ch)."""
    defaults = {
        (dev, ch): {"dry_raw": 26000, "wet_raw": 12000}
        for dev in range(_NUM_DEVS)
        for ch in range(_NUM_CH)
    }
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as fh:
            cfg = json.load(fh)
        cal = {(e["dev"], e["ch"]): e for e in cfg.get("sensors", [])}
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

    Generates all 16 sensors (4 ADS1115 devices × 4 channels each).  Each
    sensor has an independent moisture state with its own evaporation rate and
    watering events, so different beds can be at different moisture levels.

    Wire format::

        {"channels":[{"dev":0,"ch":0,"status":0,"raw":15234}, ...],
         "air_temp_c":22.4,"soil_temp_c":18.1,
         "battery":{"voltage":3.91,"percent":76}}

    Fault injection (~2 % overall):
    - ~1 % of iterations: yield a malformed JSON line.
    - ~0.5 % per channel per iteration: status 1 (err) instead of 0 (ok).

    Args:
        interval: Seconds to sleep between yields (pass 0 in tests).
        seed:     Optional seed for the internal RNG (for reproducible tests).
    """
    rng = random.Random(seed)
    calibration = _load_calibration_by_sensor()

    # Independent moisture state for each of the 16 sensors: moisture[dev*4+ch]
    moisture: list[float] = [
        rng.uniform(50.0, 75.0) for _ in range(_NUM_SENSORS)
    ]
    air_temp: float = _day_cycle_target() + rng.gauss(0, 1.0)
    soil_temp: float = air_temp - rng.uniform(2.0, 5.0)
    battery_pct: float = rng.uniform(70.0, 90.0)

    while True:
        # ── fault injection: broken JSON line (~1 %) ─────────────────────────
        if rng.random() < 0.01:
            yield '{"channels": [broken'
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

        # ── 16 soil moisture sensors (independent per bed) ───────────────────
        channel_list = []
        for dev in range(_NUM_DEVS):
            for ch in range(_NUM_CH):
                idx = dev * _NUM_CH + ch
                if rng.random() < 0.005:                    # watering event
                    moisture[idx] = rng.uniform(75.0, 98.0)
                else:
                    # Each bed dries at a slightly different rate
                    moisture[idx] -= rng.uniform(0.03, 0.12)
                moisture[idx] = max(5.0, min(100.0, moisture[idx]))

                if rng.random() < 0.005:                    # ~0.5 % err per channel
                    channel_list.append({"dev": dev, "ch": ch, "status": 1, "raw": 0})
                else:
                    cal = calibration.get((dev, ch), {"dry_raw": 26000, "wet_raw": 12000})
                    raw = _moisture_to_raw(moisture[idx], cal["dry_raw"], cal["wet_raw"])
                    channel_list.append({"dev": dev, "ch": ch, "status": 0, "raw": raw})

        yield json.dumps(
            {
                "channels": channel_list,
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
