# Raspberry Pi Radar Sensor Daemon Setup Guide

## Overview

The **Pi Radar Daemon** (`pi_radar_daemon.py`) is a lightweight, headless program designed specifically for running the Acconeer XE125 radar sensor on a **Raspberry Pi 3** (and compatible models).

### Key Features

- **Headless Operation**: No GUI overhead—runs as a background service
- **Continuous Measurement**: Automatic data collection in velocity or distance mode
- **CSV Logging**: Automatic log rotation and data persistence
- **JSON API**: Remote monitoring via HTTP (e.g., from a dashboard server)
- **Systemd Integration**: Runs automatically on boot with automatic restart on failure
- **Resource Optimized**: Minimal memory/CPU footprint for Pi 3
- **Graceful Shutdown**: Signal handling for clean termination

---

## Hardware Requirements

- **Raspberry Pi 3** (or Pi 4, Pi 5, Pi Zero 2)
- **Acconeer XE125 Radar Sensor** (A121)
- **USB-to-Serial Cable** (for sensor connection)
- **Power Supply**: 5V/2.5A minimum
- **SD Card**: 16GB+ (for OS + logs)
- **Network Connection**: Ethernet or WiFi (optional, for remote monitoring)

---

## Installation Steps

### Step 1: Install Raspberry Pi OS

