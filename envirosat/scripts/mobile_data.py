#!/usr/bin/env python3
"""
EnviroSat — scripts/mobile_data.py
4G/LTE cellular connectivity monitor via mini PCIe-to-USB adapter.

The mini PCIe adapter presents the cellular modem as one or more USB serial
ports (/dev/ttyUSBx). ModemManager (mmcli) detects and controls the modem.
NetworkManager holds the connection profile and reconnects automatically.

This script runs as a background daemon thread and:
  1. Verifies the modem is detected by ModemManager
  2. Ensures the NetworkManager "envirosat-lte" connection is active
  3. Pings 8.8.8.8 every CELLULAR_CHECK_INTERVAL seconds to verify internet
  4. Reconnects automatically if connectivity drops
  5. Exposes signal strength, carrier, and IP for logging

Port-conflict note:
  HaLow modem  → /dev/ttyUSB0
  Cellular modem → typically /dev/ttyUSB1, /dev/ttyUSB2, /dev/ttyUSB3
  ModemManager identifies modems by USB VID:PID, not by port number,
  so port ordering does not matter for modem management.

Dependencies (installed by install.sh):
  modemmanager, network-manager  (system packages)
  No Python packages needed — uses subprocess to call mmcli / nmcli.

Author:  EnviroSat Team
Licence: MIT
"""

import logging
import subprocess
import threading
import time
import json

from config import (
    CELLULAR_ENABLED,
    CELLULAR_APN,
    CELLULAR_MODEM_INDEX,
    CELLULAR_IFACE,
    CELLULAR_CONN_NAME,
    CELLULAR_CHECK_INTERVAL,
    CELLULAR_PING_HOST,
)

log = logging.getLogger("mobile_data")

# ── Internal state ────────────────────────────────────────────────────
_EMPTY_STATUS = {
    "connected":    False,
    "ip_address":   None,
    "carrier":      None,
    "signal_pct":   None,
    "access_tech":  None,   # e.g. "lte", "umts", "gsm"
    "modem_state":  None,
}


