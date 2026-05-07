# EnviroSat 🛰️

**Environmental nano-satellite platform** built on a Raspberry Pi 3B+ with Pimoroni Enviro+ sensors, dual radio telemetry (NRF24L01+ short-range + WiFi HaLow long-range), dual camera, IMU attitude sensing, and a live browser dashboard.

## Features

- 🌡️ **Environmental sensing** — Temperature, pressure, humidity, light, CO/NO2/NH3 gas, PM1/PM2.5/PM10 particulates
- 📡 **Dual radio telemetry** — NRF24L01+ (compact, 100m) + Morse Micro HaLow (full record, 1 km+)
- 📶 **4G/LTE mobile internet** — Mini PCIe-to-USB cellular modem with SIM card; ModemManager + NetworkManager auto-connect; signal/carrier/IP logged every cycle
- 📍 **GPS positioning** — u-blox Neo-6M NMEA reader with background thread
- 🔄 **Attitude sensing** — MPU-9250 3-axis accel/gyro/magnetometer
- 📷 **Dual camera** — Arducam UC-444 with automatic 5-minute captures
- 🔋 **Power management** — INA219 battery monitoring with safe auto-shutdown
- 📊 **Live dashboard** — Browser UI at http://localhost:8080
- ⌨️ **Command uplink** — Ground station can send 7 commands to the satellite over NRF
- 🔁 **Auto-start** — systemd service starts on every boot

## Quick Start

```bash
# On a fresh Raspberry Pi OS Lite — one command installs everything:
curl -sSL https://raw.githubusercontent.com/bruceboge/EnviroSat/main/envirosat/install/install.sh | bash
```

Or clone first:

```bash
git clone https://github.com/bruceboge/EnviroSat.git ~/envirosat
bash ~/envirosat/envirosat/install/install.sh
```

## Full Setup Guide

See **[SETUP.md](./SETUP.md)** for:
- Complete bill of materials
- Hardware wiring diagrams (GPIO pin assignments)
- Step-by-step OS and software setup
- Per-subsystem test commands
- Ground station setup (NRF + HaLow simultaneous reception)
- Troubleshooting guide

## Repository Structure

```
EnviroSat/
├── SETUP.md                       ← Full setup guide (start here)
└── envirosat/
    ├── config.py                  ← All hardware constants (edit to match your wiring)
    ├── main.py                    ← Satellite master script
    ├── requirements.txt
    ├── scripts/
    │   ├── gps.py                 GPS reader (Neo-6M, NMEA)
    │   ├── sensors.py             Enviro+ HAT sensors
    │   ├── imu.py                 MPU-9250 IMU
    │   ├── camera.py              Arducam UC-444 dual camera
    │   ├── nrf_tx.py              NRF24L01+ transmitter + command receiver
    │   ├── halow_tx.py            Morse Micro HaLow transmitter
    │   ├── power_monitor.py       INA219 battery monitor
    │   └── logger.py              JSON Lines data logger
    ├── ground_station/
    │   ├── ground_station.py      NRF + HaLow dual receiver + command uplink
    │   ├── halow_rx.py            HaLow-only receiver (also standalone)
    │   └── dashboard.py           HTTP dashboard on port 8080
    └── install/
        ├── install.sh             One-command Pi installer (clones repo + installs all deps)
        └── envirosat.service      systemd service
```

## Hardware

| Component | Purpose |
|---|---|
| Raspberry Pi 3B+ | Compute core |
| Pimoroni Enviro+ HAT | Environmental sensors |
| Waveshare UPS HAT | Battery + INA219 power monitor |
| u-blox Neo-6M | GPS positioning |
| NRF24L01+ (+ adapter) | Short-range 2.4 GHz telemetry |
| Morse Micro HaLow modem | Long-range 900 MHz WiFi telemetry |
| Mini PCIe-to-USB adapter + 4G modem | Mobile internet via SIM card |
| MPU-9250 IMU | Attitude (accel/gyro/mag) |
| Arducam UC-444 | Dual camera multiplexer |

## Licence

MIT — EnviroSat Team
