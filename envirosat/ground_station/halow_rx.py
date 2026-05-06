#!/usr/bin/env python3
"""
EnviroSat — ground_station/halow_rx.py
HaLow long-range receiver for the ground station.

Receives full 30-field JSON records from the EnviroSat satellite via the
Morse Micro HaLow USB modem on /dev/ttyUSB0.

Designed to run as a background daemon thread alongside the NRF24L01 receiver
in ground_station.py — both receivers write to the same CSVLogger, which is
thread-safe. HaLow delivers FULL telemetry records; NRF delivers compact ones.

Usage (as thread from ground_station.py):
    from halow_rx import HALowReceiver
    halow = HALowReceiver(csv_logger=csv_log, callback=on_halow_record)
    t = threading.Thread(target=halow.run, args=(shutdown_event,), daemon=True)
    t.start()

Usage (standalone — for testing the HaLow link alone):
    python halow_rx.py

Author:  EnviroSat Team
Licence: MIT
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import serial

# Import config constants — fall back to defaults if run standalone
try:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from config import HALOW_PORT, HALOW_BAUD, HALOW_TIMEOUT, GROUND_OUTPUT_DIR
except ImportError:
    HALOW_PORT        = "/dev/ttyUSB0"
    HALOW_BAUD        = 115200
    HALOW_TIMEOUT     = 2.0
    GROUND_OUTPUT_DIR = "~/envirosat_ground_station"

log = logging.getLogger("halow_rx")

FRAME_DELIMITER = b'\n'       # Must match halow_tx.py


class HALowReceiver:
    """
    Receive full JSON telemetry records from the satellite over HaLow.

    Args:
        csv_logger: Optional CSVLogger instance shared with the NRF receiver.
                    Both receivers write records to the same CSV file
                    (CSVLogger.write() is thread-safe).
        callback:   Optional callable(record: dict) invoked for each
                    successfully decoded record. Used by ground_station.py
                    to update the live display.
    """

    def __init__(self, csv_logger=None, callback=None):
        self._csv_logger   = csv_logger
        self._callback     = callback
        self._serial       = None
        self._connected    = False
        self._lock         = threading.Lock()
        self._packet_count = 0
        self._initialise()

    # ── Connection management ──────────────────────────────────────────

    def _initialise(self):
        """Open the HaLow USB serial port."""
        try:
            self._serial = serial.Serial(
                port=HALOW_PORT,
                baudrate=HALOW_BAUD,
                timeout=HALOW_TIMEOUT,
            )
            self._connected = True
            log.info(f"HaLow receiver opened on {HALOW_PORT} @ {HALOW_BAUD} baud.")
        except serial.SerialException as exc:
            log.error(f"Cannot open HaLow port {HALOW_PORT}: {exc}")
            log.warning("HaLow reception unavailable — NRF link still active.")
            self._serial = None
        except Exception as exc:
            log.error(f"HaLow receiver init failed: {exc}")
            self._serial = None

    def _ensure_connected(self) -> bool:
        """Attempt reconnection if the port is closed."""
        if self._connected and self._serial and self._serial.is_open:
            return True
        try:
            if self._serial is None:
                self._serial = serial.Serial(
                    port=HALOW_PORT,
                    baudrate=HALOW_BAUD,
                    timeout=HALOW_TIMEOUT,
                )
            elif not self._serial.is_open:
                self._serial.open()
            self._connected = True
            log.info("HaLow receiver reconnected.")
            return True
        except Exception as exc:
            log.debug(f"HaLow reconnection failed: {exc}")
            self._connected = False
            return False

    # ── Background receive loop ────────────────────────────────────────

    def run(self, shutdown_event: threading.Event):
        """
        Read JSON frames from the HaLow modem in a background thread.

        Each newline-delimited JSON frame from halow_tx.py is decoded,
        logged to CSV, and passed to the callback function.
        Automatically retries the connection if the modem is disconnected.
        """
        log.info("HaLow receive loop starting.")

        while not shutdown_event.is_set():
            if not self._ensure_connected():
                # Wait before retrying so we don't hammer the OS
                shutdown_event.wait(HALOW_TIMEOUT)
                continue

            try:
                # readline() blocks up to HALOW_TIMEOUT seconds
                raw = self._serial.readline()
                if not raw:
                    continue

                # Strip the frame delimiter and any whitespace
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                try:
                    record = json.loads(text)
                except json.JSONDecodeError as exc:
                    log.warning(f"HaLow bad JSON: {exc}  raw={raw[:80]!r}")
                    continue

                # Stamp with ground-station receive time
                record["received_at"] = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                record["link"] = "halow"   # Mark which radio delivered this

                with self._lock:
                    self._packet_count += 1
                    count = self._packet_count

                log.info(
                    f"HaLow RX #{count} — {record.get('satellite_id','?')} "
                    f"@ {record.get('timestamp','?')}  "
                    f"({len(text)} bytes)"
                )

                # Write to shared CSV logger (thread-safe)
                if self._csv_logger is not None:
                    try:
                        self._csv_logger.write(record)
                    except Exception as exc:
                        log.warning(f"HaLow CSV write failed: {exc}")

                # Notify the display / main thread
                if self._callback is not None:
                    try:
                        self._callback(record, count, source="HaLow")
                    except Exception as exc:
                        log.debug(f"HaLow callback error: {exc}")

            except serial.SerialException as exc:
                log.warning(f"HaLow serial error: {exc} — reconnecting …")
                self._connected = False
                self._serial = None
                shutdown_event.wait(2.0)
            except Exception as exc:
                log.warning(f"HaLow receive error: {exc}")
                shutdown_event.wait(1.0)

        log.info(f"HaLow receive loop stopped. {self._packet_count} packets received.")

    # ── Public helpers ─────────────────────────────────────────────────

    @property
    def packet_count(self) -> int:
        """Return the total number of HaLow packets received (thread-safe)."""
        with self._lock:
            return self._packet_count

    def close(self):
        """Close the serial port cleanly."""
        if self._serial is not None:
            try:
                self._serial.close()
                log.info("HaLow receiver serial port closed.")
            except Exception:
                pass
            self._serial = None
            self._connected = False


# ── Standalone entry point ─────────────────────────────────────────────

def main():
    """Run the HaLow receiver standalone for link testing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  [%(levelname)s]  %(message)s",
        datefmt="%H:%M:%S",
    )

    # Minimal CSV logger for standalone mode
    output_dir = os.path.expanduser(GROUND_OUTPUT_DIR)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    shutdown_event = threading.Event()

    def on_record(record, count, source="HaLow"):
        print(f"\n[{source} #{count}] {json.dumps(record, indent=2)}")

    receiver = HALowReceiver(csv_logger=None, callback=on_record)

    log.info("HaLow standalone receiver running. Press Ctrl+C to stop.")
    try:
        receiver.run(shutdown_event)
    except KeyboardInterrupt:
        shutdown_event.set()

    receiver.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