class MobileDataMonitor:
    """
    Monitor and maintain 4G/LTE cellular internet on the Pi.

    Usage:
        mobile = MobileDataMonitor()
        t = threading.Thread(target=mobile.run, args=(shutdown_event,), daemon=True)
        t.start()
        ...
        status = mobile.status()   # non-blocking snapshot
    """

    def __init__(self):
        self._lock   = threading.Lock()
        self._status = dict(_EMPTY_STATUS)
        self._ready  = False

        if not CELLULAR_ENABLED:
            log.info("Cellular disabled in config — mobile_data monitor will not start.")
            return

        self._ready = self._check_dependencies()

    # ── Dependency checks ──────────────────────────────────────────────

    def _check_dependencies(self) -> bool:
        """Confirm mmcli and nmcli are installed."""
        for tool in ("mmcli", "nmcli"):
            result = subprocess.run(["which", tool], capture_output=True)
            if result.returncode != 0:
                log.error(
                    f"'{tool}' not found. Run: sudo apt install modemmanager network-manager"
                )
                return False
        log.info("mmcli and nmcli found — cellular monitor ready.")
        return True

    # ── mmcli helpers ─────────────────────────────────────────────────

    def _run(self, cmd: list, timeout: int = 10) -> tuple[int, str]:
        """Run a shell command and return (returncode, stdout)."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.warning(f"Command timed out: {' '.join(cmd)}")
            return 1, ""
        except Exception as exc:
            log.warning(f"Command error: {exc}")
            return 1, ""

    def _get_modem_info(self) -> dict:
        """
        Query mmcli for modem state, signal strength, and carrier info.
        Returns a dict of parsed values (all may be None on failure).
        """
        rc, out = self._run(
            ["sudo", "mmcli", "-m", str(CELLULAR_MODEM_INDEX), "--output-json"],
            timeout=15,
        )
        if rc != 0 or not out:
            log.debug("mmcli query failed — modem may not be ready yet.")
            return {}

        try:
            data   = json.loads(out)
            modem  = data.get("modem", {})
            status = modem.get("status", {})
            signal = modem.get("signal", {})

            state      = status.get("state", None)
            access_tech = status.get("access-technologies", [None])[0]

            # Signal quality: mmcli returns "75" meaning 75%
            sig_raw   = signal.get("current", {})
            sig_value = sig_raw.get("value", None)
            signal_pct = int(sig_value) if sig_value else None

            # Carrier name from 3GPP operator
            threegpp   = modem.get("3gpp", {})
            carrier    = threegpp.get("operator-name", None)

            return {
                "modem_state":  state,
                "access_tech":  access_tech,
                "signal_pct":   signal_pct,
                "carrier":      carrier,
            }
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.debug(f"mmcli JSON parse error: {exc}")
            return {}

    def _get_ip_address(self) -> str | None:
        """Get the IP address assigned to the cellular interface."""
        rc, out = self._run(["ip", "-4", "addr", "show", CELLULAR_IFACE])
        if rc != 0 or "inet " not in out:
            return None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1].split("/")[0]
        return None

    def _ping_ok(self) -> bool:
        """Return True if CELLULAR_PING_HOST responds to a ping."""
        rc, _ = self._run(
            ["ping", "-c", "1", "-W", "3", "-I", CELLULAR_IFACE, CELLULAR_PING_HOST],
            timeout=10,
        )
        return rc == 0

    # ── NetworkManager connection management ──────────────────────────

    def _connection_exists(self) -> bool:
        """Check if the NetworkManager profile already exists."""
        rc, out = self._run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
        return CELLULAR_CONN_NAME in out.splitlines()

    def _create_connection(self):
        """
        Create a NetworkManager mobile broadband connection profile.
        Safe to call multiple times — checks if profile already exists first.
        """
        if self._connection_exists():
            log.info(f"NM connection '{CELLULAR_CONN_NAME}' already exists.")
            return

        log.info(f"Creating NM connection '{CELLULAR_CONN_NAME}' (APN={CELLULAR_APN}) …")
        rc, out = self._run([
            "sudo", "nmcli", "connection", "add",
            "type",         "gsm",
            "ifname",       "*",
            "con-name",     CELLULAR_CONN_NAME,
            "apn",          CELLULAR_APN,
            "connection.autoconnect", "yes",
        ])
        if rc == 0:
            log.info(f"NM connection '{CELLULAR_CONN_NAME}' created.")
        else:
            log.error(f"Failed to create NM connection: {out}")

    def _activate_connection(self):
        """Bring up the cellular connection via NetworkManager."""
        log.info(f"Activating connection '{CELLULAR_CONN_NAME}' …")
        rc, out = self._run(
            ["sudo", "nmcli", "connection", "up", CELLULAR_CONN_NAME],
            timeout=30,
        )
        if rc == 0:
            log.info("Cellular connection activated.")
        else:
            log.warning(f"Connection activation failed: {out}")

    # ── Background loop ───────────────────────────────────────────────

    def run(self, shutdown_event: threading.Event):
        """
        Monitor cellular connectivity. Reconnects on failure.
        Designed to run as a daemon thread.
        """
        if not self._ready or not CELLULAR_ENABLED:
            log.info("Mobile data monitor not running (disabled or deps missing).")
            return

        log.info("Mobile data monitor starting.")

        # Ensure the NM profile exists on first run
        self._create_connection()

        # Brief initial wait for ModemManager to fully initialise the modem
        shutdown_event.wait(10)

        while not shutdown_event.is_set():
            modem_info = self._get_modem_info()
            ip         = self._get_ip_address()
            connected  = ip is not None and self._ping_ok()

            with self._lock:
                self._status.update({
                    "connected":   connected,
                    "ip_address":  ip,
                    "carrier":     modem_info.get("carrier"),
                    "signal_pct":  modem_info.get("signal_pct"),
                    "access_tech": modem_info.get("access_tech"),
                    "modem_state": modem_info.get("modem_state"),
                })

            if connected:
                log.debug(
                    f"Cellular OK — IP={ip}  "
                    f"carrier={modem_info.get('carrier','?')}  "
                    f"signal={modem_info.get('signal_pct','?')}%  "
                    f"tech={modem_info.get('access_tech','?')}"
                )
            else:
                log.warning(
                    f"Cellular not connected "
                    f"(ip={ip}, modem_state={modem_info.get('modem_state','?')}) "
                    "— attempting reconnect …"
                )
                self._activate_connection()

            shutdown_event.wait(CELLULAR_CHECK_INTERVAL)

        log.info("Mobile data monitor stopped.")

    # ── Public interface ──────────────────────────────────────────────

    def status(self) -> dict:
        """Return a thread-safe snapshot of the current cellular status."""
        with self._lock:
            return dict(self._status)

    def is_connected(self) -> bool:
        """Return True if cellular internet is currently available."""
        with self._lock:
            return self._status["connected"]
