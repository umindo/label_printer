#!/usr/bin/env bash
# setup.sh — One-command setup for TSC TDP-225 Print Agent on Raspberry Pi
# Run once as your normal user (not root):  bash setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="print-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
DEVICE="/dev/usb/lp0"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   TSC TDP-225 Print Agent — Setup Script         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Install Python dependencies ───────────────────────────
echo "[1/5] Setting up virtual environment and installing dependencies..."
if ! python3 -c "import venv" 2>/dev/null; then
    echo "      ❌ python3-venv is not installed on this Raspberry Pi."
    echo "         Please run the following command first to install it:"
    echo "         sudo apt update && sudo apt install python3-venv -y"
    exit 1
fi

if [ ! -d "${SCRIPT_DIR}/env" ]; then
    python3 -m venv "${SCRIPT_DIR}/env"
fi

"${SCRIPT_DIR}/env/bin/pip" install --quiet --upgrade pip
"${SCRIPT_DIR}/env/bin/pip" install --quiet -r "${SCRIPT_DIR}/requirements.txt"
"${SCRIPT_DIR}/env/bin/pip" install --quiet Pillow "qrcode[pil]"
echo "      ✅ Virtual environment set up with Flask, Pillow, and qrcode"

# Ensure DejaVu fonts are installed (used for bitmap label rendering)
if ! fc-list | grep -qi "DejaVu"; then
    echo "      Installing DejaVu fonts..."
    sudo apt-get install -y fonts-dejavu-core > /dev/null 2>&1
fi
echo "      ✅ DejaVu Sans fonts available"

# ── 2. USB printer permissions ────────────────────────────────
echo "[2/5] Setting USB printer permissions..."

# Add user to lp group (takes effect on next login)
sudo usermod -aG lp "$USER"

# udev rule — TSC USB vendor ID is 0x0519
UDEV_RULE='SUBSYSTEM=="usb", ATTRS{idVendor}=="0519", MODE="0666", GROUP="lp"'
echo "$UDEV_RULE" | sudo tee /etc/udev/rules.d/99-tsc-printer.rules > /dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "      ✅ udev rule created"

# Immediate fix if device already exists
if [ -e "$DEVICE" ]; then
    sudo chmod 666 "$DEVICE"
    echo "      ✅ Permissions set on $DEVICE"
fi

# ── 3. Generate a random API key ──────────────────────────────
echo "[3/5] Generating API key..."
GENERATED_KEY=$("${SCRIPT_DIR}/env/bin/python" -c "import secrets; print(secrets.token_hex(24))")
echo ""
echo "  ⚠️  IMPORTANT: Copy this API key — you will enter it in"
echo "      ERPNext → Label Printer Settings → API Key"
echo ""
echo "  API KEY: $GENERATED_KEY"
echo ""
read -r -p "  Press ENTER after copying the key..."

# ── 4. Create systemd service ─────────────────────────────────
echo "[4/5] Creating systemd service..."

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=TSC TDP-225 Print Agent (Label Printer)
After=network.target

[Service]
ExecStart=${SCRIPT_DIR}/env/bin/python3 ${SCRIPT_DIR}/app.py
WorkingDirectory=${SCRIPT_DIR}
Restart=always
RestartSec=5
User=${USER}

# ── Configuration ──
Environment=PRINT_AGENT_KEY=${GENERATED_KEY}
Environment=PRINTER_DEVICE=/dev/usb/lp0
Environment=PORT=5000

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
echo "      ✅ Service enabled and started"

# ── 5. Verify ────────────────────────────────────────────────
echo "[5/5] Verifying..."
sleep 2

if sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
    PI_IP=$(hostname -I | awk '{print $1}')
    echo "      ✅ Print agent is running!"
    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║   Setup Complete! 🎉                             ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo ""
    echo "  Agent URL : http://${PI_IP}:5000"
    echo "  Health    : curl http://${PI_IP}:5000/health"
    echo ""
    echo "  Now configure ERPNext:"
    echo "    Settings → Label Printer Settings"
    echo "      Print Agent IP : ${PI_IP}"
    echo "      Port           : 5000"
    echo "      API Key        : (the key above)"
    echo ""
else
    echo "      ❌ Service failed to start. Check logs:"
    echo "         sudo journalctl -u ${SERVICE_NAME} -n 30"
fi
