"""Pydantic models and dataclasses for sensor readings."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AdcChannel(BaseModel):
    """One ADS1115 channel (soil-moisture sensor)."""

    ch: int
    raw: Optional[int] = None
    status: str  # "ok" | "err"
    moisture_pct: Optional[float] = None


class BatteryReading(BaseModel):
    """Battery state."""

    voltage: float
    percent: float


class Reading(BaseModel):
    """One complete sensor snapshot received via UART."""

    timestamp: datetime
    adc: list[AdcChannel]
    air_temp_c: Optional[float] = None
    soil_temp_c: Optional[float] = None
    battery: Optional[BatteryReading] = None
