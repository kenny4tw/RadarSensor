# Water Velocity & Distance Measurement — User Guide

Radar-based water surface velocity and distance measurement using the
**Acconeer XE125** (A121 Sparse IQ) sensor.

---

## Table of Contents

1. [Dependencies](#dependencies)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Commands](#commands)
   - [velocity](#velocity-command)
   - [distance](#distance-command)
5. [Connection Options](#connection-options)
6. [CSV Output Format](#csv-output-format)
7. [Running Two Radars Simultaneously](#running-two-radars-simultaneously)
8. [Standalone Executable (.exe)](#standalone-executable)

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
| `--log FILE`           | str   | `WaterVelocity.csv` | CSV output file.                                                                                       |

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
| `--log FILE`               | str   | `distance.csv` | CSV output file.                                                                                |

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
