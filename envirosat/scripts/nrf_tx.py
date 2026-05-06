#!/usr/bin/env python3
"""
EnviroSat — scripts/nrf_tx.py
NRF24L01+ short-range 2.4 GHz transmitter.

The NRF24L01+ connects via SPI. It MUST be used with its dedicated
adapter module — powering it directly from the Pi's 3.3V GPIO rail
causes dropped packets and erratic behaviour. The adapter provides
a filtered, stable 3.3V supply.

GPIO pin assignments (post conflict-resolution):
  CE   → GPIO 17  (Pin 11) — but see note below
  CSN  → GPIO 8   (Pin 24) — SPI CE0
  SCK  → GPIO 11  (Pin 23)
  MOSI → GPIO 10  (Pin 19)
  MISO → GPIO 9   (Pin 21)
  IRQ  → GPIO 25  (Pin 22) — optional

  NOTE: GPIO 17 conflicts with the UPS HAT power-fail signal.
  CE has been remapped to GPIO 24 per the conflict resolution in
  Section 3.7. Update the CE pin below if your wiring differs.

The transmitter sends compact JSON-encoded payloads. NRF24L01 has a
maximum payload size of 32 bytes. Larger records are sent in chunks.

Author:  EnviroSat Team
Licence: MIT
"""

import logging
import json
import time

log = logging.getLogger("nrf_tx")

# ── NRF24L01 configuration ──────────────────────────────────────────────────
from config import (
    NRF_CE_PIN  as CE_PIN,
    NRF_CSN_PIN as CSN_PIN,
    NRF_CHANNEL as CHANNEL,
    NRF_DATA_RATE as DATA_RATE,
    NRF_PA_LEVEL  as PA_LEVEL,
    NRF_ADDRESS   as TX_ADDRESS,
)
MAX_PAYLOAD = 32                         # NRF24L01 hardware limit

# ── Compact packet fields ────────────────────────────────────────────
# A compact packet contains only the key real-time fields so it fits
# within the 32-byte limit. Full records are sent via HaLow when available.
COMPACT_FIELDS = [
    "satellite_id", "timestamp", "temperature_c", "pressure_hpa",
    "humidity_pct", "pm2_5", "lat", "lon", "battery_v", "flags",
]


class NRFTransmitter:
    """
    Transmit data records to the NRF24L01 ground station receiver.

    Usage:
        nrf = NRFTransmitter()
        nrf.transmit(record_dict)
        nrf.close()
    """

    def __init__(self):
        self._radio = None
        self._initialise()

    def _initialise(self):
        try:
            from pyrf24 import RF24, RF24_PA_MIN, RF24_PA_LOW, RF24_PA_HIGH, RF24_PA_MAX
            from pyrf24 import RF24_2MBPS, RF24_1MBPS, RF24_250KBPS

            pa_map = {
                0: RF24_PA_MIN, 1: RF24_PA_LOW,
                2: RF24_PA_HIGH, 3: RF24_PA_MAX,
            }
            dr_map = {
                2: RF24_2MBPS, 1: RF24_1MBPS, 0: RF24_250KBPS,
            }

            radio = RF24(CE_PIN, CSN_PIN)
            if not radio.begin():
                raise RuntimeError("NRF24L01 did not respond — check wiring and adapter module.")

            radio.setChannel(CHANNEL)
            radio.setDataRate(dr_map.get(DATA_RATE, RF24_2MBPS))
            radio.setPALevel(pa_map.get(PA_LEVEL, RF24_PA_MIN))
            radio.openWritingPipe(TX_ADDRESS)
            radio.stopListening()

            self._radio = radio
            log.info(f"NRF24L01 initialised — channel {CHANNEL}, CE GPIO {CE_PIN}.")
        except ImportError:
            log.error("pyrf24 not installed — run: pip3 install pyrf24")
        except Exception as exc:
            log.error(f"NRF24L01 initialisation failed: {exc}")
            log.warning("NRF24 transmissions will be skipped.")

    def _compact(self, record: dict) -> bytes:
        """
        Serialise a compact subset of the record as UTF-8 JSON.
        Truncates to MAX_PAYLOAD bytes if needed.
        """
        subset = {k: record.get(k) for k in COMPACT_FIELDS}
        # Shorten timestamp to save bytes: "2026-03-05T14:32:01Z" → "143201"
        ts = subset.get("timestamp", "")
        if ts and "T" in ts:
            subset["ts"] = ts[11:19].replace(":", "")
            del subset["timestamp"]
        # Shorten satellite ID
        subset["id"] = subset.pop("satellite_id", "ES")

        payload = json.dumps(subset, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_PAYLOAD:
            # Drop optional fields until it fits
            for drop in ("pressure_hpa", "humidity_pct", "lat", "lon"):
                subset.pop(drop, None)
                payload = json.dumps(subset, separators=(",", ":")).encode("utf-8")
                if len(payload) <= MAX_PAYLOAD:
                    break
        return payload[:MAX_PAYLOAD]

    def transmit(self, record: dict) -> bool:
        """
        Transmit a data record. Returns True if acknowledged by receiver.

        The NRF24L01 uses auto-ACK by default — the receiver sends a
        hardware acknowledgement when it receives the packet correctly.
        """
        if self._radio is None:
            return False
        try:
            payload = self._compact(record)
            success = self._radio.write(payload)
            if success:
                log.debug(f"NRF24 TX OK ({len(payload)} bytes).")
            else:
                log.warning("NRF24 TX failed — no ACK from receiver.")
            return success
        except Exception as exc:
            log.warning(f"NRF24 transmit error: {exc}")
            return False

    def listen_for_command(self, timeout_ms: int = 500) -> bytes:
        """
        Briefly switch to RX mode and return a command byte if one arrives.

        The NRF24L01 is half-duplex. This method:
          1. Opens a reading pipe on the same address the ground station writes to
          2. Listens for up to timeout_ms milliseconds
          3. Returns the command bytes if received, or None if nothing arrives
          4. Always switches back to TX mode before returning

        Timing: called once per main-loop cycle, so ground commands are
        processed within one collection interval (default 60 s).
        """
        if self._radio is None:
            return None
        try:
            self._radio.openReadingPipe(1, TX_ADDRESS)
            self._radio.startListening()

            deadline = time.monotonic() + (timeout_ms / 1000.0)
            while time.monotonic() < deadline:
                if self._radio.available():
                    cmd = bytes(self._radio.read(1))
                    self._radio.stopListening()
                    self._radio.openWritingPipe(TX_ADDRESS)
                    log.debug(f"Command received from ground: {cmd!r}")
                    return cmd
                time.sleep(0.01)

            self._radio.stopListening()
            self._radio.openWritingPipe(TX_ADDRESS)
            return None
        except Exception as exc:
            log.warning(f"Command listener error: {exc}")
            try:
                self._radio.stopListening()
                self._radio.openWritingPipe(TX_ADDRESS)
            except Exception:
                pass
            return None

    def close(self):
        """Power down the radio."""
        if self._radio is not None:
            try:
                self._radio.powerDown()
                log.info("NRF24L01 powered down.")
            except Exception:
                pass
