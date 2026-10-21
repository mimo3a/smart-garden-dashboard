"""Generates realistic fake sensor readings for use without physical hardware."""

from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
from typing import Callable, Iterator, Optional

from app.config import get_calibration
from app.models import Reading
from app.parser import parse_line
from app.serial_reader import DataSource

logger = logging.getLogger(__name__)

_NUM_DEVS = 4
_NUM_CH = 4
_NUM_SENSORS = _NUM_DEVS * _NUM_CH  # 16 total

# Steps per scenario in demo mode (~1 s/step → 25 s per scenario).
_DEMO_STEPS_PER_SCENARIO = 25

# (moisture_pct, air_temp_c, soil_temp_c, battery_pct, err_channels_set)
_DEMO_SCENARIOS: list[tuple[float, float, float, float, set[tuple[int, int]]]] = [
    (65.0, 22.0, 18.0, 75.0, set()),       # 0: normal        – kein Alarm
    (10.0, 22.0, 18.0, 75.0, set()),       # 1: trocken       → soil_moisture_low
    (65.0, 38.0, 28.0, 75.0, set()),       # 2: Hitze Luft    → air_temp_high
    (65.0,  2.0,  2.0, 75.0, set()),       # 3: Frost         → air_temp_low + soil_temp_low
    (65.0, 22.0, 18.0,  5.0, set()),       # 4: Batterie leer → battery_low
    (65.0, 22.0, 18.0, 75.0, {(0, 0)}),   # 5: Sensorfehler  → sensor_error
    (65.0, 32.0, 32.0, 75.0, set()),       # 6: heißer Boden  → soil_temp_high
    #   air_temp 32 °C < 35 °C-Grenze → kein air_temp_high
]


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
    calibration = get_calibration()

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


def simulate_demo(interval: float = 1.0, seed: Optional[int] = None) -> Iterator[str]:
    """Yield demo JSON lines cycling through alarm scenarios.

    Scenarios (each _DEMO_STEPS_PER_SCENARIO steps ≈ 25 s at 1 s/step):
      0: normal           – kein Alarm
      1: Beet trocknet    – soil_moisture_low
      2: Hitze Luft       – air_temp_high
      3: Frost            – air_temp_low + soil_temp_low
      4: Batterie leer    – battery_low
      5: Sensorfehler     – sensor_error (dev=0, ch=0)
      6: heißer Boden     – soil_temp_high

    After all 7 scenarios the cycle repeats, so every alert type defined in
    ALL_ALERT_TYPES appears within ~3 minutes (7 × 25 s).

    Args:
        interval: Seconds to sleep between yields (pass 0 in tests).
        seed:     Optional RNG seed for reproducible noise.
    """
    rng = random.Random(seed)
    calibration = get_calibration()

    scenario_idx = 0
    step_in_scenario = 0

    while True:
        sc_idx = scenario_idx % len(_DEMO_SCENARIOS)
        moisture_pct_base, air_base, soil_base, batt_base, err_channels = _DEMO_SCENARIOS[sc_idx]

        # Build channel list with small Gaussian noise
        channel_list = []
        for dev in range(_NUM_DEVS):
            for ch in range(_NUM_CH):
                if (dev, ch) in err_channels:
                    channel_list.append({"dev": dev, "ch": ch, "status": 1, "raw": 0})
                else:
                    pct = max(0.0, min(100.0, moisture_pct_base + rng.gauss(0, 0.5)))
                    cal = calibration.get((dev, ch), {"dry_raw": 26000, "wet_raw": 12000})
                    raw = _moisture_to_raw(pct, cal["dry_raw"], cal["wet_raw"])
                    channel_list.append({"dev": dev, "ch": ch, "status": 0, "raw": raw})

        air_temp = air_base + rng.gauss(0, 0.2)
        soil_temp = soil_base + rng.gauss(0, 0.1)
        battery_pct = max(0.0, min(100.0, batt_base + rng.gauss(0, 0.3)))
        battery_voltage = 3.0 + battery_pct / 100.0 * 1.2

        yield json.dumps({
            "channels": channel_list,
            "air_temp_c": round(air_temp, 1),
            "soil_temp_c": round(soil_temp, 1),
            "battery": {
                "voltage": round(battery_voltage, 2),
                "percent": round(battery_pct, 1),
            },
        })

        step_in_scenario += 1
        if step_in_scenario >= _DEMO_STEPS_PER_SCENARIO:
            step_in_scenario = 0
            scenario_idx += 1

        time.sleep(interval)


# ---------------------------------------------------------------------------
# _BaseSimulatorReader — shared background-thread logic
# ---------------------------------------------------------------------------

class _BaseSimulatorReader(DataSource):
    """Common start/stop/run logic for simulator-based readers.

    Subclasses supply the line source by overriding ``_generator()``.
    """

    _thread_name: str = "simulator"

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _generator(self) -> Iterator[str]:
        raise NotImplementedError

    def start(self, callback: Callable[[Reading], None]) -> None:
        """Start the background thread and deliver readings to *callback*."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(callback,),
            daemon=True,
            name=self._thread_name,
        )
        self._thread.start()
        logger.info("%s started", type(self).__name__)

    def stop(self) -> None:
        """Signal the thread to stop and block until it finishes."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        logger.info("%s stopped", type(self).__name__)

    def _run(self, callback: Callable[[Reading], None]) -> None:
        for line in self._generator():
            if self._stop_event.is_set():
                break
            reading = parse_line(line)
            if reading is not None:
                callback(reading)
            # Interruptible 1-second sleep; returns True immediately if stop() was called.
            if self._stop_event.wait(1.0):
                break


# ---------------------------------------------------------------------------
# SimulatorReader — realistic random-walk data
# ---------------------------------------------------------------------------

class SimulatorReader(_BaseSimulatorReader):
    """Wraps the simulate() generator in a background thread.

    Inherits the same DataSource interface as SerialReader so main.py can
    treat both sources identically::

        source = SimulatorReader()          # or SerialReader(port, baud)
        source.start(on_reading)
        ...
        source.stop()
    """

    _thread_name = "simulator"

    def _generator(self) -> Iterator[str]:
        return simulate(interval=0)


# ---------------------------------------------------------------------------
# DemoSimulatorReader — cycles through alarm scenarios
# ---------------------------------------------------------------------------

class DemoSimulatorReader(_BaseSimulatorReader):
    """Wraps simulate_demo() in a background thread for --demo mode.

    Cycles through all alarm scenarios so every alert type becomes visible
    in the dashboard within ~2.5 minutes.
    """

    _thread_name = "demo-simulator"

    def _generator(self) -> Iterator[str]:
        return simulate_demo(interval=0)
