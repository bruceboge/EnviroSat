#!/usr/bin/env python3
"""
EnviroSat — scripts/halow_tx.py
HaLow long-range WiFi transmitter via Morse Micro modem.

The Morse Micro HaLow module connects via USB/UART and transmits
full 30-field JSON records without the 32-byte NRF24L01 limit.

Both NRF24L01+ (short-range, compact) and HaLow (long-range, full)
transmit simultaneously each cycle from main.py.

Hardware: Morse Micro HaLow USB modem on /dev/ttyUSB0
Author:   EnviroSat Team
Licence:  MIT
"""

import json
import logging
import serial
import threading

from config import HALOW_PORT, HALOW_BAUD, HALOW_TIMEOUT, HALOW_RETRY_INTERVAL

log = logging.getLogger("halow_tx")

# ── Transmission configuration ────────────────────────────────────────
MAX_RETRIES     = 3
FRAME_DELIMITER = b'\n'       # End-of-frame marker (must match halow_rx.py)


class HALowTransmitter:
    """
    Transmit data records to the HaLow ground station via Morse Micro modem.

    Features:
      - Transmits FULL 30+ field records (no payload limit)
      - Automatic reconnection on serial failure
      - Thread-safe transmission with a lock

    Usage:
        halow = HALowTransmitter()
        success = halow.transmit(record_dict)
        halow.close()
    """

    def __init__(self):
        self._serial    = None
        self._lock      = threading.Lock()
        self._connected = False
        self._initialise()

    def _initialise(self):
        """Open serial connection to the HaLow modem."""
        try:
            self._serial = serial.Serial(
                port=HALOW_PORT,
                baudrate=HALOW_BAUD,
                timeout=HALOW_TIMEOUT,
                write_timeout=2.0,
            )
            self._connected = True
            log.info(f"HaLow modem initialised on {HALOW_PORT} @ {HALOW_BAUD} baud.")
        except serial.SerialException as exc:
            log.error(f"Cannot open HaLow port {HALOW_PORT}: {exc}")
            log.warning("HaLow transmissions will be skipped.")
            self._serial    = None
            self._connected = False
        except Exception as exc:
            log.error(f"HaLow initialisation failed: {exc}")
            self._serial    = None
            self._connected = False

    def _ensure_connected(self) -> bool:
        """Check connection; attempt reconnection if disconnected."""
        if self._connected and self._serial is not None:
            return True
        try:
            if self._serial is None:
                self._serial = serial.Serial(
                    port=HALOW_PORT,
                    baudrate=HALOW_BAUD,
                    timeout=HALOW_TIMEOUT,
                    write_timeout=2.0,
                )
            elif not self._serial.is_open:
                self._serial.open()
            self._connected = True
            log.info("HaLow reconnected.")
            return True
        except Exception as exc:
            log.debug(f"HaLow reconnection failed: {exc}")
            self._connected = False
            return False

    def transmit(self, record: dict) -> bool:
        """
        Transmit a complete data record via HaLow (no payload limit).

        Args:
            record: Dict with 30+ fields (satellite_id, timestamp, etc.)

        Returns:
            True if sent successfully, False on failure.
        """
        if not self._ensure_connected():
            return False

        try:
            payload = json.dumps(record, separators=(",", ":")).encode("utf-8")

            with self._lock:
                self._serial.write(payload + FRAME_DELIMITER)
                self._serial.flush()

                # Read optional ACK from modem
                try:
                    ack = self._serial.readline()
                    if ack:
                        log.debug(f"HaLow TX ACK received ({len(payload)} bytes).")
                except serial.SerialTimeoutException:
                    log.debug(f"HaLow TX sent ({len(payload)} bytes, no ACK).")

            return True

        except (serial.SerialException, BrokenPipeError) as exc:
            log.warning(f"HaLow serial error: {exc}")
            self._connected = False
            return False
        except (TypeError, ValueError) as exc:
            log.error(f"HaLow payload error: {exc}")
            return False
        except Exception as exc:
            log.error(f"HaLow transmit error: {exc}")
            return False

    def close(self):
        """Close serial connection cleanly."""
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                    log.info("HaLow connection closed.")
                except Exception as exc:
                    log.warning(f"Error closing HaLow: {exc}")
                self._serial    = None
                self._connected = False
