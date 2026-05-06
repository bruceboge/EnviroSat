#!/usr/bin/env python3
"""
EnviroSat — ground_station/ground_station.py
Ground station receiver, terminal display, CSV logger, and command uplink.

Run this on the ground station laptop or Pi.
Requires an NRF24L01+ module connected via SPI (same wiring as the
satellite side), configured to receive on the same channel.

What it does:
  - Listens for NRF24L01 packets from the EnviroSat satellite
  - Displays incoming readings live in the terminal
  - Logs all received records to a timestamped CSV file
  - Accepts single-key command input to send commands back

Commands (press the key, then Enter):
  p — Ping      (code 01)
  f — Fast mode (code 02) — read every 10 seconds
  s — Slow mode (code 03) — return to 60-second interval
  c — Capture   (code 04) — trigger a camera capture
  x — Camera B  (code 05) — switch to Camera B
  q — Quit ground station

Author:  EnviroSat Team
Licence: MIT
"""

import csv
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ground_station")

# Import the HaLow receiver
try:
    from halow_rx import HALowReceiver
    HALOW_AVAILABLE = True
except ImportError:
    log.warning("halow_rx.py not found — HaLow reception disabled.")
    HALOW_AVAILABLE = False

# ── NRF24L01 configuration — must match satellite ────────────────────
CE_PIN    = 24
CSN_PIN   = 8
CHANNEL   = 76
TX_ADDRESS = b'\xE7\xE7\xE7\xE7\xE7'

# ── Output ───────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.expanduser("~/envirosat_ground_station")

# ── Command codes ─────────────────────────────────────────────────────
COMMANDS = {
    "p": (b'\x01', "Ping"),
    "f": (b'\x02', "Fast mode (10s)"),
    "s": (b'\x03', "Slow mode (60s)"),
    "c": (b'\x04', "Capture image"),
    "x": (b'\x05', "Switch camera"),
    "6": (b'\x06', "Safe shutdown"),
    "7": (b'\x07', "Status report"),
}

shutdown_event = threading.Event()

# ── Shared state (NRF + HaLow threads both update this) ───────────────
_state_lock    = threading.Lock()
display_lock   = threading.Lock()   # Prevents garbled terminal output


# ── NRF24 receiver ────────────────────────────────────────────────────

class NRFReceiver:
    def __init__(self):
        self._radio = None
        self._initialise()

    def _initialise(self):
        try:
            from pyrf24 import RF24, RF24_PA_MIN, RF24_2MBPS
            radio = RF24(CE_PIN, CSN_PIN)
            if not radio.begin():
                raise RuntimeError("NRF24L01 did not respond.")
            radio.setChannel(CHANNEL)
            radio.setDataRate(RF24_2MBPS)
            radio.setPALevel(RF24_PA_MIN)
            radio.openReadingPipe(1, TX_ADDRESS)
            radio.startListening()
            self._radio = radio
            log.info(f"NRF24L01 receiver ready — channel {CHANNEL}.")
        except Exception as exc:
            log.error(f"NRF24L01 init failed: {exc}")

    def available(self) -> bool:
        return self._radio is not None and self._radio.available()

    def read(self) -> bytes:
        return self._radio.read(32) if self._radio else b""

    def send_command(self, code: bytes) -> bool:
        if self._radio is None:
            return False
        self._radio.stopListening()
        success = self._radio.write(code)
        self._radio.startListening()
        return success


# ── CSV logger ────────────────────────────────────────────────────────

