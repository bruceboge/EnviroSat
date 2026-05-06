#!/usr/bin/env python3
"""
EnviroSat — scripts/gps.py
Background GPS reader for the u-blox Neo-6M module.

The Neo-6M connects to the Pi's hardware UART (/dev/serial0) at 9600 baud
and streams NMEA-0183 sentences continuously. This script parses:
  $GPRMC / $GNRMC  — lat, lon, speed, UTC time, fix status
  $GPGGA / $GNGGA  — altitude, fix quality, satellite count

The reader runs as a background daemon thread, updating a cached dict.
The main loop calls gps.latest() to get a non-blocking snapshot.

If the GPS module is absent or the serial port cannot be opened, all
fields return None — the rest of the system continues normally.

Hardware notes:
  - Enable hardware UART via raspi-config:
      Interface Options → Serial → disable login shell, enable hardware serial
  - Cold start TTFF: up to 12 minutes.  Warm start: ~26 seconds.
  - Ensure clear sky view for reliable fix acquisition.

Author:  EnviroSat Team
Licence: MIT
"""

import logging
import threading
import time
from datetime import timezone

log = logging.getLogger("gps")

# ── Sentinel returned when no fix or initialisation failed ────────────
EMPTY = {
    "lat":         None,
    "lon":         None,
    "altitude":    None,
    "gps_time":    None,
    "fix":         False,
    "satellites":  None,
    "speed_knots": None,
}


class GPSReader:
    """
    Background NMEA reader for the u-blox Neo-6M GPS module.

    Usage:
        gps = GPSReader(port="/dev/serial0", baud=9600)
        t = threading.Thread(target=gps.run, args=(shutdown_event,), daemon=True)
        t.start()
        ...
        data = gps.latest()   # non-blocking snapshot
        gps.close()
    """

    def __init__(self, port: str = "/dev/serial0", baud: int = 9600):
        self._port   = port
        self._baud   = baud
        self._lock   = threading.Lock()
        self._data   = dict(EMPTY)
        self._serial = None
        self._initialise()

    # ── Initialisation ─────────────────────────────────────────────────

    def _initialise(self):
        """Open serial connection to the GPS module."""
        try:
            import serial
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baud,
                timeout=1.0,     # readline() will return after 1 s if no data
            )
            log.info(f"GPS serial opened: {self._port} @ {self._baud} baud.")
        except ImportError:
            log.error("pyserial not installed — run: pip3 install pyserial")
            self._serial = None
        except Exception as exc:
            log.error(f"Cannot open GPS port {self._port}: {exc}")
            log.warning("GPS data will be unavailable — all fields will return None.")
            self._serial = None

    # ── NMEA parsers ───────────────────────────────────────────────────

    def _parse_rmc(self, sentence: str):
        """
        Parse $GPRMC / $GNRMC for lat, lon, speed, UTC time and fix status.
        Updates the cache; does nothing on a bad or void sentence.
        """
        try:
            import pynmea2
            msg = pynmea2.parse(sentence)

            if msg.status != 'A':
                # 'V' = void / no fix — mark fix False but keep last good coords
                with self._lock:
                    self._data["fix"] = False
                return

            # pynmea2 returns decimal-degree floats directly
            lat = msg.latitude
            lon = msg.longitude

            # Build ISO-8601 UTC timestamp
            try:
                dt = msg.datetime.replace(tzinfo=timezone.utc)
                gps_time = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                gps_time = None

            speed = float(msg.spd_over_grnd) if msg.spd_over_grnd else None

            with self._lock:
                self._data.update({
                    "lat":         round(lat, 6),
                    "lon":         round(lon, 6),
                    "gps_time":    gps_time,
                    "fix":         True,
                    "speed_knots": round(speed, 2) if speed is not None else None,
                })
        except Exception as exc:
            log.debug(f"GPRMC parse error: {exc}")

    def _parse_gga(self, sentence: str):
        """
        Parse $GPGGA / $GNGGA for altitude and satellite count.
        Updates the cache; does nothing on a bad sentence.
        """
        try:
            import pynmea2
            msg = pynmea2.parse(sentence)

            fix_quality = int(msg.gps_qual) if msg.gps_qual else 0
            if fix_quality == 0:
                return

            altitude   = float(msg.altitude) if msg.altitude else None
            satellites = int(msg.num_sats)   if msg.num_sats else None

            with self._lock:
                self._data.update({
                    "altitude":   round(altitude, 1) if altitude is not None else None,
                    "satellites": satellites,
                })
        except Exception as exc:
            log.debug(f"GPGGA parse error: {exc}")

    # ── Background thread ──────────────────────────────────────────────

    def run(self, shutdown_event: threading.Event):
        """
        Read NMEA lines from the GPS and update the cached data dict.
        Designed to run as a daemon thread; exits when shutdown_event is set.
        """
        log.info("GPS reader loop starting.")

        if self._serial is None:
            log.warning("GPS serial not available — reader loop exiting immediately.")
            return

        while not shutdown_event.is_set():
            try:
                # readline() blocks for up to 1 s (serial timeout), then returns b""
                raw = self._serial.readline()
                if not raw:
                    continue

                try:
                    line = raw.decode("ascii", errors="replace").strip()
                except Exception:
                    continue

                if not line.startswith("$"):
                    continue

                sentence_type = line.split(",")[0]

                if sentence_type in ("$GPRMC", "$GNRMC"):
                    self._parse_rmc(line)
                elif sentence_type in ("$GPGGA", "$GNGGA"):
                    self._parse_gga(line)
                # $GPGSV, $GPGSA, $GPVTG etc. are intentionally ignored

            except Exception as exc:
                log.warning(f"GPS read error: {exc}")
                shutdown_event.wait(1.0)    # Brief pause before retrying

        log.info("GPS reader loop stopped.")

    # ── Public interface ───────────────────────────────────────────────

    def latest(self) -> dict:
        """Return a thread-safe snapshot of the most recent GPS data."""
        with self._lock:
            return dict(self._data)

    def close(self):
        """Close the serial port cleanly."""
        if self._serial is not None:
            try:
                self._serial.close()
                log.info("GPS serial port closed.")
            except Exception:
                pass
