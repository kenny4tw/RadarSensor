# Water Velocity & Distance Measurement — User Guide

Radar-based water surface velocity and distance measurement using the
**Acconeer XE125** (A121 Sparse IQ) sensor.

---

## Table of Contents

1. [Dependencies](#dependencies)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [GUI Application](#gui-application)
5. [Web Dashboard (multiple sensors)](#web-dashboard-multiple-sensors)
6. [Commands](#commands)
   - [velocity](#velocity-command)
   - [distance](#distance-command)
7. [Connection Options](#connection-options)
8. [CSV Output Format](#csv-output-format)
9. [Running Two Radars Simultaneously](#running-two-radars-simultaneously)
10. [Standalone Executable (.exe)](#standalone-executable)

---

## Dependencies

| Package            | Version   | Purpose                                  |
|--------------------|-----------|------------------------------------------|
| Python             | >= 3.10   | Runtime                                  |
| acconeer-exptool   | >= 7.0.0  | Acconeer A121 SDK (sensor communication) |
| scipy              | (any)     | Signal processing (used by SDK)          |

All Python packages are listed in `requirements.txt`.

---

## Installation

### Option A — With Python installed

1. Install Python 3.10+ from <https://www.python.org/downloads/>
   (check **"Add Python to PATH"** during installation).
2. Double-click **`setup.bat`**, or run manually:
   ```
   pip install -r requirements.txt
   ```

### Option B — Standalone .exe (no Python needed)

See [Standalone Executable](#standalone-executable) below.

---

## Quick Start

```
python surface_velocity.py velocity --port COM3
python surface_velocity.py distance --port COM3
```

Press **Ctrl-C** to stop a measurement.

---

## GUI Application

A graphical user interface (GUI) is available for easy configuration and control of the radar sensor.

### Running the GUI

```
python radarsensor.py
```

Or use the batch file:

```
run_radarsensor.bat
```

### Autostart on Linux (systemd user service)

From the project folder:

```
chmod +x run_radarsensor_linux.sh install_radarsensor_autostart_linux.sh
./install_radarsensor_autostart_linux.sh
```

Useful commands:

```
systemctl --user status radarsensor-gui.service
journalctl --user -u radarsensor-gui.service -f
systemctl --user stop radarsensor-gui.service
systemctl --user disable radarsensor-gui.service
```

If the service should run after reboot before manual login, enable lingering once:

```
sudo loginctl enable-linger $USER
```

### Pin to Taskbar on GNOME / Ubuntu

Run the helper script once from the project folder — it auto-detects the path,
so no manual editing is needed:

```
chmod +x create_desktop_shortcut_linux.sh
./create_desktop_shortcut_linux.sh
```

Then:

1. Press the **Super** key to open the app menu.
2. Search for **Radar Sensor GUI**.
3. Right-click the icon and choose **Add to Favorites**.

The icon will appear permanently in the GNOME Dash (left-side taskbar).

If the app does not appear in the menu immediately, refresh the database:

```
update-desktop-database ~/.local/share/applications
```

### GUI Features

- **Connection Setup**: Configure serial port (default COM9) or TCP/IP connection to the sensor
- **Mode Selection**: Choose between velocity or distance measurement modes
- **Parameter Configuration**: Adjust all sensor parameters through intuitive controls
- **Real-time Display**: View live sensor measurements in a scrollable text area with full timestamps
- **Start/Stop Control**: Easy buttons to begin and end sensor measurements
- **CSV Logging**: Optional logging of measurements to CSV files
- **Profile Save/Load**: Save and load all sensor configurations at once (all sensors in one JSON profile)
- **JSON Output**: Optional HTTP endpoint for LabVIEW or other applications to poll measurement data
- **Live Graphing**: Real-time plotting of sensor data with adjustable time window
- **Average Values**: Display of average measurements over the selected time window

The GUI provides separate tabs for:
- **Connection**: Set up sensor connection parameters
- **Velocity Mode**: Configure velocity measurement parameters
- **Distance Mode**: Configure distance measurement parameters
- **Control & Output**: Start/stop controls, live output display, graphing, and averages

#### JSON Output for LabVIEW

When JSON output is enabled, the GUI starts an HTTP server that provides measurement data in JSON format. LabVIEW can poll this endpoint to retrieve the latest sensor readings.

- **URL**: `http://<this-pc-ip>:<port>/` (default port 8080)
- **Format**: JSON object with measurement data
- **Example response** (velocity mode):
  ```json
  {
    "mode": "velocity",
    "timestamp": 1640995200.123,
    "elapsed_s": 10.5,
    "velocity_m_s": 0.234,
    "distance_m": 1.25,
    "surface_distance_m": 1.0,
    "angle_deg": 45.0
  }
  ```
- **Example response** (distance mode):
  ```json
  {
    "mode": "distance",
    "timestamp": 1640995200.123,
    "elapsed_s": 10.5,
    "distance_m": 1.25,
    "avg_distance_m": 1.23,
    "strength_db": 15.7,
    "start_m": 0.25,
    "end_m": 3.0,
    "update_rate_hz": 10.0
  }
  ```

#### Live Graphing

The GUI includes a real-time graph that displays sensor measurements over time:

- **Time Window**: Adjustable from 10 to 300 seconds
- **Velocity Mode**: Shows both velocity (blue) and distance (red) on dual Y-axes
- **Distance Mode**: Shows distance measurements over time
- **Average Display**: Shows average values over the selected time window
- **Automatic Updates**: Graph updates in real-time as new measurements arrive

---

## Web Dashboard (multiple sensors)

A web dashboard is included for monitoring multiple sensors and polling their
JSON network-variable endpoints from any PC on your network.

### Running from Python

```
python dashboard.py
```

Then open a browser to:

```
http://<host>:5000/
```

The dashboard lets you:

- Add/edit multiple sensors (COM port, netvar port, mode, etc.)
- Start/stop the local helper process for each sensor (when running locally)
- Poll each sensor's netvar endpoint and display the latest values
- See the JSON netvar URL for easy copy/paste into LabVIEW

## Opta JSON Dashboard

An additional dashboard is available for the Arduino Opta setup. It runs independently from the main Water Velocity dashboard, so both can stay active on the same Ubuntu machine.

### Run the Opta dashboard

```
python opta_dashboard.py
```

Or on Ubuntu/Linux with the helper script:

```
chmod +x run_opta_dashboard_linux.sh
./run_opta_dashboard_linux.sh
```

Then open:

```
http://<host>:5051/
```

### Opta dashboard features

- Polls the Opta JSON endpoints `/data.json` and `/control.json`
- Mirrors both payloads into local files `opta_data.json` and `opta_control.json`
- Lets you start/stop the Opta measurement loop and update `q_soll_l_s`
- Displays calculated `Q`, `h`, and derived control value `K`
- Can start/stop CSV logging into `opta_json_history.csv`, storing both JSON payloads together with the key values

### Standalone dashboard executable

You can build a standalone dashboard EXE (no Python needed) using:

```
build_dashboard.bat
```

That produces:

```
dist\WaterVelocityDashboard.exe
```

Run it on any Windows PC, then browse to:

```
http://<host>:5000/
```

---

## Commands

### velocity command

Measures water surface velocity using Doppler processing.

```
python surface_velocity.py velocity [OPTIONS]
```

| Parameter              | Type  | Default             | Description                                                                                            |
|------------------------|-------|---------------------|--------------------------------------------------------------------------------------------------------|
| `--port PORT`          | str   | (auto-detect)       | Serial port, e.g. `COM3` (Windows) or `/dev/ttyUSB0` (Linux). Mutually exclusive with `--ip`.         |
| `--ip ADDR`            | str   | (auto-detect)       | IP address for TCP/IP connection. Mutually exclusive with `--port`.                                    |
| `--sensor-id`          | int   | 1                   | Sensor ID on the module (usually 1).                                                                   |
| `--surface-distance`   | float | 1.0                 | Perpendicular distance from sensor to water surface [m].                                               |
| `--angle`              | float | 45.0                | Sensor angle from vertical (straight down = 0°). Must be between 0° and 90° (exclusive).              |
| `--num-points`         | int   | 4                   | Number of range points inside the measurement window.                                                  |
| `--sweeps`             | int   | 128                 | Sweeps per frame. More sweeps = better velocity resolution.                                            |
| `--frame-rate`         | float | None (auto)         | Do NOT set this. Velocity mode uses continuous sweep mode which determines it automatically.            |
| `--hwaas`              | int   | 16                  | Hardware Accelerated Averaging. Higher = better SNR, slower sweep rate.                                |
| `--time-series`        | int   | 512                 | Length of the velocity time series used by the processor.                                               |
| `--lp-coeff`           | float | 0.75                | Low-pass filter coefficient [0–1]. Lower = faster response to direction changes.                       |
| `--cfar-sensitivity`   | float | 0.5                 | CFAR detection sensitivity [0–1]. Higher = lower threshold = more detections.                          |
| `--max-peak-interval`  | float | 1.0                 | Seconds without a detected peak before velocity resets to 0. Also controls direction-flip hold time.   |
| `--slow-zone`          | int   | 3                   | Half-width (FFT bins) of the dead zone around 0 m/s. Reduce to detect very slow flows.                |
| `--log FILE`           | str   | None                | CSV output file. If omitted, no file is written.                                                        |
| `--netvar-port PORT`   | int   | None                | Host a simple HTTP endpoint that returns the latest measurement in JSON (LabVIEW can poll this).       |
| `--output-rate`        | float | 4.0                 | Maximum output rate [Hz] for console output and GUI events. Set to 0 to emit every frame.              |
| `--no-gui-events`      | flag  | false               | Disable `@@GUI_EVENT@@` output for lower process I/O load.                                              |

**Example with all parameters:**

```
python surface_velocity.py velocity --port COM3 --surface-distance 1.7 --angle 45 --num-points 4 --sweeps 128 --hwaas 16 --time-series 512 --lp-coeff 0.75 --cfar-sensitivity 0.5 --max-peak-interval 1.0 --slow-zone 3 --log WaterVelocity.csv
```

---

### distance command

Measures the distance from the sensor to the water surface.

```
python surface_velocity.py distance [OPTIONS]
```

| Parameter                  | Type  | Default        | Description                                                                                     |
|----------------------------|-------|----------------|-------------------------------------------------------------------------------------------------|
| `--port PORT`              | str   | (auto-detect)  | Serial port, e.g. `COM3`. Mutually exclusive with `--ip`.                                      |
| `--ip ADDR`                | str   | (auto-detect)  | IP address for TCP/IP connection. Mutually exclusive with `--port`.                             |
| `--sensor-id`              | int   | 1              | Sensor ID on the module (usually 1).                                                            |
| `--start`                  | float | 0.25           | Measurement range start [m].                                                                    |
| `--end`                    | float | 3.0            | Measurement range end [m].                                                                      |
| `--update-rate`            | float | 10.0           | Measurement update rate [Hz].                                                                   |
| `--signal-quality`         | float | 25.0           | Signal quality [dB]. Higher = more HW averaging = steadier readings but slower update.          |
| `--threshold-sensitivity`  | float | 0.35           | Detection threshold sensitivity [0–1]. Lower = stricter, rejects weak reflections.              |
| `--min-strength`           | float | 5.0            | Minimum peak strength [dB] to accept a detection. Readings below this are discarded.            |
| `--avg-window`             | int   | 5              | Moving-average window size. Smooths distance over N frames (1 = no smoothing).                  |
| `--log FILE`               | str   | None           | CSV output file. If omitted, no file is written.                                                |
| `--netvar-port PORT`       | int   | None           | Host a simple HTTP endpoint that returns the latest measurement in JSON (LabVIEW can poll this).   |
| `--output-rate`            | float | 4.0            | Maximum output rate [Hz] for console output and GUI events. Set to 0 to emit every frame.      |
| `--no-gui-events`          | flag  | false          | Disable `@@GUI_EVENT@@` output for lower process I/O load.                                       |

**Example with all parameters:**

```
python surface_velocity.py distance --port COM3 --start 0.25 --end 3.0 --update-rate 10 --signal-quality 25 --threshold-sensitivity 0.35 --min-strength 5.0 --avg-window 5 --log distance.csv
```

---

## Connection Options

The sensor can be connected in three ways (same for both commands):

| Method      | Flag             | Example                         |
|-------------|------------------|---------------------------------|
| USB / UART  | `--port PORT`    | `--port COM3`                   |
| TCP/IP      | `--ip ADDR`      | `--ip 192.168.1.100`            |
| Auto-detect | (no flag)        | Scans USB ports automatically   |

---

## CSV Output Format

Both commands write semicolon-separated (`;`) CSV files.

### Velocity CSV (`WaterVelocity.csv`)

| Column         | Description                                 |
|----------------|---------------------------------------------|
| year           | Timestamp year                              |
| month          | Timestamp month                             |
| day            | Timestamp day                               |
| hours          | Timestamp hours                             |
| minutes        | Timestamp minutes                           |
| seconds        | Timestamp seconds                           |
| milliseconds   | Timestamp milliseconds                      |
| elapsed_s      | Seconds since measurement start             |
| velocity_m_s   | Surface velocity [m/s] (+ / - for direction)|
| distance_m     | Distance to surface [m]                     |

### Distance CSV (`distance.csv`)

| Column         | Description                                    |
|----------------|------------------------------------------------|
| year           | Timestamp year                                 |
| month          | Timestamp month                                |
| day            | Timestamp day                                  |
| hours          | Timestamp hours                                |
| minutes        | Timestamp minutes                              |
| seconds        | Timestamp seconds                              |
| milliseconds   | Timestamp milliseconds                         |
| elapsed_s      | Seconds since measurement start                |
| distance_m     | Moving-averaged distance to surface [m]        |
| strength       | Peak detection strength [dB]                   |

Bad signal behavior:
If signal quality is too poor (no valid detection), both velocity and distance modes emit `42` as fallback output values.

---

## Running Two Radars Simultaneously

Connect each radar to a different USB port. Open two terminal windows and run
with different `--port` and `--log` values:

**Terminal 1:**
```
python surface_velocity.py velocity --port COM3 --log WaterVelocity_Radar1.csv
```

**Terminal 2:**
```
python surface_velocity.py velocity --port COM4 --log WaterVelocity_Radar2.csv
```

You can also mix modes (velocity on one, distance on the other).

---

## LabVIEW network variable (HTTP polling)

The program can host a small HTTP endpoint that always returns the latest measurement in JSON. LabVIEW can poll this like a “network variable” using the HTTP Client VIs.

- Use `--netvar-port <PORT>` to enable it.
- The endpoint is available at `http://<host>:<PORT>/` (or `/status`).
- Example JSON payload (velocity mode):

```json
{
  "mode": "velocity",
  "elapsed_s": 3.14,
  "velocity_m_s": 0.0123,
  "distance_m": 1.234,
  "timestamp": 1710854321.123456
}
```

---

## Standalone Executable

To distribute the program to users who do not have Python installed:

1. On **your** PC (with Python), double-click **`build_exe.bat`**.
2. The build produces `dist\WaterVelocityMeasure.exe`.
3. Copy that single `.exe` file to the target laptop.

Usage on the target PC is identical, just replace `python surface_velocity.py`
with `WaterVelocityMeasure.exe`:

```
WaterVelocityMeasure.exe velocity --port COM3
WaterVelocityMeasure.exe distance --port COM3
WaterVelocityMeasure.exe velocity --help
WaterVelocityMeasure.exe distance --help
```

All parameters listed above work the same way with the `.exe`.
