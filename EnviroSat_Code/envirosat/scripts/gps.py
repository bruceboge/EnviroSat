#!/usr/bin/env python3
"""
EnviroSat — scripts/gps.py
Reads the u-blox NEO-M8M GPS module over UART.

The GPS connects to the Grove UART port on the Grove Base Hat,
which maps to GPIO 14 (TX) and GPIO 15 (RX), accessible at
/dev/serial0 once the Pi's serial console is disabled in raspi-config.

The module streams NMEA sentences continuously at 9600 baud.
This script runs as a background thread (gps.run(shutdown_event))
and keeps the latest fix cached. The main loop calls gps.latest()
to get a snapshot without blocking.

Cold start: 30–90 seconds outdoors to acquire first fix.
Warm start: < 5 seconds after a brief power interruption.

Author:  EnviroSat Team
Licence: MIT
"""

import logging
import serial
import threading
import pynmea2
import time

log = logging.getLogger("gps")

NO_FIX = {
    "lat":       None,
    "lon":       None,
    "altitude":  None,
    "speed_kts": None,
    "gps_time":  None,
    "fix":       False,
    "satellites": 0,
}


class GPSReader:
    """
    Background NMEA reader for the NEO-M8M GPS module.

    Usage:
        gps = GPSReader()
        t = threading.Thread(target=gps.run, args=(shutdown_event,), daemon=True)
        t.start()
        ...
        fix = gps.latest()   # non-blocking snapshot
    """

    def __init__(self, port: str = "/dev/serial0", baud: int = 9600):
        self._port  = port
        self._baud  = baud
        self._lock  = threading.Lock()
        self._data  = dict(NO_FIX)
        self._ready = False

    def run(self, shutdown_event: threading.Event):
        """
        Open the serial port and read NMEA sentences continuously.
        Runs until shutdown_event is set.
        """
        log.info(f"GPS reader starting on {self._port} at {self._baud} baud.")
        while not shutdown_event.is_set():
            try:
                with serial.Serial(self._port, self._baud, timeout=2) as ser:
                    log.info("GPS serial port open.")
                    while not shutdown_event.is_set():
                        try:
                            line = ser.readline().decode("ascii", errors="replace").strip()
                            self._parse(line)
                        except serial.SerialException as exc:
                            log.warning(f"GPS serial read error: {exc}")
                            break
            except serial.SerialException as exc:
                log.error(f"Cannot open GPS serial port {self._port}: {exc}")
                log.info("Retrying GPS in 10 seconds …")
                shutdown_event.wait(10)

        log.info("GPS reader stopped.")

    def _parse(self, line: str):
        """Parse a single NMEA sentence and update the cached fix."""
        if not line.startswith("$"):
            return
        try:
            msg = pynmea2.parse(line)
        except pynmea2.ParseError:
            return

        # GGA — position, altitude, satellite count
        if isinstance(msg, pynmea2.GGA):
            fix_quality = getattr(msg, "gps_qual", 0)
            if fix_quality and fix_quality > 0:
                with self._lock:
                    self._data = {
                        "lat":        round(float(msg.latitude),  6) if msg.latitude  else None,
                        "lon":        round(float(msg.longitude), 6) if msg.longitude else None,
                        "altitude":   round(float(msg.altitude),  1) if msg.altitude  else None,
                        "speed_kts":  self._data.get("speed_kts"),
                        "gps_time":   str(msg.timestamp) if msg.timestamp else None,
                        "fix":        True,
                        "satellites": int(msg.num_sats) if msg.num_sats else 0,
                    }
                if not self._ready:
                    self._ready = True
                    log.info(f"GPS first fix acquired: lat={self._data['lat']} lon={self._data['lon']}")
            else:
                with self._lock:
                    self._data = dict(NO_FIX)

        # RMC — speed over ground
        elif isinstance(msg, pynmea2.RMC):
            if msg.status == "A":           # A = valid
                with self._lock:
                    self._data["speed_kts"] = round(float(msg.spd_over_grnd), 2) if msg.spd_over_grnd else None

    def latest(self) -> dict:
        """Return a snapshot of the most recent GPS fix (thread-safe)."""
        with self._lock:
            return dict(self._data)

    @property
    def has_fix(self) -> bool:
        with self._lock:
            return self._data["fix"]