class CSVLogger:
    FIELDS = [
        "received_at", "satellite_id", "timestamp",
        "temperature_c", "pressure_hpa", "humidity_pct",
        "lux", "pm2_5", "pm10",
        "lat", "lon", "altitude_m", "gps_fix",
        "accel_x", "accel_y", "accel_z",
        "heading_deg", "battery_v", "flags",
    ]

    def __init__(self, output_dir: str):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        ts       = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        filepath = os.path.join(output_dir, f"ground_station_{ts}.csv")
        self._file   = open(filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDS, extrasaction="ignore")
        self._writer.writeheader()
        self._file.flush()
        log.info(f"CSV log: {filepath}")

    def write(self, record: dict):
        record["received_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._writer.writerow({k: record.get(k, "") for k in self.FIELDS})
        self._file.flush()

    def close(self):
        self._file.close()


# ── Terminal display ──────────────────────────────────────────────────

ANSI_CLEAR  = "\033[2J\033[H"
ANSI_GREEN  = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_CYAN   = "\033[36m"
ANSI_RED    = "\033[31m"
ANSI_RESET  = "\033[0m"
ANSI_BOLD   = "\033[1m"


def display(record: dict, packet_count: int, halow_count: int = 0):
    """Render a full-screen terminal dashboard."""
    ts_local = datetime.now().strftime("%H:%M:%S")
    gps_ok   = "✓ FIX" if record.get("gps_fix") else "✗ NO FIX"
    batt     = record.get("battery_v")
    batt_str = f"{batt:.2f}V" if batt else "—"

    with display_lock:
        print(ANSI_CLEAR, end="")
        print(f"{ANSI_BOLD}{ANSI_CYAN}╔══════════════════════════════════════════════╗{ANSI_RESET}")
        print(f"{ANSI_BOLD}{ANSI_CYAN}║  EnviroSat Ground Station   {ts_local}       ║{ANSI_RESET}")
        print(f"{ANSI_BOLD}{ANSI_CYAN}╚══════════════════════════════════════════════╝{ANSI_RESET}")
        print()
        print(f"  Satellite ID : {ANSI_BOLD}{record.get('satellite_id', '—')}{ANSI_RESET}")
        print(f"  NRF packets  : {ANSI_GREEN}{packet_count}{ANSI_RESET}   "
              f"HaLow packets : {ANSI_GREEN}{halow_count}{ANSI_RESET}")
        print(f"  Timestamp    : {record.get('timestamp', '—')}")
        print(f"  Battery      : {ANSI_YELLOW}{batt_str}{ANSI_RESET}    "
              f"GPS : {ANSI_GREEN if record.get('gps_fix') else ANSI_RED}{gps_ok}{ANSI_RESET}")
        print()
        print(f"  {ANSI_BOLD}── ENVIRONMENT ─────────────────────────────────{ANSI_RESET}")
        print(f"  Temperature  : {record.get('temperature_c', '—')} °C")
        print(f"  Pressure     : {record.get('pressure_hpa', '—')} hPa")
        print(f"  Humidity     : {record.get('humidity_pct', '—')} %")
        print(f"  Light        : {record.get('lux', '—')} lux")
        print(f"  PM2.5        : {record.get('pm2_5', '—')} µg/m³    "
              f"PM10 : {record.get('pm10', '—')} µg/m³")
        print()
        print(f"  {ANSI_BOLD}── POSITION ─────────────────────────────────────{ANSI_RESET}")
        lat = record.get("lat");  lon = record.get("lon")
        print(f"  Lat / Lon    : {lat if lat else '—'} / {lon if lon else '—'}")
        print(f"  Altitude     : {record.get('altitude_m', '—')} m")
        print()
        print(f"  {ANSI_BOLD}── ATTITUDE ─────────────────────────────────────{ANSI_RESET}")
        print(f"  Heading      : {record.get('heading_deg', '—')} °")
        print(f"  Accel X/Y/Z  : {record.get('accel_x', '—')} / {record.get('accel_y', '—')} / {record.get('accel_z', '—')}")
        print()
        print(f"  {ANSI_BOLD}── COMMANDS ─────────────────────────────────────{ANSI_RESET}")
        for key, (code, label) in COMMANDS.items():
            print(f"  [{key}] {label}")
        print(f"  [q] Quit")
        print()


# ── Command input thread ──────────────────────────────────────────────

def command_loop(receiver: NRFReceiver, shutdown_event: threading.Event):
    while not shutdown_event.is_set():
        try:
            key = input("Command > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            shutdown_event.set()
            break
        if key == "q":
            shutdown_event.set()
            break
        if key in COMMANDS:
            code, label = COMMANDS[key]
            ok = receiver.send_command(code)
            status = "sent" if ok else "FAILED"
            log.info(f"Command '{label}' {status}.")
        else:
            print(f"  Unknown command '{key}'. Try: {', '.join(COMMANDS.keys())}, q")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    log.info("EnviroSat Ground Station starting (NRF24 + HaLow dual receiver).")
    receiver = NRFReceiver()
    csv_log  = CSVLogger(OUTPUT_DIR)

    # ── Shared display state ─────────────────────────────────────────
    packet_count      = [0]     # NRF packet counter (list for mutability in closure)
    halow_count       = [0]     # HaLow packet counter
    last_record       = [{}]    # Shared last record (updated by both receivers)

    def on_halow_record(record, count, source="HaLow"):
        """Callback invoked by the HaLow receiver thread for each record."""
        with _state_lock:
            last_record[0] = record
            halow_count[0] = count
        csv_log.write(record)
        display(record, packet_count[0], halow_count[0])

    # ── Start HaLow receive thread ─────────────────────────────────────
    halow_receiver = None
    if HALOW_AVAILABLE:
        halow_receiver = HALowReceiver(
            csv_logger=None,          # csv_log.write() called in on_halow_record
            callback=on_halow_record,
        )
        halow_thread = threading.Thread(
            target=halow_receiver.run,
            args=(shutdown_event,),
            daemon=True,
        )
        halow_thread.start()
        log.info("HaLow receive thread started.")
    else:
        log.info("HaLow receive thread NOT started (halow_rx not available).")

    # ── Start NRF command input thread ───────────────────────────────
    cmd_thread = threading.Thread(
        target=command_loop, args=(receiver, shutdown_event), daemon=True
    )
    cmd_thread.start()

    log.info("Listening for packets … (press q + Enter to quit)")

    # ── NRF receive loop (main thread) ───────────────────────────────
    while not shutdown_event.is_set():
        if receiver.available():
            raw = receiver.read()
            try:
                text   = raw.decode("utf-8").rstrip("\x00")
                record = json.loads(text)
                packet_count[0] += 1

                # Normalise compact field names back to full names
                if "id"  in record: record["satellite_id"] = record.pop("id")
                if "ts"  in record:
                    ts_raw = record.pop("ts")
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    record.setdefault("timestamp", f"{today}T{ts_raw[:2]}:{ts_raw[2:4]}:{ts_raw[4:6]}Z")

                record["link"] = "nrf"
                with _state_lock:
                    last_record[0] = record

                csv_log.write(record)
                display(record, packet_count[0], halow_count[0])

            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                log.warning(f"Bad NRF packet: {exc}  raw={raw!r}")
        else:
            time.sleep(0.05)    # 50 ms poll

    csv_log.close()
    if halow_receiver:
        halow_receiver.close()
    log.info(f"Ground station stopped. NRF={packet_count[0]} HaLow={halow_count[0]} packets.")


if __name__ == "__main__":
    main()
