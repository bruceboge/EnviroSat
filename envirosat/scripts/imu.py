#!/usr/bin/env python3
"""
EnviroSat — scripts/imu.py
Reads the MPU-9250 / MPU-6500 Inertial Measurement Unit.

The IMU sits on a Grove I2C port (GPIO 2/3) at address 0x68.
It provides:
  - 3-axis accelerometer  (m/s²)
  - 3-axis gyroscope      (degrees/second)
  - 3-axis magnetometer   (µT)  — MPU-9250 only via internal AK8963 at 0x0C
  - Computed magnetic heading (degrees, 0–360)

The reader runs as a background thread, sampling every 500 ms.
The main loop calls imu.latest() to get a non-blocking snapshot.

Note on MPU-6500:
  The MPU-6500 variant has no magnetometer (no AK8963 inside).
  If the magnetometer read fails, heading is returned as None and
  accel/gyro data continues normally. Check your module's markings.

Author:  EnviroSat Team
Licence: MIT
"""

import logging
import threading
import time
import math

log = logging.getLogger("imu")

SAMPLE_INTERVAL = 0.5   # seconds between IMU reads in the background thread

EMPTY = {
    "accel_x": None, "accel_y": None, "accel_z": None,
    "gyro_x":  None, "gyro_y":  None, "gyro_z":  None,
    "mag_x":   None, "mag_y":   None, "mag_z":   None,
    "heading":  None,
    "temp_c":   None,
}


class IMUReader:
    """
    Background IMU reader for the MPU-9250 / MPU-6500.

    Usage:
        imu = IMUReader()
        t = threading.Thread(target=imu.run, args=(shutdown_event,), daemon=True)
        t.start()
        ...
        data = imu.latest()   # non-blocking snapshot
    """

    def __init__(self, address: int = 0x68):
        self._address = address
        self._lock    = threading.Lock()
        self._data    = dict(EMPTY)
        self._mpu     = None
        self._has_mag = False
        self._initialise()

    def _initialise(self):
        try:
            from mpu9250_jmdev.registers import AK8963_ADDRESS
            from mpu9250_jmdev.mpu_9250  import MPU9250

            self._mpu = MPU9250(
                address_ak=AK8963_ADDRESS,
                address_mpu_master=self._address,
                address_mpu_slave=None,
                bus=1,
                gfs=0,   # ±250 °/s
                afs=0,   # ±2 g
                mfs=14,  # 16-bit magnetometer
                mode=1,  # continuous measurement
            )
            self._mpu.configure()
            self._has_mag = True
            log.info(f"MPU-9250 initialised at I2C 0x{self._address:02X} (magnetometer enabled).")
        except ImportError:
            log.error("mpu9250-jmdev library not found — run: pip3 install mpu9250-jmdev")
        except Exception as exc:
            # Try without magnetometer (MPU-6500)
            log.warning(f"MPU-9250 full init failed ({exc}) — retrying as MPU-6500 (no mag).")
            try:
                import smbus2
                self._bus     = smbus2.SMBus(1)
                self._has_mag = False
                self._mpu     = None
                self._smbus   = True
                self._wake_mpu6500()
                log.info("MPU-6500 initialised over smbus2 (no magnetometer).")
            except Exception as exc2:
                log.error(f"IMU initialisation failed: {exc2}")

    def _wake_mpu6500(self):
        """Wake the MPU-6500 from sleep mode (it boots in sleep by default)."""
        # Register 107 (PWR_MGMT_1) — write 0x00 to wake
        self._bus.write_byte_data(self._address, 107, 0x00)
        time.sleep(0.1)

    def _read_mpu6500_raw(self) -> dict:
        """Read accel and gyro via raw smbus2 (MPU-6500 fallback path)."""
        def read_word_signed(reg):
            high = self._bus.read_byte_data(self._address, reg)
            low  = self._bus.read_byte_data(self._address, reg + 1)
            val  = (high << 8) | low
            return val - 65536 if val > 32767 else val

        ACCEL_SCALE = 16384.0   # ±2 g range → LSB/g
        GYRO_SCALE  = 131.0     # ±250 °/s range → LSB/(°/s)

        ax = read_word_signed(0x3B) / ACCEL_SCALE
        ay = read_word_signed(0x3D) / ACCEL_SCALE
        az = read_word_signed(0x3F) / ACCEL_SCALE
        gx = read_word_signed(0x43) / GYRO_SCALE
        gy = read_word_signed(0x45) / GYRO_SCALE
        gz = read_word_signed(0x47) / GYRO_SCALE
        # Raw temperature
        raw_t = read_word_signed(0x41)
        temp  = (raw_t / 340.0) + 36.53

        return {
            "accel_x": round(ax, 4), "accel_y": round(ay, 4), "accel_z": round(az, 4),
            "gyro_x":  round(gx, 4), "gyro_y":  round(gy, 4), "gyro_z":  round(gz, 4),
            "mag_x":   None,         "mag_y":   None,          "mag_z":   None,
            "heading":  None,
            "temp_c":   round(temp, 2),
        }

    @staticmethod
    def _compute_heading(mag_x: float, mag_y: float) -> float:
        """Compute magnetic heading in degrees from magnetometer X/Y."""
        heading = math.degrees(math.atan2(mag_y, mag_x))
        return round((heading + 360) % 360, 1)

    def run(self, shutdown_event: threading.Event):
        """Sample the IMU at SAMPLE_INTERVAL and cache the result."""
        log.info("IMU reader loop starting.")
        while not shutdown_event.is_set():
            try:
                if self._mpu is not None:
                    # Full MPU-9250 path via mpu9250-jmdev
                    a = self._mpu.readAccelerometerMaster()
                    g = self._mpu.readGyroscopeMaster()
                    m = self._mpu.readMagnetometerMaster() if self._has_mag else [None, None, None]
                    heading = self._compute_heading(m[0], m[1]) if (m[0] is not None) else None
                    snap = {
                        "accel_x": round(a[0], 4), "accel_y": round(a[1], 4), "accel_z": round(a[2], 4),
                        "gyro_x":  round(g[0], 4), "gyro_y":  round(g[1], 4), "gyro_z":  round(g[2], 4),
                        "mag_x":   round(m[0], 2) if m[0] is not None else None,
                        "mag_y":   round(m[1], 2) if m[1] is not None else None,
                        "mag_z":   round(m[2], 2) if m[2] is not None else None,
                        "heading": heading,
                        "temp_c":  None,
                    }
                elif hasattr(self, "_smbus"):
                    # MPU-6500 smbus2 fallback
                    snap = self._read_mpu6500_raw()
                else:
                    snap = dict(EMPTY)

                with self._lock:
                    self._data = snap

            except Exception as exc:
                log.warning(f"IMU read error: {exc}")

            shutdown_event.wait(SAMPLE_INTERVAL)

        log.info("IMU reader loop stopped.")

    def latest(self) -> dict:
        """Return a snapshot of the most recent IMU reading (thread-safe)."""
        with self._lock:
            return dict(self._data)
