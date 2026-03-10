#!/usr/bin/env python3
"""
EnviroSat — scripts/sensors.py
Reads all Pimoroni Enviro+ HAT sensors.

Returns a flat dict of values every time read_all() is called.
Does not transmit or log — purely collects. Called by main.py
each cycle.

Sensors on board:
  BME280   — temperature, pressure, humidity  (I2C 0x76)
  LTR-559  — light level, proximity           (I2C 0x23)
  MICS6814 — CO, NO2, NH3 gas resistances     (via ADS1015 at 0x49)
  PMS5003  — PM1.0, PM2.5, PM10              (UART via Enviro+ connector)
  MEMS mic — ambient noise level              (I2S — optional)

Temperature compensation:
  The BME280 sits close to the Pi CPU. Raw readings run 3–8°C high.
  Apply the correction factor below (calibrate against a reference
  thermometer and adjust TEMP_FACTOR until readings match).

Author:  EnviroSat Team
Licence: MIT
"""

import logging
import time

log = logging.getLogger("sensors")

# ── Temperature correction ────────────────────────────────────────────
# Increase if readings still read high; decrease if over-correcting.
# Typical range: 1.5 – 3.0. Default 2.25 matches Pi 3B+ under normal load.
TEMP_FACTOR = 2.25

# ── Gas sensor warm-up ────────────────────────────────────────────────
# The MICS6814 needs ~10 minutes to stabilise after power-on.
# Readings before this time are discarded.
GAS_WARMUP_SECONDS = 600


class SensorReader:
    """Initialise all Enviro+ sensors and provide a single read_all() call."""

    def __init__(self):
        self._boot_time = time.monotonic()
        self._pms5003   = None
        self._bme280    = None
        self._ltr559    = None
        self._gas       = None
        self._initialise()

    def _initialise(self):
        try:
            from enviroplus import gas
            from enviroplus.noise import Noise
            from bme280 import BME280
            from ltr559 import LTR559
            from pms5003 import PMS5003, ReadTimeoutError
            import smbus2

            bus = smbus2.SMBus(1)

            self._bme280  = BME280(i2c_dev=bus)
            self._ltr559  = LTR559()
            self._gas     = gas
            self._noise   = Noise()
            self._pms5003 = PMS5003()
            self._ReadTimeoutError = ReadTimeoutError

            # Force a first BME280 read to initialise internal compensation
            _ = self._bme280.get_temperature()
            log.info("All Enviro+ sensors initialised.")
        except Exception as exc:
            log.error(f"Sensor initialisation failed: {exc}")
            log.warning("Sensor reads will return None values.")

    def _compensated_temperature(self):
        """Return CPU-heat-corrected temperature in °C."""
        try:
            raw_temp = self._bme280.get_temperature()
            # Read CPU temperature from the system file
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                cpu_temp = int(f.read()) / 1000.0
            corrected = raw_temp - ((cpu_temp - raw_temp) / TEMP_FACTOR)
            return round(corrected, 2)
        except Exception as exc:
            log.warning(f"Temperature read failed: {exc}")
            return None

    def read_all(self) -> dict:
        """
        Read every Enviro+ sensor and return a flat dict.
        Any sensor that fails returns None for its fields.
        """
        data = {}

        # ── BME280 — temperature, pressure, humidity ─────────────────
        try:
            data["temperature"] = self._compensated_temperature()
            data["pressure"]    = round(self._bme280.get_pressure(), 2)
            data["humidity"]    = round(self._bme280.get_humidity(), 2)
        except Exception as exc:
            log.warning(f"BME280 read error: {exc}")
            data.update({"temperature": None, "pressure": None, "humidity": None})

        # ── LTR-559 — light and proximity ────────────────────────────
        try:
            data["lux"]       = round(self._ltr559.get_lux(), 2)
            data["proximity"] = self._ltr559.get_proximity()
        except Exception as exc:
            log.warning(f"LTR-559 read error: {exc}")
            data.update({"lux": None, "proximity": None})

        # ── MICS6814 — gas sensors (skip if still warming up) ────────
        uptime = time.monotonic() - self._boot_time
        if uptime < GAS_WARMUP_SECONDS:
            remaining = int(GAS_WARMUP_SECONDS - uptime)
            log.debug(f"Gas sensor warming up — {remaining}s remaining.")
            data.update({"gas_co": None, "gas_no2": None, "gas_nh3": None})
        else:
            try:
                readings       = self._gas.read_all()
                data["gas_co"]  = round(readings.reducing,  2)
                data["gas_no2"] = round(readings.oxidising, 2)
                data["gas_nh3"] = round(readings.nh3,       2)
            except Exception as exc:
                log.warning(f"MICS6814 read error: {exc}")
                data.update({"gas_co": None, "gas_no2": None, "gas_nh3": None})

        # ── PMS5003 — particulate matter ─────────────────────────────
        try:
            pm = self._pms5003.read()
            data["pm1"]   = pm.pm_ug_per_m3(1.0)
            data["pm2_5"] = pm.pm_ug_per_m3(2.5)
            data["pm10"]  = pm.pm_ug_per_m3(10)
        except self._ReadTimeoutError:
            log.warning("PMS5003 read timeout — no particle data this cycle.")
            data.update({"pm1": None, "pm2_5": None, "pm10": None})
        except Exception as exc:
            log.warning(f"PMS5003 read error: {exc}")
            data.update({"pm1": None, "pm2_5": None, "pm10": None})

        # ── MEMS microphone — ambient noise ──────────────────────────
        try:
            low, mid, high, amp = self._noise.get_noise_profile()
            data["noise_amp"] = round(amp, 4)
        except Exception as exc:
            log.debug(f"Noise read skipped: {exc}")
            data["noise_amp"] = None

        return data
