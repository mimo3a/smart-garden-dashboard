"""Tests for SerialReader (app.serial_reader) and SimulatorReader (app.simulator)."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

import serial
import pytest

from app.models import Reading
from app.serial_reader import DataSource, SerialReader
from app.simulator import SimulatorReader

VALID_LINE = json.dumps(
    {
        "adc": [
            {"ch": 0, "raw": 15234, "status": "ok"},
            {"ch": 1, "raw": 14980, "status": "ok"},
            {"ch": 2, "raw": 0, "status": "err"},
            {"ch": 3, "raw": 16012, "status": "ok"},
        ],
        "air_temp_c": 22.4,
        "soil_temp_c": 18.1,
        "battery": {"voltage": 3.91, "percent": 76},
    }
)


# ---------------------------------------------------------------------------
# Mock helpers — never exhaust, so no StopIteration leaks into reader threads
# ---------------------------------------------------------------------------

def _make_ctx(mock_ser: MagicMock) -> MagicMock:
    """Wrap a mock serial object in a context-manager mock."""
    ctx = MagicMock()
    ctx.__enter__.return_value = mock_ser
    ctx.__exit__.return_value = False
    return ctx


def _blocking_ser() -> MagicMock:
    """Serial mock whose readline() always returns b'' (simulates an idle connection).

    Used as a fallback so the reader thread can block without raising StopIteration
    after all planned interactions are done.
    """
    ser = MagicMock()

    def _idle_read():
        time.sleep(0.005)   # tiny sleep to avoid busy-spin
        return b""

    ser.readline.side_effect = _idle_read
    return ser


def _make_serial_cls(*planned_ctxs: MagicMock) -> MagicMock:
    """Return a mock serial.Serial class that serves *planned_ctxs* in order,
    then returns a blocking fallback context for every subsequent call.

    This prevents StopIteration when the reader thread reconnects after
    all planned interactions have been consumed.
    """
    fallback = _make_ctx(_blocking_ser())
    queue = list(planned_ctxs)

    mock_cls = MagicMock()

    def _factory(*args, **kwargs):
        return queue.pop(0) if queue else fallback

    mock_cls.side_effect = _factory
    return mock_cls


def _ser_with_lines(*lines: bytes) -> MagicMock:
    """Serial mock that delivers *lines* then blocks on every subsequent read."""
    ser = MagicMock()
    it = iter(lines)

    def _read():
        try:
            return next(it)
        except StopIteration:
            time.sleep(0.005)
            return b""

    ser.readline.side_effect = _read
    return ser


# ---------------------------------------------------------------------------
# SerialReader
# ---------------------------------------------------------------------------

class TestSerialReader:
    def test_delivers_valid_readings_to_callback(self):
        received_event = threading.Event()
        received: list[Reading] = []

        ser = _ser_with_lines(VALID_LINE.encode() + b"\n")
        mock_cls = _make_serial_cls(_make_ctx(ser))

        with patch("app.serial_reader.serial.Serial", mock_cls):
            with patch("app.serial_reader._RECONNECT_DELAY", 0.0):
                reader = SerialReader("COM5", 115200)
                reader.start(lambda r: (received.append(r), received_event.set()))
                assert received_event.wait(timeout=2.0), "callback not called within 2 s"
                reader.stop()

        assert len(received) >= 1
        assert isinstance(received[0], Reading)
        assert received[0].air_temp_c == pytest.approx(22.4)

    def test_broken_json_not_delivered_to_callback(self):
        received: list[Reading] = []

        ser = _ser_with_lines(b"not valid json\n", b"also broken\n")
        mock_cls = _make_serial_cls(_make_ctx(ser))

        with patch("app.serial_reader.serial.Serial", mock_cls):
            with patch("app.serial_reader._RECONNECT_DELAY", 0.0):
                reader = SerialReader("COM5", 115200)
                reader.start(received.append)
                time.sleep(0.1)
                reader.stop()

        assert received == []

    def test_stop_joins_thread(self):
        # connect always fails → reader spins in reconnect loop
        mock_cls = MagicMock()
        mock_cls.side_effect = serial.SerialException("no device")

        with patch("app.serial_reader.serial.Serial", mock_cls):
            with patch("app.serial_reader._RECONNECT_DELAY", 0.0):
                reader = SerialReader("COM5", 115200)
                reader.start(lambda r: None)
                reader.stop()

        assert reader._thread is not None
        assert not reader._thread.is_alive()

    def test_reconnects_after_connect_failure(self):
        """First connect raises SerialException; second connection delivers a reading."""
        received_event = threading.Event()
        received: list[Reading] = []

        ctx_fail = MagicMock()
        ctx_fail.__enter__.side_effect = serial.SerialException("port busy")
        ctx_fail.__exit__.return_value = False

        ctx_ok = _make_ctx(_ser_with_lines(VALID_LINE.encode() + b"\n"))
        mock_cls = _make_serial_cls(ctx_fail, ctx_ok)

        with patch("app.serial_reader.serial.Serial", mock_cls):
            with patch("app.serial_reader._RECONNECT_DELAY", 0.0):
                reader = SerialReader("COM5", 115200)
                reader.start(lambda r: (received.append(r), received_event.set()))
                assert received_event.wait(timeout=2.0), "no reading after reconnect"
                reader.stop()

        assert mock_cls.call_count >= 2
        assert len(received) >= 1

    def test_read_error_triggers_reconnect(self):
        """readline() raises mid-stream; reader reconnects and delivers again."""
        received_event = threading.Event()
        received: list[Reading] = []

        ser1 = MagicMock()
        ser1.readline.side_effect = serial.SerialException("cable pulled")
        ctx1 = _make_ctx(ser1)
        ctx2 = _make_ctx(_ser_with_lines(VALID_LINE.encode() + b"\n"))
        mock_cls = _make_serial_cls(ctx1, ctx2)

        with patch("app.serial_reader.serial.Serial", mock_cls):
            with patch("app.serial_reader._RECONNECT_DELAY", 0.0):
                reader = SerialReader("COM5", 115200)
                reader.start(lambda r: (received.append(r), received_event.set()))
                assert received_event.wait(timeout=2.0), "no reading after reconnect"
                reader.stop()

        assert mock_cls.call_count >= 2
        assert len(received) >= 1

    def test_empty_lines_ignored(self):
        """Timeout-induced empty reads and whitespace-only lines call no callback."""
        received: list[Reading] = []

        ser = _ser_with_lines(b"", b"\n", b"   \n")
        mock_cls = _make_serial_cls(_make_ctx(ser))

        with patch("app.serial_reader.serial.Serial", mock_cls):
            with patch("app.serial_reader._RECONNECT_DELAY", 0.0):
                reader = SerialReader("COM5", 115200)
                reader.start(received.append)
                time.sleep(0.1)
                reader.stop()

        assert received == []

    def test_callback_exception_does_not_stop_reader(self):
        """An exception raised by the callback must not kill the reader thread;
        subsequent readings must still be delivered."""
        call_count = 0
        second_event = threading.Event()

        def bad_callback(r: Reading) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated DB error")
            second_event.set()

        encoded = VALID_LINE.encode() + b"\n"
        # Deliver multiple readings from the same connection
        ser = _ser_with_lines(encoded, encoded, encoded)
        mock_cls = _make_serial_cls(_make_ctx(ser))

        with patch("app.serial_reader.serial.Serial", mock_cls):
            with patch("app.serial_reader._RECONNECT_DELAY", 0.0):
                reader = SerialReader("COM5", 115200)
                reader.start(bad_callback)
                assert second_event.wait(timeout=2.0), "second reading not delivered after callback error"
                reader.stop()

        assert call_count >= 2


# ---------------------------------------------------------------------------
# SimulatorReader
# ---------------------------------------------------------------------------

class TestSimulatorReader:
    def test_delivers_readings_to_callback(self):
        received_event = threading.Event()
        received: list[Reading] = []

        reader = SimulatorReader()
        reader.start(lambda r: (received.append(r), received_event.set()))
        assert received_event.wait(timeout=3.0), "no reading within 3 s"
        reader.stop()

        assert len(received) >= 1
        assert isinstance(received[0], Reading)

    def test_stop_joins_thread(self):
        reader = SimulatorReader()
        reader.start(lambda r: None)
        reader.stop()

        assert reader._thread is not None
        assert not reader._thread.is_alive()

    def test_readings_are_reading_instances(self):
        received: list[Reading] = []
        three_event = threading.Event()

        def collect(r: Reading) -> None:
            received.append(r)
            if len(received) >= 3:
                three_event.set()

        reader = SimulatorReader()
        reader.start(collect)
        three_event.wait(timeout=5.0)
        reader.stop()

        assert all(isinstance(r, Reading) for r in received)

    def test_stop_before_start_does_not_crash(self):
        SimulatorReader().stop()


# ---------------------------------------------------------------------------
# Common DataSource interface
# ---------------------------------------------------------------------------

class TestDataSourceInterface:
    def test_serial_reader_is_datasource_subclass(self):
        assert isinstance(SerialReader("COM5"), DataSource)

    def test_simulator_reader_is_datasource_subclass(self):
        assert isinstance(SimulatorReader(), DataSource)

    def test_serial_reader_has_start_and_stop(self):
        reader = SerialReader("COM5")
        assert callable(reader.start)
        assert callable(reader.stop)

    def test_simulator_reader_has_start_and_stop(self):
        reader = SimulatorReader()
        assert callable(reader.start)
        assert callable(reader.stop)
