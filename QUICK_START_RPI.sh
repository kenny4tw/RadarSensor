#!/bin/bash
# Quick Start Guide for Pi Radar Daemon
# Run these commands in sequence on your Raspberry Pi

echo "=== Pi Radar Daemon Quick Start ==="
echo ""
echo "[1/6] Updating system..."
sudo apt update && sudo apt upgrade -y

echo ""
echo "[2/6] Installing Python..."
sudo apt install -y python3 python3-pip python3-venv git

echo ""
echo "[3/6] Navigating to project directory..."
if [ -d ~/RadarSensor ]; then
	cd ~/RadarSensor
elif [ -d ~/WaterVelocityMeassure ]; then
	cd ~/WaterVelocityMeassure
else
	echo "Directory not found. Clone the repo first:"
	echo "  git clone https://github.com/kenny4tw/RadarSensor.git"
	exit 1
fi

echo ""
echo "[4/6] Setting up Python virtual environment..."
if ! touch .write_test 2>/dev/null; then
	echo "Cannot write to $(pwd)."
	echo "Check that you cloned into your home directory, the filesystem is not read-only, and the SD card is not full."
	echo "Helpful checks: pwd ; ls -ld . ; df -h . ; mount | grep ' on / '"
	exit 1
fi
rm -f .write_test

if ! python3 -m venv .venv; then
	echo "Failed to create .venv in $(pwd)."
	echo "Make sure python3-venv is installed and this directory is writable."
	exit 1
fi
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "[5/6] Installing as systemd service..."
chmod +x setup_rpi.sh run_radar_daemon_rpi.sh
sudo bash setup_rpi.sh

echo ""
echo "[6/6] Starting the service..."
sudo systemctl start radar-daemon

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Check status:"
echo "  sudo systemctl status radar-daemon"
echo ""
echo "View live logs:"
echo "  sudo journalctl -u radar-daemon -f"
echo ""
echo "Query API status:"
echo "  curl http://localhost:8080/status | jq ."
echo ""
echo "Stop service:"
echo "  sudo systemctl stop radar-daemon"
echo ""
