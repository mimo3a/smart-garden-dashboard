"""FastAPI application – Smart Garden Dashboard.

CLI usage::

    python -m app.main                                      # simulator, localhost only
    python -m app.main --port COM5                          # UART mode, localhost only
    python -m app.main --host 0.0.0.0 --port COM5          # expose on all interfaces
    python -m app.main --port COM5 --baud 115200 --db garden.db --keep-days 7
    python -m app.main --demo                               # demo mode (cycles alarm scenarios)
"""

from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

from app.alerts import check_alerts
from app.config import get_config
from app.db import history_buckets, init_db, insert_reading, latest_reading, purge_older_than
from app.models import AdcChannel, BatteryReading, Reading
from app.serial_reader import DataSource, SerialReader
from app.simulator import DemoSimulatorReader, SimulatorReader

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent / "static"

# Set once before uvicorn starts (see __main__ block).
# Tests inject a pre-built Namespace via monkeypatch before TestClient starts.
_args: Optional[argparse.Namespace] = None


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smart Garden Dashboard")
    p.add_argument("--port", default=None,
                   help="Serial port, e.g. COM5 or /dev/ttyACM0")
    p.add_argument("--baud", type=int, default=115200,
                   help="Baud rate (default 115200)")
    p.add_argument("--simulate", action="store_true",
                   help="Force simulator mode even if --port is given")
    p.add_argument("--demo", action="store_true",
                   help="Demo mode: cycles through alarm scenarios (implies --simulate)")
    p.add_argument("--db", default="garden.db",
                   help="SQLite database file path (default garden.db)")
    p.add_argument("--keep-days", type=int, default=7, dest="keep_days",
                   help="Purge readings older than N days on startup (default 7)")
    p.add_argument("--host", default="127.0.0.1",
                   help="Bind host (default 127.0.0.1; use 0.0.0.0 to expose on all interfaces)")
    return p.parse_args()


def _row_to_reading(row: dict) -> Reading:
    """Reconstruct a Reading from a latest_reading() dict for alert computation."""
    channels: list[AdcChannel] = []
    for c in row.get("channels", []):
        dev = c.get("dev")
        ch_idx = c.get("ch")
        if dev is None or ch_idx is None:
            logger.warning("Skipping channel with missing dev/ch: %r", c)
            continue
        try:
            channels.append(AdcChannel(
                dev=dev,
                ch=ch_idx,
                raw=c.get("raw"),
                status=c.get("status", "ok"),
                moisture_pct=c.get("moisture_pct"),
            ))
        except Exception as exc:
            logger.warning("Skipping invalid channel %r: %s", c, exc)

    battery: Optional[BatteryReading] = None
    batt_pct = row.get("battery_percent")
    batt_v = row.get("battery_voltage")
    if batt_pct is not None and batt_v is not None:
        battery = BatteryReading(voltage=batt_v, percent=batt_pct)

    ts_str = row.get("ts", "")
    try:
        ts = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        logger.warning("Invalid timestamp %r in DB row, using now", ts_str)
        ts = datetime.now(tz=timezone.utc)

    return Reading(
        timestamp=ts,
        channels=channels,
        air_temp_c=row.get("air_temp_c"),
        soil_temp_c=row.get("soil_temp_c"),
        battery=battery,
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    global _args
    if _args is None:
        _args = _parse_args()

    init_db(Path(_args.db))
    purge_older_than(_args.keep_days)

    use_demo: bool = getattr(_args, "demo", False)
    use_simulator: bool = use_demo or _args.simulate or not _args.port

    if use_demo:
        source: DataSource = DemoSimulatorReader()
        source_label = "demo"
    elif use_simulator:
        source = SimulatorReader()
        source_label = "simulator"
    else:
        source = SerialReader(_args.port, _args.baud)
        source_label = "uart"

    def on_reading(reading: Reading) -> None:
        try:
            insert_reading(reading, source=source_label)
        except Exception as exc:
            logger.error("insert_reading failed: %s", exc)

    source.start(on_reading)
    logger.info("Data source started: %s (%s)", type(source).__name__, source_label)

    yield

    source.stop()
    logger.info("Data source stopped")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(title="Smart Garden Dashboard", lifespan=lifespan)


@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/latest")
def api_latest() -> dict:
    """Return the most recent sensor snapshot including all channels and alerts."""
    row = latest_reading()
    if row is None:
        raise HTTPException(status_code=404, detail="No readings yet")

    alerts: list[dict] = []
    try:
        reading = _row_to_reading(row)
        alerts = check_alerts(reading, get_config())
    except Exception as exc:
        logger.warning("check_alerts failed: %s", exc)

    row["alerts"] = alerts
    return row


@app.get("/api/history")
def api_history(
    minutes: int = Query(default=60, ge=1, le=1440,
                         description="Time window in minutes (1–1440)"),
    max_points: int = Query(default=300, ge=10, le=1000,
                            description="Maximum number of data points (10–1000)"),
) -> list:
    """Return time-bucketed readings from the last *minutes* minutes.

    If the window contains more readings than *max_points*, values are averaged
    into equal-width time buckets entirely in SQL.
    """
    return history_buckets(minutes, max_points)


@app.get("/api/config")
def api_config() -> dict:
    """Return the sensor calibration and alert thresholds from config.json."""
    cfg = get_config()
    if not cfg:
        raise HTTPException(status_code=500, detail="Cannot read config")
    return cfg


# Static files are mounted last so API routes always take priority.
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run("app.main:app", host=_args.host, port=8000, reload=False)
