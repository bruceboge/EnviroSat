#!/usr/bin/env python3
"""
EnviroSat — main.py
Master startup and scheduler script.

This is the only script launched at boot (via systemd).
It starts all subsystem threads, runs the 60-second data
collection loop, and handles clean shutdown when asked.

Hardware: Raspberry Pi 3B+
Author:   EnviroSat Team
Licence:  MIT
"""

import time
import threading
import signal
import sys
import logging
import logging.handlers
from datetime import datetime, timezone

# ── Local modules ────────────────────────────────────────────────────
from scripts.sensors       import SensorReader
from scripts.gps           import GPSReader
from scripts.imu           import IMUReader
from scripts.camera        import CameraController
from scripts.nrf_tx        import NRFTransmitter
from scripts.halow_tx      import HALowTransmitter
from scripts.power_monitor import PowerMonitor
from scripts.logger        import DataLogger
from config import (
    SATELLITE_ID, COLLECTION_INTERVAL, CAMERA_INTERVAL,
    IMAGE_DIR, LOG_DIR, GPS_PORT, GPS_BAUD,
    LOG_MAX_BYTES, LOG_BACKUP_COUNT,
)

# ── Logging setup ────────────────────────────────────────────────────
_formatter = logging.Formatter(
    fmt="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_formatter)
# RotatingFileHandler prevents the log from filling the microSD card.
_file_handler = logging.handlers.RotatingFileHandler(
    filename=f"{LOG_DIR}/system.log",
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
)
_file_handler.setFormatter(_formatter)
logging.root.setLevel(logging.INFO)
logging.root.addHandler(_stream_handler)
logging.root.addHandler(_file_handler)
log = logging.getLogger("main")

# ── Configuration — imported from config.py ──────────────────────────
# SATELLITE_ID, COLLECTION_INTERVAL, CAMERA_INTERVAL, IMAGE_DIR,
# LOG_DIR, GPS_PORT, GPS_BAUD are imported at the top of this file.

# ── NRF command codes (must match ground_station.py) ─────────────────
CMD_PING     = b'\x01'
CMD_FAST     = b'\x02'   # Switch to 10-second collection interval
CMD_SLOW     = b'\x03'   # Return to 60-second collection interval
CMD_CAPTURE  = b'\x04'   # Trigger a camera capture immediately
CMD_CAMERA_B = b'\x05'   # Switch to Camera B
CMD_SHUTDOWN = b'\x06'   # Safe shutdown
CMD_STATUS   = b'\x07'   # Log a status report

# ── Global shutdown flag ─────────────────────────────────────────────
shutdown_event = threading.Event()


def signal_handler(sig, frame):
    """Catch SIGTERM / SIGINT and trigger clean shutdown."""
    log.info("Shutdown signal received — stopping all subsystems.")
    shutdown_event.set()


def build_data_record(sensors, gps, imu, battery_v, uptime_s):
    """Assemble one complete timestamped JSON-serialisable record."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "satellite_id":  SATELLITE_ID,
        "timestamp":     ts,
        "uptime_s":      round(uptime_s, 1),
        # Environmental
        "temperature_c": sensors.get("temperature"),
        "pressure_hpa":  sensors.get("pressure"),
        "humidity_pct":  sensors.get("humidity"),
        "lux":           sensors.get("lux"),
        "proximity":     sensors.get("proximity"),
        "gas_co":        sensors.get("gas_co"),
        "gas_no2":       sensors.get("gas_no2"),
        "gas_nh3":       sensors.get("gas_nh3"),
        "pm1":           sensors.get("pm1"),
        "pm2_5":         sensors.get("pm2_5"),
        "pm10":          sensors.get("pm10"),
        # Position
        "lat":           gps.get("lat"),
        "lon":           gps.get("lon"),
        "altitude_m":    gps.get("altitude"),
        "gps_time":      gps.get("gps_time"),
        "gps_fix":       gps.get("fix"),
        # Attitude
        "accel_x":       imu.get("accel_x"),
        "accel_y":       imu.get("accel_y"),
        "accel_z":       imu.get("accel_z"),
        "gyro_x":        imu.get("gyro_x"),
        "gyro_y":        imu.get("gyro_y"),
        "gyro_z":        imu.get("gyro_z"),
        "heading_deg":   imu.get("heading"),
        # Power
        "battery_v":     round(battery_v, 3) if battery_v else None,
        # Status flags (bitfield: b0=sensor_err, b1=gps_no_fix, b2=low_batt)
        "flags":         0x00,
    }


def camera_loop(camera, shutdown_event):
    """Background thread — captures an image every CAMERA_INTERVAL seconds."""
    log.info("Camera loop started.")
    while not shutdown_event.is_set():
        shutdown_event.wait(CAMERA_INTERVAL)
        if shutdown_event.is_set():
            break
        try:
            filename = camera.capture(IMAGE_DIR)
            log.info(f"Image captured: {filename}")
        except Exception as exc:
            log.warning(f"Camera capture failed: {exc}")
    log.info("Camera loop stopped.")


def main():
    log.info("=" * 60)
    log.info(f"EnviroSat {SATELLITE_ID} — starting up")
    log.info("=" * 60)

    start_time = time.monotonic()

    # ── Register shutdown signals ────────────────────────────────────
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT,  signal_handler)

    # ── Initialise subsystems ────────────────────────────────────────
    log.info("Initialising sensor reader …")
    sensors = SensorReader()

    log.info("Initialising GPS reader …")
    gps = GPSReader(port=GPS_PORT, baud=GPS_BAUD)
    gps_thread = threading.Thread(target=gps.run, args=(shutdown_event,), daemon=True)
    gps_thread.start()

    log.info("Initialising IMU …")
    imu = IMUReader()
    imu_thread = threading.Thread(target=imu.run, args=(shutdown_event,), daemon=True)
    imu_thread.start()

    log.info("Initialising camera controller …")
    camera = CameraController()
    cam_thread = threading.Thread(target=camera_loop, args=(camera, shutdown_event), daemon=True)
    cam_thread.start()

    log.info("Initialising NRF24L01 transmitter …")
    nrf = NRFTransmitter()

    log.info("Initialising HaLow transmitter …")
    halow = HALowTransmitter()

    log.info("Initialising power monitor …")
    power = PowerMonitor(shutdown_event)
    power_thread = threading.Thread(target=power.run, daemon=True)
    power_thread.start()

    log.info("Initialising data logger …")
    logger = DataLogger(LOG_DIR)

    # ── Mutable collection interval (commands can change this) ───────
    collection_interval = [COLLECTION_INTERVAL]   # list so inner functions can mutate

    log.info("All subsystems up — entering main collection loop.")

    # ── Main loop ────────────────────────────────────────────────────
    cycle = 0
    while not shutdown_event.is_set():
        cycle_start = time.monotonic()
        cycle += 1
        log.info(f"── Cycle {cycle} ──────────────────────────────────────")

        # 1. Read all sensors
        try:
            sensor_data = sensors.read_all()
        except Exception as exc:
            log.error(f"Sensor read failed: {exc}")
            sensor_data = {}

        # 2. Get latest GPS fix
        gps_data = gps.latest()

        # 3. Get latest IMU data
        imu_data = imu.latest()

        # 4. Get battery voltage
        battery_v = power.battery_voltage()

        # 5. Build complete record
        uptime = time.monotonic() - start_time
        record = build_data_record(sensor_data, gps_data, imu_data, battery_v, uptime)

        # 6. Log to microSD
        try:
            logger.write(record)
        except Exception as exc:
            log.error(f"Logger write failed: {exc}")

        # 7. Transmit compact record over NRF24L01 (short-range link)
        try:
            nrf.transmit(record)
        except Exception as exc:
            log.warning(f"NRF24 transmit failed: {exc}")

        # 8. Transmit full record over HaLow (long-range link, no payload limit)
        try:
            halow.transmit(record)
        except Exception as exc:
            log.warning(f"HaLow transmit failed: {exc}")

        # 9. Listen briefly for ground-station commands over NRF
        cmd = nrf.listen_for_command(timeout_ms=500)
        if cmd == CMD_PING:
            log.info("Ground command: PING received.")
        elif cmd == CMD_FAST:
            collection_interval[0] = 10
            log.info("Ground command: FAST mode — collecting every 10 s.")
        elif cmd == CMD_SLOW:
            collection_interval[0] = COLLECTION_INTERVAL
            log.info(f"Ground command: SLOW mode — collecting every {COLLECTION_INTERVAL} s.")
        elif cmd == CMD_CAPTURE:
            log.info("Ground command: CAPTURE — triggering camera.")
            try:
                camera.capture(IMAGE_DIR)
            except Exception as exc:
                log.warning(f"Command-triggered capture failed: {exc}")
        elif cmd == CMD_CAMERA_B:
            log.info("Ground command: CAMERA B — switching camera.")
            camera.switch_camera()
        elif cmd == CMD_SHUTDOWN:
            log.warning("Ground command: SHUTDOWN received.")
            shutdown_event.set()
        elif cmd == CMD_STATUS:
            log.info(
                f"STATUS — cycle={cycle} battery={battery_v}V "
                f"gps_fix={gps_data.get('fix')} interval={collection_interval[0]}s"
            )

        # 10. Log cycle time and sleep for the remainder of the interval
        elapsed = time.monotonic() - cycle_start
        log.info(f"Cycle {cycle} complete in {elapsed:.2f}s  |  battery={battery_v}V")
        sleep_for = max(0, collection_interval[0] - elapsed)
        shutdown_event.wait(sleep_for)

    # ── Clean shutdown ───────────────────────────────────────────────
    log.info("Shutdown…")
    logger.close()
    nrf.close()
    halow.close()
    gps.close()
    log.info("EnviroSat stopped.")


if __name__ == "__main__":
    main()
