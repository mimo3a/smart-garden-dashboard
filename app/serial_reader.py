"""Background thread that reads UART, handles reconnect, and feeds the parser."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import serial

from app.models import Reading
from app.parser import parse_line

logger = logging.getLogger(__name__)

_RECONNECT_DELAY: float = 3.0  # seconds between reconnect attempts


# ---------------------------------------------------------------------------
# Common interface
# ---------------------------------------------------------------------------

class DataSource:
    """Base class shared by SerialReader and SimulatorReader.

    Both sources run in a background thread and deliver parsed Readings to a
    caller-supplied callback.  main.py can use either source identically::

        source: DataSource = SerialReader(port, baud)   # or SimulatorReader()
        source.start(on_reading)
        ...
        source.stop()
    """

    def start(self, callback: Callable[[Reading], None]) -> None:
        """Start delivering readings to *callback* in a background thread."""
        raise NotImplementedError

    def stop(self) -> None:
        """Signal the background thread to stop and block until it finishes."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Serial implementation
# ---------------------------------------------------------------------------

class SerialReader(DataSource):
    """Reads UART data from *port* in a background thread.

    Reconnects automatically after connection loss (after *_RECONNECT_DELAY*
    seconds).  Delivers parsed Readings to the callback supplied to
    :meth:`start`.
    """

    def __init__(self, port: str, baud: int = 115200) -> None:
        self._port = port
        self._baud = baud
        self._callback: Optional[Callable[[Reading], None]] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, callback: Callable[[Reading], None]) -> None:
        """Start the reader thread and deliver readings to *callback*."""
        self._callback = callback
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"serial-reader-{self._port}",
        )
        self._thread.start()
        logger.info("SerialReader started on %s at %d baud", self._port, self._baud)

    def stop(self) -> None:
        """Signal the reader thread to stop and block until it finishes."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=_RECONNECT_DELAY + 2)
        logger.info("SerialReader stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with serial.Serial(self._port, self._baud, timeout=1) as ser:
                    logger.info("Connected to %s", self._port)
                    self._read_loop(ser)
            except serial.SerialException as exc:
                logger.warning("Cannot connect to %s: %s", self._port, exc)
            except Exception as exc:
                # Unexpected error during connect/read (e.g. OS error, driver bug).
                # Treat like a connection failure: log and reconnect after delay.
                logger.error(
                    "Unexpected error on %s: %s", self._port, exc, exc_info=True
                )

            if not self._stop_event.is_set():
                logger.info(
                    "Reconnecting to %s in %.0f s …", self._port, _RECONNECT_DELAY
                )
                # wait() returns immediately when stop() sets the event
                self._stop_event.wait(_RECONNECT_DELAY)

    def _read_loop(self, ser: serial.Serial) -> None:
        """Inner read loop; returns on stop request or read error."""
        while not self._stop_event.is_set():
            try:
                raw = ser.readline()
            except serial.SerialException as exc:
                logger.warning("Read error on %s: %s", self._port, exc)
                return  # let _run handle reconnect

            if not raw:
                continue  # timeout with no data

            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            reading = parse_line(line)
            if reading is not None and self._callback is not None:
                try:
                    self._callback(reading)
                except Exception as exc:
                    # A failing callback (e.g. DB error) must not stop the reader.
                    logger.error(
                        "Callback raised an exception, reading discarded: %s",
                        exc,
                        exc_info=True,
                    )
