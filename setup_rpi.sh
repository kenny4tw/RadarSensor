#!/usr/bin/env bash
# Setup script for Raspberry Pi radar sensor daemon
# Run with: sudo bash setup_rpi.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${SUDO_USER:-${USER:-}}"
SERVICE_NAME="radar-daemon"
SERVICE_DIR="/etc/systemd/system"
SERVICE_FILE="$SERVICE_DIR/${SERVICE_NAME}.service"
LOG_DIR="/var/log/radar_daemon"

if [[ -z "$SERVICE_USER" ]] && id pi >/dev/null 2>&1; then
	SERVICE_USER="pi"
fi

if [[ -z "$SERVICE_USER" ]] || ! id "$SERVICE_USER" >/dev/null 2>&1; then
	echo "Unable to determine a valid service user. Run with: sudo bash setup_rpi.sh" >&2
	exit 1
fi

echo "Setting up Radar Sensor Daemon for Raspberry Pi..."

# Create log directory
echo "Creating log directory: $LOG_DIR"
sudo mkdir -p "$LOG_DIR"
sudo chown "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR"
sudo chmod 755 "$LOG_DIR"

# Make boot script executable
chmod +x "$SCRIPT_DIR/pi_radar_daemon.py"
chmod +x "$SCRIPT_DIR/run_radar_daemon_rpi.sh"

# Create systemd service file
echo "Creating systemd service: $SERVICE_FILE"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Radar Sensor Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/run_radar_daemon_rpi.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
echo "Registering service with systemd..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME.service"

echo ""
echo "Setup complete! To start the service, run:"
echo "  sudo systemctl start $SERVICE_NAME"
echo ""
echo "To view logs, run:"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "To check service status:"
echo "  sudo systemctl status $SERVICE_NAME"
