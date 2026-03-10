#!/usr/bin/env python3
"""
EnviroSat — scripts/camera.py
Dual camera capture and switching via the Arducam UC-444 adapter.

The Arducam UC-444 connects to the Pi's CSI port via a 22-pin FFC
ribbon cable and is controlled over I2C (address 0x70).

It physically switches between Camera A and Camera B by toggling a
multiplexer — only one camera can be active at a time.

Camera models supported: OV5647 (5MP) and IMX219 (8MP).
Both cameras must be the same model — do not mix types.

GPIO 4 (Pin 7) is used as the camera select signal.

Author:  EnviroSat Team
Licence: MIT
"""

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("camera")

# ── Arducam I2C multiplexer ──────────────────────────────────────────
ARDUCAM_I2C_ADDR = 0x70
CAMERA_A         = 0        # Arducam channel index for Camera A
CAMERA_B         = 1        # Arducam channel index for Camera B

# ── Image settings ───────────────────────────────────────────────────
STILL_RESOLUTION = (2592, 1944)     # OV5647 full resolution
JPEG_QUALITY     = 85               # 0–100


class CameraController:
    """
    Select, capture, and switch between Camera A and Camera B.

    Usage:
        cam = CameraController()
        filename = cam.capture("/path/to/images")       # auto camera
        filename = cam.capture("/path/to/images", cam=1)  # force Camera B
        cam.switch_camera()                              # toggle active camera
    """

    def __init__(self):
        self._active_camera = CAMERA_A
        self._i2c_bus       = None
        self._picam2        = None
        self._initialise()

    def _initialise(self):
        try:
            import smbus2
            from picamera2 import Picamera2
            from libcamera import controls

            self._smbus2   = smbus2
            self._Picamera2 = Picamera2
            self._controls  = controls
            self._i2c_bus   = smbus2.SMBus(1)

            # Select Camera A at startup
            self._select_camera(CAMERA_A)
            log.info("Arducam UC-444 initialised. Camera A active.")
        except ImportError as exc:
            log.error(f"Camera library not available: {exc}")
            log.warning("Camera captures will be skipped.")
        except Exception as exc:
            log.error(f"Camera initialisation failed: {exc}")

    def _select_camera(self, channel: int):
        """
        Write to the Arducam I2C multiplexer to select a camera channel.
        channel: 0 = Camera A, 1 = Camera B
        """
        if self._i2c_bus is None:
            return
        try:
            # Arducam UC-444 register map: write channel index to register 0
            self._i2c_bus.write_byte_data(ARDUCAM_I2C_ADDR, 0x00, channel)
            time.sleep(0.1)     # Allow multiplexer to settle
        except Exception as exc:
            log.warning(f"Camera select failed (channel {channel}): {exc}")

    def switch_camera(self):
        """Toggle the active camera between A and B."""
        new_cam = CAMERA_B if self._active_camera == CAMERA_A else CAMERA_A
        self._select_camera(new_cam)
        self._active_camera = new_cam
        label = "A" if new_cam == CAMERA_A else "B"
        log.info(f"Switched to Camera {label}.")
        return new_cam

    def capture(self, output_dir: str, cam: int = None) -> str:
        """
        Capture a still image and save it as a timestamped JPEG.

        Args:
            output_dir: Directory path where the image will be saved.
            cam:        Camera channel to use (0=A, 1=B). Defaults to
                        the currently active camera.

        Returns:
            Full path of the saved image file.

        Raises:
            RuntimeError if camera libraries are not available.
        """
        if self._Picamera2 is None:
            raise RuntimeError("Camera library not available — install python3-picamera2")

        # Switch camera if a specific one is requested
        if cam is not None and cam != self._active_camera:
            self._select_camera(cam)
            self._active_camera = cam

        cam_label = "A" if self._active_camera == CAMERA_A else "B"

        # Build filename: envirosat_camA_2026-03-05T143201Z.jpg
        ts       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        filename = f"envirosat_cam{cam_label}_{ts}.jpg"
        filepath = os.path.join(output_dir, filename)

        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Capture
        picam2 = self._Picamera2()
        try:
            config = picam2.create_still_configuration(
                main={"size": STILL_RESOLUTION},
                lores={"size": (640, 480)},
                display="lores",
            )
            picam2.configure(config)
            picam2.start()
            time.sleep(2)   # Allow auto-exposure to settle
            picam2.capture_file(filepath)
            log.info(f"Captured: {filepath} (camera {cam_label})")
        finally:
            picam2.stop()
            picam2.close()

        return filepath

    @property
    def active_camera(self) -> str:
        """Return 'A' or 'B' for the currently active camera."""
        return "A" if self._active_camera == CAMERA_A else "B"
