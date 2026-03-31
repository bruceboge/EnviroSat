#!/usr/bin/env python3
"""
EnviroSat — scripts/power_monitor.py
Battery voltage monitoring and safe shutdown.

The Pi UPS HAT (Waveshare) includes an INA219 current/voltage sensor
at I2C address 0x42. This script polls it every 30 seconds and triggers
a controlled shutdown when battery voltage falls below the safe threshold.

Unlike the PowerBoost 1000C (which used a hardware LBO pin), the UPS HAT
reports power state entirely over I2C. There is no GPIO pin to monitor —
all battery information is read from the INA219 registers.

The shutdown procedure:
  1. Log the event and battery voltage.
  2. Set the global shutdown_event so all threads can stop cleanly.
  3. Flush the data logger.
  4. Call 'sudo shutdown -h now' to power off the Pi safely.

Author:  EnviroSat Team
Licence: MIT
"""

import logging
import os
import subprocess
import threading
import time

log = logging.getLogger("power_monitor")

# ── UPS HAT I2C configuration ─────────────────────────────────────────
UPS_HAT_ADDR         = 0x42    # Default Waveshare UPS HAT address (some use 0x36)
POLL_INTERVAL        = 30      # Seconds between battery checks
LOW_BATTERY_VOLTS    = 3.40    # Volts — below this, shutdown is triggered
CRITICAL_BATTERY_VOLTS = 3.20  # Volts — immediate shutdown regardless of state
WARNING_VOLTS        = 3.60    # Volts — log a warning but keep running
FULL_VOLTS           = 4.15    # Volts — 18650 fully charged

# ── INA219 register addresses ─────────────────────────────────────────
INA219_REG_CONFIG    = 0x00
INA219_REG_SHUNT     = 0x01
INA219_REG_BUS       = 0x02    # Bus voltage register
INA219_REG_POWER     = 0x03
INA219_REG_CURRENT   = 0x04
INA219_REG_CALIB     = 0x05

# Calibration constants for Waveshare UPS HAT (0.01Ω shunt, 2A max)
INA219_CALIBRATION   = 4096
CURRENT_LSB          = 0.0001  # Amps per bit
BUS_VOLTAGE_LSB      = 0.004   # Volts per bit (4 mV)


class PowerMonitor:
    """
    Monitor battery voltage via the UPS HAT INA219 and trigger safe
    shutdown when voltage is critically low.

    Usage:
        power = PowerMonitor(shutdown_event)
        t = threading.Thread(target=power.run, daemon=True)
        t.start()
        ...
        volts = power.battery_voltage()
        pct   = power.battery_percent()
    """

    def __init__(self, shutdown_event: threading.Event):
        self._shutdown_event = shutdown_event
        self._lock           = threading.Lock()
        self._voltage        = None
        self._current_ma     = None
        self._bus            = None
        self._initialise()

    def _initialise(self):
        try:
            import smbus2
            self._bus = smbus2.SMBus(1)
            # Write calibration register
            self._bus.write_word_data(UPS_HAT_ADDR, INA219_REG_CALIB, self._swap16(INA219_CALIBRATION))
            # Configure for 32V range, ±2A, 12-bit ADC
            config = 0x399F
            self._bus.write_word_data(UPS_HAT_ADDR, INA219_REG_CONFIG, self._swap16(config))
            log.info(f"UPS HAT INA219 initialised at I2C 0x{UPS_HAT_ADDR:02X}.")
        except Exception as exc:
            log.error(f"Power monitor init failed: {exc}")
            log.warning("Power monitoring will be unavailable — no safe-shutdown protection.")

    @staticmethod
    def _swap16(val: int) -> int:
        """Swap byte order for 16-bit smbus word reads."""
        return ((val & 0xFF) << 8) | ((val >> 8) & 0xFF)

    def _read_voltage(self) -> float:
        """Read bus voltage from INA219 register and convert to volts."""
        raw = self._bus.read_word_data(UPS_HAT_ADDR, INA219_REG_BUS)
        raw = self._swap16(raw)
        # Bits 15:3 are voltage data; bit 0 = overflow, bit 1 = conversion ready
        voltage = (raw >> 3) * BUS_VOLTAGE_LSB
        return round(voltage, 3)

    def _read_current(self) -> float:
        """Read current from INA219 and return in milliamps."""
        raw = self._bus.read_word_data(UPS_HAT_ADDR, INA219_REG_CURRENT)
        raw = self._swap16(raw)
        if raw > 32767:
            raw -= 65536
        current_a  = raw * CURRENT_LSB
        return round(current_a * 1000, 1)

    def run(self):
        """Poll battery voltage and trigger shutdown if critically low."""
        log.info(f"Power monitor running — polling every {POLL_INTERVAL}s.")
        while not self._shutdown_event.is_set():
            if self._bus is not None:
                try:
                    volts = self._read_voltage()
                    ma    = self._read_current()
                    with self._lock:
                        self._voltage    = volts
                        self._current_ma = ma

                    log.debug(f"Battery: {volts:.3f}V  {ma:.0f}mA")

                    if volts <= CRITICAL_BATTERY_VOLTS:
                        log.critical(f"CRITICAL BATTERY: {volts:.3f}V — immediate shutdown.")
                        self._safe_shutdown()
                    elif volts <= LOW_BATTERY_VOLTS:
                        log.warning(f"LOW BATTERY: {volts:.3f}V — initiating safe shutdown.")
                        self._safe_shutdown()
                    elif volts <= WARNING_VOLTS:
                        log.warning(f"Battery low warning: {volts:.3f}V")

                except Exception as exc:
                    log.warning(f"Battery read error: {exc}")

            self._shutdown_event.wait(POLL_INTERVAL)

        log.info("Power monitor stopped.")

    def _safe_shutdown(self):
        """Signal all threads to stop, then power off the Pi."""
        log.warning("Initiating safe shutdown sequence …")
        # Signal main loop and all threads
        self._shutdown_event.set()
        # Give threads 5 seconds to flush data
        time.sleep(5)
        log.warning("Calling system shutdown.")
        try:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        except Exception as exc:
            log.error(f"shutdown command failed: {exc}")

    def battery_voltage(self) -> float:
        """Return the last measured battery voltage (thread-safe)."""
        with self._lock:
            return self._voltage

    def battery_current_ma(self) -> float:
        """Return the last measured current draw in milliamps (thread-safe)."""
        with self._lock:
            return self._current_ma

    def battery_percent(self) -> int:
        """
        Estimate state of charge as a percentage.
        Linear approximation between CRITICAL_BATTERY_VOLTS and FULL_VOLTS.
        Not precise — use as a rough indicator only.
        """
        with self._lock:
            v = self._voltage
        if v is None:
            return None
        pct = (v - CRITICAL_BATTERY_VOLTS) / (FULL_VOLTS - CRITICAL_BATTERY_VOLTS) * 100
        return max(0, min(100, round(pct)))