1. Download **Raspberry Pi OS** (Bookworm or newer) from [raspberrypi.com](https://www.raspberrypi.com/software/)
2. Use **Raspberry Pi Imager** to write the OS to your SD card
3. Boot the Pi and complete initial setup

### Step 2: Install Python Dependencies

Connect to your Pi via SSH or terminal:

```bash
sudo apt update
sudo apt upgrade -y

# Install Python and pip
sudo apt install -y python3 python3-pip python3-venv git

# Verify Python version
python3 --version  # Should be 3.10+
```

### Step 3: Clone/Copy the Project

Option A: **Clone from GitHub**
```bash
cd ~
git clone https://github.com/kenny4tw/RadarSensor.git
cd RadarSensor
```

Option B: **Copy files via SCP**
```bash
scp pi@<PI_IP>:~/WaterVelocityMeassure/* .
```

### Step 4: Set Up Python Virtual Environment

```bash
cd ~/WaterVelocityMeassure

# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

### Step 5: Configure the Daemon

Edit `sensors_rpi.json` to match your setup:

```bash
nano sensors_rpi.json
```

**Key settings**:

| Setting | Description | Example |
|---------|-------------|---------|
| `serial_port` | USB serial port for sensor | `/dev/ttyUSB0` |
| `mode` | Measurement mode | `velocity` or `distance` |
| `output_rate` | Measurements per second | `2.0` |
| `log_dir` | Directory for CSV logs | `/var/log/radar_daemon` |

**Find your serial port:**
```bash
ls -la /dev/ttyUSB*   # USB adapters
ls -la /dev/ttyAMA*   # GPIO UART
```

### Step 6: Install as Systemd Service

Run the setup script (requires `sudo`):

```bash
chmod +x setup_rpi.sh
sudo bash setup_rpi.sh
```

This will:
- Create the log directory
- Create a systemd service file
- Enable automatic startup on boot

### Step 7: Start the Daemon

```bash
# Start the service
sudo systemctl start radar-daemon

# Check status
sudo systemctl status radar-daemon

# View live logs
sudo journalctl -u radar-daemon -f
```

---

## Usage

### Start/Stop

```bash
# Start
sudo systemctl start radar-daemon

# Stop
sudo systemctl stop radar-daemon

# Restart
sudo systemctl restart radar-daemon

# Enable autostart on boot
sudo systemctl enable radar-daemon

# Disable autostart
sudo systemctl disable radar-daemon
```

### View Logs

```bash
# Real-time logs
sudo journalctl -u radar-daemon -f

# Last 100 lines
sudo journalctl -u radar-daemon -n 100

# Logs from last hour
sudo journalctl -u radar-daemon --since "1 hour ago"
```

### Check JSON API Status

If you enabled the JSON API (`"enable_json_api": true`), you can query the daemon status from another machine:

```bash
# From another computer on your network
curl http://<PI_IP>:8080/status | jq .

# Example output:
# {
#   "timestamp": "2024-04-17T14:23:45.123456",
#   "daemon_running": true,
#   "sensors": {
#     "sensor1": {
#       "running": true,
#       "mode": "velocity",
#       "last_measurement": 0.42,
#       "measurement_count": 1234,
#       "error_count": 0,
#       "connected": true
#     }
#   }
# }
```

### Access CSV Logs

Logs are stored in the directory specified in `sensors_rpi.json` (default: `/var/log/radar_daemon/`):

```bash
# View latest log
tail -f /var/log/radar_daemon/*.csv

# Download via SCP
scp -r pi@<PI_IP>:/var/log/radar_daemon/ ./logs/
```

CSV format:
```
timestamp,value,measurement_count
2024-04-17T14:23:45.123456,0.42,1234
2024-04-17T14:23:46.234567,0.43,1235
```

---

## Configuration Examples

### Velocity Measurement

```json
{
  "sensors": [
    {
      "id": "sensor1",
      "mode": "velocity",
      "connection_type": "serial",
      "serial_port": "/dev/ttyUSB0",
      "velocity_config": {
        "surface_distance": 0.25,
        "angle": 45.0,
        "sweeps": 128,
        "hwaas": 16
      }
    }
  ]
}
```

### Distance Measurement

```json
{
  "sensors": [
    {
      "id": "sensor1",
      "mode": "distance",
      "connection_type": "serial",
      "serial_port": "/dev/ttyUSB0",
      "distance_config": {
        "start": 0.25,
        "end": 3.0,
        "signal_quality": 25.0,
        "threshold_sensitivity": 0.35
      }
    }
  ]
}
```

### Multiple Sensors

```json
{
  "sensors": [
    {
      "id": "sensor1",
      "connection_type": "serial",
      "serial_port": "/dev/ttyUSB0",
      "mode": "velocity"
    },
    {
      "id": "sensor2",
      "connection_type": "serial",
      "serial_port": "/dev/ttyUSB1",
      "mode": "distance"
    }
  ]
}
```

---

## Troubleshooting

### Issue: "Serial port not found"

**Solution**: Check the correct port:
```bash
ls /dev/tty*
dmesg | grep tty  # Check kernel messages
```

Update `serial_port` in `sensors_rpi.json`.

### Issue: "SDK not available" / Import Error

**Solution**: Install dependencies in virtual environment:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Issue: Crashes after a few minutes

**Solution**:
1. Check logs: `sudo journalctl -u radar-daemon -f`
2. Increase error tolerance in code or check sensor connection
3. Try increasing output rate intervals in config

### Issue: High CPU or Memory Usage

**Solution**:
1. Reduce `output_rate` (fewer measurements per second)
2. Reduce `sweeps` and `hwaas` in velocity config
3. Check for background processes: `top` or `htop`

### Issue: Service won't start on boot

**Solution**:
```bash
sudo systemctl enable radar-daemon
sudo systemctl status radar-daemon  # Check for errors
sudo journalctl -u radar-daemon -n 50  # View logs
```

---

## Manual Testing

Before deploying as a service, test the daemon manually:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run daemon directly (with control-C to stop)
python3 pi_radar_daemon.py --config sensors_rpi.json

# Or with custom log level
python3 pi_radar_daemon.py --config sensors_rpi.json --log-level DEBUG
```

---

## Uninstall

To remove the daemon:

```bash
# Stop and disable service
sudo systemctl stop radar-daemon
sudo systemctl disable radar-daemon

# Remove service file
sudo rm /etc/systemd/system/radar-daemon.service

# Reload systemd
sudo systemctl daemon-reload

# Remove project files (optional)
rm -rf ~/WaterVelocityMeassure
```

---

## Integration with Dashboard

The JSON API allows the Raspberry Pi daemon to stream status to the **WaterVelocity Dashboard** on another machine:

1. **On Pi**: Enable JSON API in `sensors_rpi.json`:
   ```json
   "enable_json_api": true,
   "json_api_port": 8080
   ```

2. **On Dashboard Server**: Add Pi as a network sensor:
   ```json
   {
     "id": "pi_sensor",
     "connection_type": "network",
     "host": "<PI_IP>",
     "json_port": 8080
   }
   ```

3. Dashboard polls Pi status via HTTP GET to `http://<PI_IP>:8080/status`

---

## Performance Notes

### Raspberry Pi 3 Specs
- **CPU**: 4-core ARM 1.2 GHz
- **RAM**: 1 GB (B+) or 1/2 GB (Pi Zero)
- **Typical Usage**: ~10-15% CPU, 50-100 MB RAM

### Optimization Tips
- Use `distance` mode (lighter) instead of `velocity` for lower resource use
- Reduce `output_rate` to 1.0 Hz or lower
- Run on headless system (no desktop)
- Use SSD or high-speed SD card for faster I/O

---

## Support & Further Help

- **SDK Documentation**: [Acconeer Developer Hub](https://developer.acconeer.com/)
- **Raspberry Pi Docs**: [raspberrypi.com/documentation/](https://www.raspberrypi.com/documentation/)
- **Project Issues**: Check GitHub repository or contact the maintainer

---

**Last Updated**: April 2024  
**Tested On**: Raspberry Pi 3 Model B+, Raspberry Pi 4, OS: Bookworm
