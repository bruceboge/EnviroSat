#!/usr/bin/env python3
"""
EnviroSat — config.py
Single source of truth for all hardware constants and tuneable parameters.

Edit ONLY this file to change hardware settings.
All other scripts import their constants from here.

Author:  EnviroSat Team
Licence: MIT
"""

# ── System Identity ───────────────────────────────────────────────────
SATELLITE_ID        = "ES-01"

# ── Collection Timing ─────────────────────────────────────────────────
COLLECTION_INTERVAL = 60        # seconds between sensor reads
CAMERA_INTERVAL     = 300       # seconds between automatic captures

# ── Directory Paths (satellite) ───────────────────────────────────────
IMAGE_DIR = "/home/envirosat/envirosat/images"
LOG_DIR   = "/home/envirosat/envirosat/logs"

# ── GPS — u-blox Neo-6M ───────────────────────────────────────────────
GPS_PORT = "/dev/serial0"       # Hardware UART on Pi 3B+
GPS_BAUD = 9600                 # Neo-6M factory default baud rate

# ── NRF24L01+ — short-range 2.4 GHz ──────────────────────────────────
# CE remapped from GPIO17 → GPIO24 (GPIO17 conflicts with UPS HAT).
# CSN uses the Pi's hardware SPI CE0 line (GPIO8).
NRF_CE_PIN    = 24
NRF_CSN_PIN   = 8
NRF_CHANNEL   = 76              # RF channel 0–125. MUST match ground station.
NRF_DATA_RATE = 2               # 2 = 2 Mbps  |  1 = 1 Mbps  |  0 = 250 Kbps
NRF_PA_LEVEL  = 0               # 0=MIN  1=LOW  2=HIGH  3=MAX
NRF_ADDRESS   = b'\xE7\xE7\xE7\xE7\xE7'   # 5-byte pipe address

# ── HaLow — Morse Micro long-range WiFi ──────────────────────────────
HALOW_PORT           = "/dev/ttyUSB0"   # USB serial port for HaLow modem
HALOW_BAUD           = 115200           # Morse Micro modem baud rate
HALOW_TIMEOUT        = 2.0              # Serial read timeout in seconds
HALOW_RETRY_INTERVAL = 30               # Seconds between reconnection attempts

# ── Enviro+ Sensors ───────────────────────────────────────────────────
# TEMP_FACTOR: CPU-heat correction. Increase if still reading high.
# Calibrate against a reference thermometer. Typical range: 1.5–3.0.
TEMP_FACTOR        = 2.25
GAS_WARMUP_SECONDS = 600    # MICS6814 stabilisation time after power-on

# ── Camera — Arducam UC-444 dual-camera mux ───────────────────────────
ARDUCAM_I2C_ADDR = 0x70
STILL_RESOLUTION = (2592, 1944)   # OV5647 full resolution
JPEG_QUALITY     = 85             # 0–100

# ── Power Monitor — Waveshare UPS HAT (INA219) ────────────────────────
# Some Waveshare boards use 0x36 — confirm with: sudo i2cdetect -y 1
UPS_HAT_ADDR           = 0x42
POWER_POLL_INTERVAL    = 30      # Battery check interval (seconds)
LOW_BATTERY_VOLTS      = 3.40    # Trigger safe shutdown below this
CRITICAL_BATTERY_VOLTS = 3.20    # Immediate shutdown regardless of state
WARNING_VOLTS          = 3.60    # Log warning, keep running
FULL_VOLTS             = 4.15    # 18650 cell fully charged voltage

# ── IMU — MPU-9250 / MPU-6500 ─────────────────────────────────────────
IMU_I2C_ADDR    = 0x68
IMU_SAMPLE_RATE = 0.5      # Seconds between background IMU samples

# ── Ground Station ────────────────────────────────────────────────────
GROUND_OUTPUT_DIR = "~/envirosat_ground_station"
DASHBOARD_PORT    = 8080

# ── System Logging (satellite) ────────────────────────────────────────
LOG_MAX_BYTES    = 10 * 1024 * 1024   # 10 MB per rotating log file
LOG_BACKUP_COUNT = 5                  # Keep 5 backup files
