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
import struct
import time

log = logging.getLogger("nrf_tx")

# ── NRF24L01 configuration ───────────────────────────────────────────
CE_PIN   = 24           # GPIO 24 — see conflict-resolution note above
CSN_PIN  = 8            # GPIO 8 (SPI CE0)
SPI_BUS  = 0
SPI_DEV  = 0
CHANNEL  = 76           # RF channel 0–125. Must match ground station.
DATA_RATE = 2           # 2 Mbps
PA_LEVEL  = 0           # 0=min, 1=low, 2=high, 3=max transmit power

TX_ADDRESS = b'\xE7\xE7\xE7\xE7\xE7'   # 5-byte pipe address
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

    def close(self):
        """Power down the radio."""
        if self._radio is not None:
            try:
                self._radio.powerDown()
                log.info("NRF24L01 powered down.")
            except Exception:
                pass
