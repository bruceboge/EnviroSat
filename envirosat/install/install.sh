#!/bin/bash
# ============================================================
# EnviroSat — install/install.sh
# One-command dependency installer for the Raspberry Pi 3B+
#
# Run as the envirosat user (not root):
#   bash install/install.sh
#
# What this script does:
#   1. Updates the system package list
#   2. Installs system-level packages via apt
#   3. Clones and installs the Pimoroni Enviro+ library
#   4. Installs Python libraries via pip3
#   5. Clones and builds the Morse Micro HaLow kernel driver
#   6. Creates required directories
#   7. Enables required hardware interfaces
#   8. Installs the systemd auto-start service
#
# Total time: approximately 10–20 minutes depending on
# internet speed and Pi load.
# ============================================================

set -e  # Exit immediately on any error
BOLD="\033[1m"
TEAL="\033[36m"
GREEN="\033[32m"
RED="\033[31m"
RESET="\033[0m"

info()    { echo -e "${TEAL}${BOLD}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}${BOLD}[ OK ]${RESET}  $*"; }
error()   { echo -e "${RED}${BOLD}[FAIL]${RESET}  $*"; exit 1; }

# ── Detect user ──────────────────────────────────────────────────────
ENVIROSAT_USER="${USER:-envirosat}"
HOME_DIR="/home/${ENVIROSAT_USER}"
PROJECT_DIR="${HOME_DIR}/envirosat"

info "Installing EnviroSat dependencies for user: ${ENVIROSAT_USER}"
info "Project directory: ${PROJECT_DIR}"
echo ""

# ── 1. System update ─────────────────────────────────────────────────
info "Step 1/8 — Updating system packages …"
sudo apt update -y && sudo apt upgrade -y
success "System packages up to date."

# ── 2. System-level packages ──────────────────────────────────────────
info "Step 2/8 — Installing system packages …"
sudo apt install -y \
    python3-pip \
    python3-serial \
    python3-picamera2 \
    git \
    i2c-tools \
    build-essential \
    dkms \
    linux-headers-$(uname -r)
success "System packages installed."

# ── 3. Pimoroni Enviro+ library ───────────────────────────────────────
info "Step 3/8 — Installing Pimoroni Enviro+ library …"
if [ ! -d "${HOME_DIR}/enviroplus-python" ]; then
    git clone https://github.com/pimoroni/enviroplus-python "${HOME_DIR}/enviroplus-python"
fi
cd "${HOME_DIR}/enviroplus-python"
# Install non-interactively into the pimoroni virtualenv
yes | ./install.sh 2>&1 | tail -5
success "Enviro+ library installed."

# ── 4. Python libraries via pip3 ──────────────────────────────────────
info "Step 4/8 — Installing Python libraries …"

# Activate the pimoroni virtualenv that the Enviro+ installer created
VENV="${HOME_DIR}/.virtualenvs/pimoroni/bin/pip3"
if [ ! -f "$VENV" ]; then
    # Fallback: create a fresh venv if the pimoroni one is not present
    python3 -m venv "${HOME_DIR}/.virtualenvs/pimoroni"
    VENV="${HOME_DIR}/.virtualenvs/pimoroni/bin/pip3"
fi

$VENV install --upgrade pip

PACKAGES=(
    "smbus2"            # General I2C communication
    "RPi.GPIO"          # GPIO pin control
    "pyrf24"            # NRF24L01+ radio driver
    "pynmea2"           # GPS NMEA sentence parser
    "mpu9250-jmdev"     # MPU-9250/6500 IMU driver
)

for pkg in "${PACKAGES[@]}"; do
    info "  Installing ${pkg} …"
    $VENV install "$pkg"
done
success "Python libraries installed."

# ── 5. HaLow kernel driver ────────────────────────────────────────────
info "Step 5/8 — Installing Morse Micro HaLow kernel driver …"
DRIVER_DIR="${HOME_DIR}/morse_driver"
if [ ! -d "$DRIVER_DIR" ]; then
    git clone https://github.com/MorseMicro/morse_driver.git "$DRIVER_DIR"
fi
cd "$DRIVER_DIR"
make 2>&1 | tail -5
sudo make install 2>&1 | tail -3

# Load module now
sudo modprobe morse 2>/dev/null || info "  morse module will load on next boot."

# Ensure it loads on every boot
if ! grep -q "^morse$" /etc/modules 2>/dev/null; then
    echo 'morse' | sudo tee -a /etc/modules
fi
success "HaLow driver installed."

# ── 6. Create required directories ────────────────────────────────────
info "Step 6/8 — Creating project directories …"
mkdir -p "${PROJECT_DIR}/logs"
mkdir -p "${PROJECT_DIR}/images"
mkdir -p "${PROJECT_DIR}/scripts"
mkdir -p "${HOME_DIR}/envirosat_ground_station"
success "Directories created."

# ── 7. Enable hardware interfaces ─────────────────────────────────────
info "Step 7/8 — Enabling hardware interfaces …"

# Enable I2C
sudo raspi-config nonint do_i2c 0
# Enable SPI
sudo raspi-config nonint do_spi 0
# Enable UART (disable login shell on UART, keep hardware UART active)
sudo raspi-config nonint do_serial_hw 0
sudo raspi-config nonint do_serial_cons 1
# Enable camera (CSI)
sudo raspi-config nonint do_camera 0

success "I2C, SPI, UART, and Camera interfaces enabled."

# ── 8. Install systemd service ────────────────────────────────────────
info "Step 8/8 — Installing EnviroSat systemd service …"
SERVICE_SRC="${PROJECT_DIR}/install/envirosat.service"
SERVICE_DST="/etc/systemd/system/envirosat.service"

if [ -f "$SERVICE_SRC" ]; then
    sudo cp "$SERVICE_SRC" "$SERVICE_DST"
    sudo systemctl daemon-reload
    sudo systemctl enable envirosat.service
    success "systemd service installed and enabled."
else
    info "  Service file not found at ${SERVICE_SRC} — skipping auto-start setup."
    info "  Copy install/envirosat.service to /etc/systemd/system/ manually when ready."
fi

# ── Done ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  EnviroSat installation complete!               ${RESET}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════${RESET}"
echo ""
echo "  Next steps:"
echo "  1. Reboot the Pi:  sudo reboot"
echo "  2. Verify I2C:     sudo i2cdetect -y 1"
echo "     Expected:  0x04 (Grove Hat), 0x23 (LTR-559),"
echo "                0x42 (UPS HAT), 0x68 (IMU), 0x76 (BME280)"
echo "  3. Test sensors:   cd ~/enviroplus-python/examples"
echo "                     source ~/.virtualenvs/pimoroni/bin/activate"
echo "                     python weather.py"
echo "  4. Start manually: source ~/.virtualenvs/pimoroni/bin/activate"
echo "                     cd ~/envirosat && python main.py"
echo "  5. Start on boot:  sudo systemctl start envirosat"
echo "                     sudo systemctl status envirosat"
echo ""
