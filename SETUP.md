# EnviroSat — Complete Setup Guide

> **Repository:** https://github.com/bruceboge/EnviroSat  
> **Hardware:** Raspberry Pi 3B+ · Pimoroni Enviro+ · Morse Micro HaLow · NRF24L01+  
> **OS:** Raspberry Pi OS Lite (64-bit, Bookworm)

---

## Table of Contents

1. [Bill of Materials](#1-bill-of-materials)
2. [Hardware Wiring](#2-hardware-wiring)
3. [Flash the Raspberry Pi OS](#3-flash-raspberry-pi-os)
4. [First Boot & Pi Configuration](#4-first-boot--pi-configuration)
5. [Clone the Repository](#5-clone-the-repository)
6. [Run the Installer](#6-run-the-installer)
7. [Verify Hardware](#7-verify-hardware)
8. [Test Each Subsystem](#8-test-each-subsystem)
9. [Enable Auto-Start at Boot](#9-enable-auto-start-at-boot)
10. [Ground Station Setup](#10-ground-station-setup)
11. [Run the Dashboard](#11-run-the-dashboard)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Bill of Materials

### Satellite Board

| # | Component | Notes |
|---|---|---|
| 1 | Raspberry Pi 3B+ | The compute core |
| 1 | Pimoroni Enviro+ HAT | Stacks directly on Pi GPIO header |
| 1 | Waveshare UPS HAT (C) | Stacks on top of Enviro+; INA219 at I2C 0x42 |
| 1 | Grove Base Hat for Raspberry Pi | Required for IMU I2C connection |
| 1 | MPU-9250 IMU module | Plugs into Grove I2C port |
| 1 | u-blox Neo-6M GPS module | UART connection to Pi |
| 1 | NRF24L01+ with adapter module | **Use the adapter** — do NOT power from Pi 3.3V directly |
| 1 | Arducam UC-444 dual camera adapter | CSI ribbon cable |
| 2 | Camera modules (OV5647 or IMX219) | Must be the same model |
| 1 | Morse Micro HaLow USB modem | USB-A to Pi |
| 1 | 18650 Li-ion battery (×2) | For UPS HAT |
| 1 | MicroSD card (32 GB+, Class 10) | Data logging storage |

### Ground Station

| # | Component | Notes |
|---|---|---|
| 1 | Laptop or Raspberry Pi | Runs `ground_station.py` and `dashboard.py` |
| 1 | NRF24L01+ with adapter module | Same wiring as satellite side |
| 1 | Morse Micro HaLow USB modem | USB-A, paired with satellite modem |

---

## 2. Hardware Wiring

### 2.1 NRF24L01+ Adapter → Pi GPIO

> [!IMPORTANT]
> Always use the **adapter module** between the NRF24L01+ and the Pi.
> Powering the NRF directly from GPIO 3.3V causes packet loss.

| NRF Pin | Pi GPIO | Pi Pin # |
|---|---|---|
| VCC | 5V (from adapter) | — |
| GND | GND | Pin 6 |
| CE | **GPIO 24** | Pin 18 |
| CSN | GPIO 8 (SPI CE0) | Pin 24 |
| SCK | GPIO 11 | Pin 23 |
| MOSI | GPIO 10 | Pin 19 |
| MISO | GPIO 9 | Pin 21 |
| IRQ | GPIO 25 (optional) | Pin 22 |

> [!WARNING]
> **CE is GPIO 24, NOT GPIO 17.** GPIO 17 conflicts with the UPS HAT power-fail pin.
> This is already set correctly in `config.py` — do not change it.

### 2.2 Neo-6M GPS → Pi UART

| GPS Pin | Pi Connection |
|---|---|
| VCC | 3.3V (Pin 1) |
| GND | GND (Pin 6) |
| TX | Pi RX — GPIO 15 (Pin 10) |
| RX | Pi TX — GPIO 14 (Pin 8) |

The Pi's hardware UART (`/dev/serial0`) is used at 9600 baud.

### 2.3 HAT Stack Order (bottom to top)

```
Pi 3B+ (bottom)
  └── Enviro+ HAT       (GPIO header)
        └── UPS HAT     (stacks on Enviro+ passthrough)
              └── Batteries
```

### 2.4 I2C Address Map

Run `sudo i2cdetect -y 1` after installation. Expected addresses:

| Address | Device |
|---|---|
| `0x23` | LTR-559 (light/proximity) |
| `0x42` | INA219 on UPS HAT (battery monitor) |
| `0x49` | ADS1015 (gas sensor ADC) |
| `0x68` | MPU-9250/6500 IMU |
| `0x70` | Arducam UC-444 camera mux |
| `0x76` | BME280 (temperature/pressure/humidity) |

---

## 3. Flash Raspberry Pi OS

1. Download **Raspberry Pi Imager** from https://rpi.imager.org
2. Choose **Raspberry Pi OS Lite (64-bit)** — Bookworm
3. Click the ⚙️ gear icon before flashing and set:
   - **Hostname:** `envirosat`
   - **Username:** `envirosat`  ← must match the user in `install.sh`
   - **Password:** (your choice — note it down)
   - **Enable SSH:** checked
   - **Wi-Fi:** enter your network credentials (for setup only)
4. Flash to your microSD card
5. Insert microSD into the Pi and power on

---

## 4. First Boot & Pi Configuration

SSH into the Pi from your laptop:

```bash
ssh envirosat@envirosat.local
# or use the Pi's IP address: ssh envirosat@192.168.x.x
```

### Expand the filesystem (if not done automatically)

```bash
sudo raspi-config --expand-rootfs
```

### Set the timezone

```bash
sudo timedatectl set-timezone Africa/Nairobi   # Change to your timezone
```

### Update the system

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 5. Clone the Repository

```bash
# Clone from GitHub into the home directory
git clone https://github.com/bruceboge/EnviroSat.git ~/envirosat

# Confirm the project structure
ls ~/envirosat/envirosat/
# Expected: config.py  main.py  scripts/  ground_station/  install/
```

---

## 6. Run the Installer

The installer script handles everything: system packages, Python libraries, the Pimoroni Enviro+ library, the HaLow kernel driver, directories, hardware interfaces, and the systemd service.

```bash
# Run from the project root — NOT as root, as the envirosat user
cd ~/envirosat
bash envirosat/install/install.sh
```

**What the installer does (8 steps, ~15 minutes):**

| Step | Action |
|---|---|
| 1 | `apt update && apt upgrade` |
| 2 | Installs: `python3-pip`, `python3-serial`, `python3-picamera2`, `git`, `i2c-tools`, `build-essential`, `dkms`, `linux-headers` |
| 3 | Clones and installs Pimoroni Enviro+ Python library |
| 4 | Installs Python packages: `smbus2`, `RPi.GPIO`, `pyrf24`, `pynmea2`, `mpu9250-jmdev` |
| 5 | Clones and builds Morse Micro HaLow kernel driver (`morse_driver`) |
| 6 | Creates `/images/` and `/logs/` directories |
| 7 | Enables I2C, SPI, UART, and Camera interfaces via `raspi-config` |
| 8 | Installs `envirosat.service` into systemd and enables it |

After the script completes:

```bash
sudo reboot
```

---

## 7. Verify Hardware

After reboot, SSH back in and run these checks:

### 7.1 I2C devices

```bash
sudo i2cdetect -y 1
```

You should see: `0x23`, `0x42`, `0x49`, `0x68`, `0x70`, `0x76`

### 7.2 GPS serial data

```bash
# Install screen if needed
sudo apt install -y screen

# Monitor the GPS UART — you should see NMEA sentences streaming
screen /dev/serial0 9600

# Press Ctrl+A then K to exit screen
```

Look for lines starting with `$GPRMC` and `$GPGGA`. If you see them, the GPS is wired correctly.

### 7.3 SPI (NRF24L01)

```bash
ls /dev/spidev*
# Expected: /dev/spidev0.0  /dev/spidev0.1
```

### 7.4 HaLow modem

```bash
ls /dev/ttyUSB*
# Expected: /dev/ttyUSB0
# If absent, try unplugging and replugging the USB modem
```

### 7.5 Camera

```bash
libcamera-hello --nopreview -t 2000
# Should complete without errors
```

---

## 8. Test Each Subsystem

Activate the Pimoroni virtualenv first:

```bash
source ~/.virtualenvs/pimoroni/bin/activate
cd ~/envirosat/envirosat
```

### 8.1 Sensors (Enviro+)

```bash
python - <<'EOF'
from scripts.sensors import SensorReader
s = SensorReader()
import time; time.sleep(1)
print(s.read_all())
EOF
```

Expected: dict with temperature, pressure, humidity, lux, proximity, gas, PM values.

### 8.2 GPS

```bash
python - <<'EOF'
import threading, time
from scripts.gps import GPSReader
ev = threading.Event()
g = GPSReader()
t = threading.Thread(target=g.run, args=(ev,), daemon=True)
t.start()
time.sleep(5)
print(g.latest())
ev.set()
EOF
```

Expected: dict with lat/lon/fix fields. `fix` will be `False` until the antenna has a sky view.

### 8.3 IMU

```bash
python - <<'EOF'
import threading, time
from scripts.imu import IMUReader
ev = threading.Event()
imu = IMUReader()
t = threading.Thread(target=imu.run, args=(ev,), daemon=True)
t.start()
time.sleep(2)
print(imu.latest())
ev.set()
EOF
```

Expected: accel_x/y/z, gyro_x/y/z, heading values.

### 8.4 Power Monitor (Battery)

```bash
python - <<'EOF'
import threading
from scripts.power_monitor import PowerMonitor
ev = threading.Event()
p = PowerMonitor(ev)
import time; time.sleep(1)
print(f"Voltage: {p.battery_voltage()}V")
print(f"Current: {p.battery_current_ma()}mA")
print(f"Level:   {p.battery_percent()}%")
ev.set()
EOF
```

### 8.5 Full system dry run

```bash
python main.py
```

Watch the logs. Within 60 seconds you should see `Cycle 1` complete. Check for any `[ERROR]` lines.

---

## 9. Enable Auto-Start at Boot

The installer already does this, but to verify:

```bash
sudo systemctl status envirosat
# Should show: active (running)  or  enabled (will start on next boot)

# If not enabled, run:
sudo systemctl enable --now envirosat

# View live logs:
sudo journalctl -u envirosat -f

# Stop / start manually:
sudo systemctl stop envirosat
sudo systemctl start envirosat
```

Log files are written to:
```
~/envirosat/logs/system.log         ← rotating, max 10 MB × 5 files
~/envirosat/logs/envirosat_*.jsonl  ← one JSON Lines data file per boot session
~/envirosat/images/                 ← timestamped JPEG captures
```

---

## 10. Ground Station Setup

The ground station runs on a **separate laptop or Raspberry Pi**.

### 10.1 Install ground station dependencies

```bash
# On the ground station machine (not the satellite Pi)
pip3 install pyrf24 pyserial
```

### 10.2 Wire the NRF24L01

Same wiring as the satellite side — see Section 2.1.

> [!IMPORTANT]
> The NRF **channel** and **address** must match the satellite values in `config.py`:
> - Channel: `76`
> - Address: `\xE7\xE7\xE7\xE7\xE7`

### 10.3 Connect the HaLow modem

Plug the Morse Micro HaLow USB modem into the ground station laptop.

```bash
ls /dev/ttyUSB*   # Confirm it appears as /dev/ttyUSB0
```

### 10.4 Clone the repo on the ground station

```bash
git clone https://github.com/bruceboge/EnviroSat.git ~/envirosat
cd ~/envirosat/envirosat
```

### 10.5 Run the ground station receiver

```bash
cd ~/envirosat/envirosat/ground_station
python ground_station.py
```

The terminal will display a live dashboard showing:
- **NRF packets** (compact, 10-field, short-range)
- **HaLow packets** (full, 30-field, long-range)
- Both counts update simultaneously from their respective receiver threads

**Available commands** (type the key, then Enter):

| Key | Action |
|---|---|
| `p` | Ping satellite |
| `f` | Fast mode (collect every 10 s) |
| `s` | Slow mode (back to 60 s) |
| `c` | Trigger camera capture |
| `x` | Switch to Camera B |
| `6` | Safe shutdown satellite |
| `7` | Status report in satellite log |
| `q` | Quit ground station |

### 10.6 Test HaLow link alone

```bash
cd ~/envirosat/envirosat/ground_station
python halow_rx.py
```

This receives HaLow-only packets and prints full JSON records to the terminal.

---

## 11. Run the Dashboard

In a **second terminal** on the ground station:

```bash
cd ~/envirosat/envirosat/ground_station
python dashboard.py
```

Open a browser at: **http://localhost:8080**

The page auto-refreshes every 5 seconds and displays all telemetry fields including a battery bar, GPS fix status, temperature, pressure, PM2.5, PM10, heading, and a historical data table.

---

## 12. Troubleshooting

### `ImportError: cannot import name 'GPSReader' from 'scripts.gps'`
The `scripts/gps.py` file is missing. Pull the latest code:
```bash
cd ~/envirosat && git pull
```

### `NRF24L01 did not respond — check wiring and adapter module`
- Confirm SPI is enabled: `ls /dev/spidev*`
- Confirm CE pin is wired to GPIO **24** (not 17)
- Confirm you are using the **adapter module** (brown PCB with capacitors)
- Try: `sudo raspi-config nonint do_spi 0` then reboot

### `Cannot open GPS port /dev/serial0`
- Confirm UART is enabled: `ls /dev/serial0`
- Run: `sudo raspi-config nonint do_serial_hw 0` and `sudo raspi-config nonint do_serial_cons 1` then reboot
- Confirm TX/RX wires are not swapped (GPS TX → Pi RX)

### `Cannot open HaLow port /dev/ttyUSB0`
- Unplug and replug the HaLow USB modem
- Check `dmesg | tail -20` for USB enumeration messages
- Try `sudo modprobe morse` to load the kernel driver manually
- If `ttyUSB1` or higher, update `HALOW_PORT` in `config.py`

### GPS shows `fix: False` permanently
- Move antenna outdoors with clear sky view
- Cold start can take up to 12 minutes
- Check NMEA stream: `screen /dev/serial0 9600`

### Battery voltage shows `None`
- Confirm UPS HAT I2C address: `sudo i2cdetect -y 1` — should show `0x42`
- Some Waveshare boards use `0x36` — update `UPS_HAT_ADDR` in `config.py`

### Logs filling the microSD
- Log rotation is configured: `system.log` rotates at 10 MB, keeping 5 files
- JSONL data files grow at ~1 record/minute (~5 KB/hour) — a 32 GB card will last decades

---

## Quick Reference — File Structure

```
EnviroSat/
└── envirosat/
    ├── config.py                  ← All hardware constants (edit this file)
    ├── main.py                    ← Satellite boot script (started by systemd)
    ├── requirements.txt           ← pip dependencies
    ├── scripts/
    │   ├── gps.py                 ← Neo-6M GPS reader
    │   ├── sensors.py             ← Enviro+ sensor reader
    │   ├── imu.py                 ← MPU-9250 IMU reader
    │   ├── camera.py              ← Arducam dual camera
    │   ├── nrf_tx.py              ← NRF24L01+ transmitter + command receiver
    │   ├── halow_tx.py            ← Morse Micro HaLow transmitter
    │   ├── power_monitor.py       ← INA219 battery monitor
    │   └── logger.py              ← JSON Lines data logger
    ├── ground_station/
    │   ├── ground_station.py      ← NRF + HaLow dual receiver + command uplink
    │   ├── halow_rx.py            ← HaLow receiver (also runs standalone)
    │   └── dashboard.py           ← Browser dashboard on :8080
    └── install/
        ├── install.sh             ← One-command Pi installer
        └── envirosat.service      ← systemd service file
```

---

*EnviroSat Team · https://github.com/bruceboge/EnviroSat*
