#!/bin/bash
set -e

CURRENT_USER="${SUDO_USER:-$(whoami)}"
PROJECT_DIR="/home/$CURRENT_USER/iot_project"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="mqtt_publisher"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "=== MQTT Publisher Service Installer ==="

echo "[1/5] Creating project directory at $PROJECT_DIR..."
mkdir -p "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/certs"
chown "$CURRENT_USER:$CURRENT_USER" "$PROJECT_DIR/certs"

echo "[2/5] Copying scripts..."
cp mqtt_publisher.py "$PROJECT_DIR/"
cp m5stick_parser.py "$PROJECT_DIR/"
chown -R "$CURRENT_USER:$CURRENT_USER" "$PROJECT_DIR"

echo "[3/5] Setting up Python venv and installing dependencies..."
sudo -u "$CURRENT_USER" python3 -m venv "$VENV_DIR"
sudo -u "$CURRENT_USER" "$VENV_DIR/bin/pip" install --upgrade pip
sudo -u "$CURRENT_USER" "$VENV_DIR/bin/pip" install bleak paho-mqtt psutil

echo "[4/5] Installing systemd service..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=BLE Medicine Tag Scanner and MQTT Publisher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/python mqtt_publisher.py
Restart=on-failure
RestartSec=5

# Log to systemd journal
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "[5/5] Starting service..."
systemctl start "$SERVICE_NAME"

echo ""
echo "=== Done ==="
echo "Service status:"
systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "Useful commands:"
echo "  sudo systemctl status $SERVICE_NAME    # check status"
echo "  sudo systemctl restart $SERVICE_NAME   # restart"
echo "  sudo systemctl stop $SERVICE_NAME      # stop"
echo "  sudo journalctl -u $SERVICE_NAME -f    # follow live logs"
