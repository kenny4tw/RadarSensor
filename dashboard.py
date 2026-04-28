#!/usr/bin/env python3
"""Web dashboard for monitoring multiple Acconeer XE125 sensors.

This dashboard lets you:
  - Define multiple sensors (local or remote)
  - Start/stop local measurement processes (using the existing executable)
  - Poll each sensor's JSON "network variable" endpoint
  - View the latest values in a browser (accessible from other machines)

Run:
    python dashboard.py

Open in browser:
    http://<host>:5000/

"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import subprocess
from pathlib import Path
from subprocess import Popen
from typing import Any, Dict, List, Optional

try:
    from serial.tools import list_ports as _list_ports
    _SERIAL_AVAILABLE = True
except ImportError:
    _list_ports = None
    _SERIAL_AVAILABLE = False

from flask import Flask, jsonify, render_template_string, request

APP = Flask(__name__)

if getattr(sys, "frozen", False):
    # When running as an EXE, store config next to the executable
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "sensors.json"
PROFILES_PATH = BASE_DIR / "profiles.json"

DEFAULT_CONFIG = {
    "sensors": [
        {
            "id": "sensor1",
            "name": "Sensor 1",
            "host": "localhost",
            "mode": "velocity",
            "port": "COM9",
            "netvar_port": 8000,
            "control_mode": "auto",
            "remote_sensor_id": "sensor1",
            "surface_distance": 1.0,
            "angle": 45.0,
            "hwaas": 16,
            "sweeps": 128,
            "time_series": 512,
            "lp_coeff": 0.75,
            "cfar_sensitivity": 0.5,
            "max_peak_interval": 1.0,
            "slow_zone": 3,
            "start": 0.25,
            "end": 3.0,
            "update_rate": 10.0,
            "signal_quality": 25.0,
            "threshold_sensitivity": 0.35,
            "min_strength": 5.0,
            "avg_window": 5,
            "auto_start": False,
        }
    ]
}

# Shared state
_STATE_LOCK = threading.RLock()
_SENSORS: Dict[str, Dict[str, Any]] = {}
_SENSOR_DATA: Dict[str, Dict[str, Any]] = {}
_SENSOR_PROCESSES: Dict[str, Popen] = {}
_ACTIVE_SENSORS: set[str] = set()
_PROFILES: Dict[str, Dict[str, Any]] = {}

_POLL_INTERVAL_S = 0.5

# Debug/status tracking
_DEBUG_LOG: List[str] = []
_MAX_DEBUG_LINES = 100


def _should_log_worker_line(line: str) -> bool:
    """Keep only actionable worker lines in dashboard logs.

    Measurement/event lines can arrive at high rate and cause large CPU load when
    multiple sensors run in parallel.
    """
    text = line.strip()
    if not text:
        return False

    if text.startswith("@@GUI_EVENT@@"):
        return False

    lowered = text.lower()
    interesting_tokens = (
        "[error]",
        "error",
        "exception",
        "failed",
        "connecting",
        "network variable served",
        "session active",
        "session closed",
        "calibrating",
    )
    return any(token in lowered for token in interesting_tokens)


def _debug_log(msg: str) -> None:
    """Add a debug message to the shared log."""
    global _DEBUG_LOG
    timestamp = time.strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {msg}"
    print(full_msg)  # Also print to console
    with _STATE_LOCK:
        _DEBUG_LOG.append(full_msg)
        if len(_DEBUG_LOG) > _MAX_DEBUG_LINES:
            _DEBUG_LOG.pop(0)


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Water Velocity Dashboard</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 12px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
    th { background: #eee; }
    input, select { width: 100%; box-sizing: border-box; }
    button { padding: 6px 10px; }
    .status-ok { color: green; }
    .status-bad { color: red; }
  </style>
</head>
<body>
  <h1>Water Velocity Dashboard</h1>
  <p>Use this dashboard to monitor multiple sensors and view the latest values.
     The dashboard polls each sensor's <code>/</code> JSON endpoint.</p>

  <div>
    <button onclick="refresh()">Refresh</button>
    <span id="status" style="margin-left: 16px; color: red; font-weight: bold;"></span>
  </div>

  <table id="sensor-table">
    <thead>
      <tr>
        <th>ID</th>
        <th>Name</th>
        <th>Mode</th>
        <th>Host</th>
        <th>Netvar Port</th>
        <th>Netvar URL</th>
        <th>Last update</th>
        <th>Velocity</th>
        <th>Distance</th>
        <th>Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

  <h2>Add / Update Sensor</h2>
  <form id="sensor-form" onsubmit="return saveSensor()">
    <table>
      <tr><td>ID:</td><td><input id="id" required></td></tr>
      <tr><td>Name:</td><td><input id="name" required></td></tr>
      <tr><td>Mode:</td><td><select id="mode" onchange="updateForm()"><option value="velocity">velocity</option><option value="distance">distance</option></select></td></tr>
      <tr><td>Host:</td><td><input id="host" value="localhost" oninput="updateComPortVisibility()"></td></tr>
      <tr id="comport-row"><td>COM Port:</td><td>
        <div style="display:flex;gap:6px;align-items:center;">
          <select id="port-select" style="flex:1;" onchange="document.getElementById('port').value=this.value;"><option value="">— scanning… —</option></select>
          <button type="button" onclick="refreshComPorts()" title="Refresh COM ports">&#x21bb;</button>
        </div>
        <input id="port" value="COM9" placeholder="e.g. COM9 or /dev/ttyUSB0" style="margin-top:4px;width:100%;box-sizing:border-box;">
      </td></tr>
      <tr><td>Netvar Port:</td><td><input id="netvar_port" type="number" value="8000"></td></tr>
    <tr><td>Control Mode:</td><td><select id="control_mode"><option value="auto">auto</option><option value="remote">remote</option><option value="local">local</option></select></td></tr>
    <tr><td>Remote Sensor ID:</td><td><input id="remote_sensor_id" value="sensor1"></td></tr>

      <!-- Velocity-specific parameters -->
      <tr id="velocity-params" style="display:none;">
        <td colspan="2"><strong>Velocity Parameters:</strong></td>
      </tr>
      <tr id="surface_distance_row" style="display:none;"><td>Surface Distance (m):</td><td><input id="surface_distance" type="number" step="0.1" value="1.0"></td></tr>
      <tr id="angle_row" style="display:none;"><td>Angle (°):</td><td><input id="angle" type="number" step="1" value="45"></td></tr>
      <tr id="hwaas_row" style="display:none;"><td>HWAAS:</td><td><input id="hwaas" type="number" value="16"></td></tr>
      <tr id="sweeps_row" style="display:none;"><td>Sweeps per Frame:</td><td><input id="sweeps" type="number" value="128"></td></tr>
      <tr id="time_series_row" style="display:none;"><td>Time Series Length:</td><td><input id="time_series" type="number" value="512"></td></tr>
      <tr id="lp_coeff_row" style="display:none;"><td>LP Coefficient:</td><td><input id="lp_coeff" type="number" step="0.01" value="0.75"></td></tr>
      <tr id="cfar_sensitivity_row" style="display:none;"><td>CFAR Sensitivity:</td><td><input id="cfar_sensitivity" type="number" step="0.01" value="0.5"></td></tr>
      <tr id="max_peak_interval_row" style="display:none;"><td>Max Peak Interval (s):</td><td><input id="max_peak_interval" type="number" step="0.1" value="1.0"></td></tr>
      <tr id="slow_zone_row" style="display:none;"><td>Slow Zone:</td><td><input id="slow_zone" type="number" value="3"></td></tr>

      <!-- Distance-specific parameters -->
      <tr id="distance-params" style="display:none;">
        <td colspan="2"><strong>Distance Parameters:</strong></td>
      </tr>
      <tr id="start_row" style="display:none;"><td>Start (m):</td><td><input id="start" type="number" step="0.01" value="0.25" placeholder="0.25"></td></tr>
      <tr id="end_row" style="display:none;"><td>End (m):</td><td><input id="end" type="number" step="0.01" value="3.0" placeholder="3.0"></td></tr>
      <tr id="update_rate_row" style="display:none;"><td>Update Rate (Hz):</td><td><input id="update_rate" type="number" step="0.1" value="10.0" placeholder="10.0"></td></tr>
      <tr id="signal_quality_row" style="display:none;"><td>Signal Quality (dB):</td><td><input id="signal_quality" type="number" step="1" value="25.0" placeholder="25.0"></td></tr>
      <tr id="threshold_sensitivity_row" style="display:none;"><td>Threshold Sensitivity:</td><td><input id="threshold_sensitivity" type="number" step="0.01" value="0.35" placeholder="0.35"></td></tr>
      <tr id="min_strength_row" style="display:none;"><td>Min Strength (dB):</td><td><input id="min_strength" type="number" step="1" value="5.0" placeholder="5.0"></td></tr>
      <tr id="avg_window_row" style="display:none;"><td>Avg Window:</td><td><input id="avg_window" type="number" value="5" placeholder="5"></td></tr>

      <tr><td colspan="2"><button type="submit">Save Sensor</button></td></tr>
    </table>
  </form>

  <div style="margin-top: 16px; border: 1px solid #bbb; border-radius: 4px; padding: 12px; background: #fafafa;">
    <h3 style="margin-top:0;">Profiles</h3>
    <p style="margin:0 0 8px 0; font-size: 0.9em; color: #555;">
      Profiles store measurement parameters (mode, distances, algorithm settings). They do <em>not</em> store host/port or sensor ID.
    </p>
    <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
      <select id="profile-select" style="min-width:180px;"><option value="">— select profile —</option></select>
      <button type="button" onclick="applyProfile()">Load into Form</button>
      <button type="button" onclick="deleteProfile()" style="color:red;">Delete</button>
    </div>
    <div style="display:flex; gap:8px; margin-top:8px; align-items:center;">
      <input id="profile-name" type="text" placeholder="New profile name…" style="min-width:180px;">
      <button type="button" onclick="saveProfile()">Save Current Form as Profile</button>
    </div>
  </div>

  <div style="margin-top: 24px; border-top: 2px solid #ccc; padding-top: 12px;">
    <h2>Debug Log</h2>
    <button onclick="refreshDebugLog()">Refresh Debug Log</button>
    <button onclick="clearDebugLog()">Clear</button>
    <pre id="debug-log" style="background: #f0f0f0; padding: 8px; overflow-y: auto; max-height: 300px; border: 1px solid #ccc; margin-top: 8px;">(loading...)</pre>
  </div>

  <script>
    async function api(path, options) {
      const res = await fetch(path, options);
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    async function refreshDebugLog() {
      try {
        const data = await api('/api/debug');
        const logEl = document.getElementById('debug-log');
        logEl.textContent = (data.logs || []).join('\\n') || '(no logs yet)';
        logEl.scrollTop = logEl.scrollHeight;
      } catch (e) {
        document.getElementById('debug-log').textContent = `Error: ${e.message}`;
      }
    }

    async function clearDebugLog() {
      document.getElementById('debug-log').textContent = '';
    }


    async function refresh() {
      try {
        const data = await api('/api/sensors');
        console.log('API returned:', data);
        document.getElementById('status').textContent = '';
        const tbody = document.querySelector('#sensor-table tbody');
        tbody.innerHTML = '';
        console.log('Table has', data.length, 'sensors');
        data.forEach((s, i) => {
          const tr = document.createElement('tr');
          const last = s.last_update ? new Date(s.last_update * 1000).toLocaleTimeString() : '-';
          const netvarUrl = s.host && s.netvar_port ? `http://${s.host}:${s.netvar_port}/` : '-';

          let value1 = '-';
          let value2 = '-';
          const displayMode = (s.data && s.data.mode) ? s.data.mode : s.mode;
          if (displayMode === 'velocity') {
            value1 = (s.data && s.data.velocity_m_s != null) ? s.data.velocity_m_s : '-';
            value2 = (s.data && s.data.distance_m != null) ? s.data.distance_m : '-';
          } else if (displayMode === 'distance') {
                        value1 = '-';
                        value2 = (s.data && s.data.avg_distance_m != null) ? s.data.avg_distance_m : '-';
          }

                    // Fallback for Pi daemon status format (single "last_measurement").
                    if (displayMode === 'velocity' && value1 === '-' && s.data && s.data.last_measurement != null) {
                        value1 = s.data.last_measurement;
                    }
                    if (value2 === '-' && s.data && s.data.measurement_count != null) {
                        value2 = `n=${s.data.measurement_count}`;
                    }

          const status = s.last_error ? `ERROR: ${s.last_error}` : 'OK';
          const running = s.running ? 'running' : 'stopped';
          const sensorId = s.id.replace(/"/g, '&quot;');
          const startDisabled = s.running ? 'disabled' : '';
          const stopDisabled = s.running ? '' : 'disabled';
          
          tr.innerHTML = `<td>${s.id}</td><td>${s.name}</td><td>${s.mode}</td><td>${s.host}</td><td>${s.netvar_port}</td><td><a href="${netvarUrl}" target="_blank">${netvarUrl}</a></td><td>${last}</td><td>${value1}</td><td>${value2}</td><td>${status} / ${running}</td><td><button onclick="editSensor('${sensorId}')">Edit</button> <button onclick="startSensor('${sensorId}')" ${startDisabled}>Start</button> <button onclick="stopSensor('${sensorId}')" ${stopDisabled}>Stop</button></td>`;
          tbody.appendChild(tr);
        });
      } catch (e) {
        console.error(e);
        document.getElementById('status').textContent = e.message || String(e);
      }
    }

    function fillForm(sensor) {
            ['id','name','mode','host','port','netvar_port','control_mode','remote_sensor_id'].forEach(k => {
        const el = document.getElementById(k);
        if (el) el.value = sensor[k] ?? '';
      });

      // Fill velocity params
      ['surface_distance','angle','hwaas','sweeps','time_series','lp_coeff','cfar_sensitivity','max_peak_interval','slow_zone'].forEach(k => {
        const el = document.getElementById(k);
        if (el) el.value = sensor[k] ?? '';
      });

      // Fill distance params
      ['start','end','update_rate','signal_quality','threshold_sensitivity','min_strength','avg_window'].forEach(k => {
        const el = document.getElementById(k);
        if (el) el.value = sensor[k] ?? '';
      });

      updateForm();
      updateComPortVisibility();
      // Sync the dropdown to match the loaded port value
      const portSel = document.getElementById('port-select');
      const portVal = document.getElementById('port').value;
      if (portSel && portVal) portSel.value = portVal;
    }

    function updateForm() {
      const mode = document.getElementById('mode').value;
      const velocityRows = ['velocity-params', 'surface_distance_row', 'angle_row', 'hwaas_row', 'sweeps_row', 'time_series_row', 'lp_coeff_row', 'cfar_sensitivity_row', 'max_peak_interval_row', 'slow_zone_row'];
      const distanceRows = ['distance-params', 'start_row', 'end_row', 'update_rate_row', 'signal_quality_row', 'threshold_sensitivity_row', 'min_strength_row', 'avg_window_row'];

      if (mode === 'velocity') {
        velocityRows.forEach(id => document.getElementById(id).style.display = '');
        distanceRows.forEach(id => document.getElementById(id).style.display = 'none');
      } else if (mode === 'distance') {
        velocityRows.forEach(id => document.getElementById(id).style.display = 'none');
        distanceRows.forEach(id => document.getElementById(id).style.display = '');
      }
    }

    async function editSensor(id) {
      const data = await api(`/api/sensors/${encodeURIComponent(id)}`);
      fillForm(data);
    }

    async function saveSensor() {
      const sensor = {
        id: document.getElementById('id').value,
        name: document.getElementById('name').value,
        mode: document.getElementById('mode').value,
        host: document.getElementById('host').value,
        port: document.getElementById('port').value,
        netvar_port: Number(document.getElementById('netvar_port').value),
                control_mode: document.getElementById('control_mode').value,
                remote_sensor_id: document.getElementById('remote_sensor_id').value,
      };

      // Add velocity params
      ['surface_distance','angle','hwaas','sweeps','time_series','lp_coeff','cfar_sensitivity','max_peak_interval','slow_zone'].forEach(k => {
        const val = document.getElementById(k).value;
        if (val !== '') sensor[k] = isNaN(val) ? val : Number(val);
      });

      // Add distance params
      ['start','end','update_rate','signal_quality','threshold_sensitivity','min_strength','avg_window'].forEach(k => {
        const val = document.getElementById(k).value;
        if (val !== '') sensor[k] = isNaN(val) ? val : Number(val);
      });

      await api('/api/sensors', { method: 'POST', body: JSON.stringify(sensor), headers: { 'Content-Type': 'application/json' } });
      await refresh();
      return false;
    }

    async function startSensor(id) {
            // If user is editing this same sensor, persist form changes first.
            const formId = (document.getElementById('id')?.value || '').trim();
            if (formId && formId === id) {
                await saveSensor();
            }
      await api(`/api/sensors/${encodeURIComponent(id)}/start`, { method: 'POST' });
      await refresh();
    }

    async function stopSensor(id) {
      await api(`/api/sensors/${encodeURIComponent(id)}/stop`, { method: 'POST' });
      await refresh();
    }

    // ── Profiles ──────────────────────────────────────────────────────────────
    const PROFILE_KEYS = [
      'mode','surface_distance','angle','hwaas','sweeps','time_series',
      'lp_coeff','cfar_sensitivity','max_peak_interval','slow_zone',
      'start','end','update_rate','signal_quality','threshold_sensitivity',
      'min_strength','avg_window'
    ];

    async function loadProfilesList() {
      const profiles = await api('/api/profiles');
      const sel = document.getElementById('profile-select');
      const prev = sel.value;
      sel.innerHTML = '<option value="">— select profile —</option>';
      Object.keys(profiles).sort().forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        sel.appendChild(opt);
      });
      if (prev && profiles[prev]) sel.value = prev;
    }

    async function applyProfile() {
      const name = document.getElementById('profile-select').value;
      if (!name) return;
      const profiles = await api('/api/profiles');
      const p = profiles[name];
      if (!p) return;
      PROFILE_KEYS.forEach(k => {
        const el = document.getElementById(k);
        if (el && p[k] !== undefined) el.value = p[k];
      });
      updateForm();
    }

    async function saveProfile() {
      const name = document.getElementById('profile-name').value.trim();
      if (!name) { alert('Please enter a profile name.'); return; }
      const profile = { name };
      PROFILE_KEYS.forEach(k => {
        const el = document.getElementById(k);
        if (el && el.value !== '') profile[k] = isNaN(el.value) ? el.value : Number(el.value);
      });
      await api('/api/profiles', { method: 'POST', body: JSON.stringify(profile), headers: { 'Content-Type': 'application/json' } });
      document.getElementById('profile-name').value = '';
      await loadProfilesList();
    }

    async function deleteProfile() {
      const name = document.getElementById('profile-select').value;
      if (!name) return;
      if (!confirm(`Delete profile "${name}"?`)) return;
      await api(`/api/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
      await loadProfilesList();
    }

    // ── COM Ports ─────────────────────────────────────────────────────────────
    async function refreshComPorts() {
      const sel = document.getElementById('port-select');
      const portInput = document.getElementById('port');
      try {
        const data = await api('/api/comports');
        const ports = data.ports || [];
        const prev = portInput.value || sel.value;
        sel.innerHTML = '<option value="">— select port —</option>';
        ports.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.device;
          opt.textContent = `${p.device} — ${p.description}`;
          sel.appendChild(opt);
        });
        if (prev) {
          sel.value = prev;
          if (sel.value) portInput.value = sel.value;
        }
        if (ports.length === 0) {
          sel.innerHTML = '<option value="">(no sensor ports found)</option>';
        }
      } catch (e) {
        sel.innerHTML = '<option value="">(error scanning ports)</option>';
      }
    }

    function updateComPortVisibility() {
      const host = (document.getElementById('host').value || '').trim().toLowerCase();
      const isLocal = host === '' || host === 'localhost' || host === '127.0.0.1' || host === '::1';
      document.getElementById('comport-row').style.display = isLocal ? '' : 'none';
    }

    setInterval(refresh, 1500);
    setInterval(refreshDebugLog, 2000);
    refresh();
    refreshDebugLog();
    updateForm();
    loadProfilesList();
    refreshComPorts();
    updateComPortVisibility();
  </script>
</body>
</html>
"""


def _save_config() -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump({"sensors": list(_SENSORS.values())}, f, indent=2)
        _debug_log(f"Config saved to {CONFIG_PATH}")
    except Exception as e:
        _debug_log(f"ERROR saving config: {e}")


def _load_config() -> None:
    global _SENSORS
    _debug_log(f"Loading config from {CONFIG_PATH}")
    if not CONFIG_PATH.exists():
        _debug_log("Config file not found, creating with defaults")
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        _SENSORS = {s["id"]: s for s in cfg.get("sensors", []) if "id" in s}
        _debug_log(f"Loaded {len(_SENSORS)} sensors")
    except Exception as e:
        _debug_log(f"ERROR loading config: {e}, using defaults")
        _SENSORS = {s["id"]: s for s in DEFAULT_CONFIG["sensors"]}
        _save_config()


# ── Profiles ──────────────────────────────────────────────────────────────────

_PROFILE_KEYS = [
    "mode", "surface_distance", "angle", "hwaas", "sweeps", "time_series",
    "lp_coeff", "cfar_sensitivity", "max_peak_interval", "slow_zone",
    "start", "end", "update_rate", "signal_quality", "threshold_sensitivity",
    "min_strength", "avg_window",
]


def _save_profiles() -> None:
    try:
        PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROFILES_PATH.open("w", encoding="utf-8") as f:
            json.dump({"profiles": _PROFILES}, f, indent=2)
    except Exception as e:
        _debug_log(f"ERROR saving profiles: {e}")


def _load_profiles() -> None:
    global _PROFILES
    if not PROFILES_PATH.exists():
        _PROFILES = {}
        return
    try:
        data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        _PROFILES = data.get("profiles", {})
        _debug_log(f"Loaded {len(_PROFILES)} profiles")
    except Exception as e:
        _debug_log(f"ERROR loading profiles: {e}")
        _PROFILES = {}


def _poll_worker() -> None:
    _debug_log("Polling worker started")
    while True:
        with _STATE_LOCK:
            sensors = [s for sid, s in _SENSORS.items() if sid in _ACTIVE_SENSORS]
        for sensor in sensors:
            sid = sensor["id"]
            host = sensor.get("host", "localhost")
            port = sensor.get("netvar_port")
            if not port:
                continue
            url = f"http://{host}:{port}/"
            try:
                with urllib.request.urlopen(url, timeout=0.75) as resp:
                    text = resp.read().decode("utf-8")
                    raw_data = json.loads(text)

                    normalized_data: Dict[str, Any]
                    if isinstance(raw_data, dict) and "sensors" in raw_data:
                        remote_sensor_id = sensor.get("remote_sensor_id")
                        sensors_map = raw_data.get("sensors", {}) if isinstance(raw_data.get("sensors", {}), dict) else {}

                        remote_entry = None
                        if remote_sensor_id and remote_sensor_id in sensors_map:
                            remote_entry = sensors_map.get(remote_sensor_id)
                        elif sid in sensors_map:
                            remote_entry = sensors_map.get(sid)
                        elif sensors_map:
                            remote_entry = next(iter(sensors_map.values()))

                        normalized_data = {
                            "daemon_running": raw_data.get("daemon_running"),
                            "remote": remote_entry or {},
                            "mode": (remote_entry or {}).get("mode"),
                            "last_measurement": (remote_entry or {}).get("last_measurement"),
                            "measurement_count": (remote_entry or {}).get("measurement_count"),
                            "connected": (remote_entry or {}).get("connected"),
                            "remote_running": (remote_entry or {}).get("running"),
                        }
                    else:
                        normalized_data = raw_data if isinstance(raw_data, dict) else {"value": raw_data}

                    with _STATE_LOCK:
                        _SENSOR_DATA[sid] = {
                            "data": normalized_data,
                            "last_update": time.time(),
                            "last_error": None,
                        }
                    _debug_log(f"✓ {sid}: Updated from {url}")
            except urllib.error.URLError as e:
                with _STATE_LOCK:
                    _SENSOR_DATA[sid] = {
                        "data": None,
                        "last_update": None,
                        "last_error": f"Connection refused: {host}:{port}",
                    }
                _debug_log(f"✗ {sid}: Connection failed to {url} - {e}")
            except json.JSONDecodeError as e:
                with _STATE_LOCK:
                    _SENSOR_DATA[sid] = {
                        "data": None,
                        "last_update": None,
                        "last_error": f"Invalid JSON: {str(e)[:50]}",
                    }
                _debug_log(f"✗ {sid}: Invalid JSON from {url}")
            except Exception as e:
                with _STATE_LOCK:
                    _SENSOR_DATA[sid] = {
                        "data": None,
                        "last_update": None,
                        "last_error": str(e)[:100],
                    }
                _debug_log(f"✗ {sid}: Polling error - {e}")
        time.sleep(_POLL_INTERVAL_S)


def _start_poller() -> None:
    thread = threading.Thread(target=_poll_worker, daemon=True)
    thread.start()


def _build_command(sensor: Dict[str, Any]) -> List[str]:
    """Build command line for running the sensor process."""
    # Prefer an EXE placed next to the dashboard; fallback to dist/ and Python script.
    exe = BASE_DIR / "WaterVelocityMeasure.exe"
    if not exe.exists():
        exe = BASE_DIR / "dist" / "WaterVelocityMeasure.exe"

    if exe.exists():
        cmd = [str(exe)]
    else:
        script = BASE_DIR / "surface_velocity.py"
        if not script.exists():
            raise FileNotFoundError(f"Cannot find WaterVelocityMeasure.exe or surface_velocity.py in {BASE_DIR}")
        cmd = ["python", str(script)]

    mode = sensor.get("mode", "velocity")
    cmd.append(mode)

    port = sensor.get("port")
    if port:
        cmd += ["--port", str(port)]

    netvar = sensor.get("netvar_port")
    if netvar:
        cmd += ["--netvar-port", str(netvar)]

    # Add commonly used parameters for velocity mode if present
    if mode == "velocity":
        for key in [
            ("surface_distance", "--surface-distance"),
            ("angle", "--angle"),
            ("hwaas", "--hwaas"),
            ("sweeps", "--sweeps"),
            ("time_series", "--time-series"),
            ("lp_coeff", "--lp-coeff"),
            ("cfar_sensitivity", "--cfar-sensitivity"),
            ("max_peak_interval", "--max-peak-interval"),
            ("slow_zone", "--slow-zone"),
        ]:
            if key[0] in sensor and sensor[key[0]] is not None:
                cmd += [key[1], str(sensor[key[0]])]

    # Add commonly used parameters for distance mode if present
    if mode == "distance":
        for key in [
            ("start", "--start"),
            ("end", "--end"),
            ("update_rate", "--update-rate"),
            ("signal_quality", "--signal-quality"),
            ("threshold_sensitivity", "--threshold-sensitivity"),
            ("min_strength", "--min-strength"),
            ("avg_window", "--avg-window"),
        ]:
            if key[0] in sensor and sensor[key[0]] is not None:
                cmd += [key[1], str(sensor[key[0]])]

    return cmd


def _start_process(sensor_id: str) -> None:
    with _STATE_LOCK:
        sensor = _SENSORS.get(sensor_id)
        if not sensor:
            _debug_log(f"ERROR: Sensor {sensor_id} not found")
            return
        if sensor_id in _SENSOR_PROCESSES:
            proc = _SENSOR_PROCESSES[sensor_id]
            if proc.poll() is None:
                _debug_log(f"WARN: Sensor {sensor_id} already running (PID {proc.pid})")
                return
            else:
                _debug_log(f"INFO: Sensor {sensor_id} process ended (PID {proc.pid}), restarting")
                del _SENSOR_PROCESSES[sensor_id]
        cmd = _build_command(sensor)

    if not cmd:
        _debug_log(f"ERROR: Could not build command for {sensor_id}")
        raise RuntimeError("Could not build command for sensor")

    cmd_str = ' '.join(cmd)
    _debug_log(f">>> STARTING {sensor_id}")
    _debug_log(f">>> CMD: {cmd_str}")
    
    try:
        proc = Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _SENSOR_PROCESSES[sensor_id] = proc
        _debug_log(f"✓ Started {sensor_id} with PID {proc.pid}")
        
        # Check if process immediately crashed
        import time
        time.sleep(0.5)
        if proc.poll() is not None:
            retcode = proc.returncode
            _debug_log(f"ERROR: Process {sensor_id} exited immediately with code {retcode}")
            try:
                stdout, _ = proc.communicate(timeout=1)
                if stdout:
                    _debug_log(f"Process output: {stdout}")
            except:
                pass
            return
        
        _debug_log(f"✓ Process {sensor_id} is still alive")
        
        # Capture output in background
        def capture_output(p: Popen, sid: str) -> None:
            try:
                if p.stdout is None:
                    return
                for line in p.stdout:
                    clean = line.rstrip()
                    if _should_log_worker_line(clean):
                        _debug_log(f"[{sid}] {clean}")
            except Exception as e:
                _debug_log(f"[{sid}] Error reading output: {e}")
        
        thread = threading.Thread(target=capture_output, args=(proc, sensor_id), daemon=True)
        thread.start()
    except Exception as e:
        _debug_log(f"ERROR starting {sensor_id}: {e}")
        raise


def _is_local_host(host: str) -> bool:
    return str(host).strip().lower() in ("", "localhost", "127.0.0.1", "::1")


def _remote_control(sensor: Dict[str, Any], action: str) -> Dict[str, Any]:
    host = sensor.get("host", "localhost")
    port = int(sensor.get("netvar_port", 8080))
    url = f"http://{host}:{port}/control/{action}"

    body = {}
    remote_sensor_id = sensor.get("remote_sensor_id")
    if remote_sensor_id:
        body["sensor_id"] = remote_sensor_id

    if action == "start":
        body["mode"] = sensor.get("mode", "velocity")

        for key in [
            "surface_distance", "angle", "hwaas", "sweeps", "time_series",
            "lp_coeff", "cfar_sensitivity", "max_peak_interval", "slow_zone",
            "start", "end", "update_rate", "signal_quality",
            "threshold_sensitivity", "min_strength", "avg_window",
        ]:
            if key in sensor and sensor[key] is not None:
                body[key] = sensor[key]

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=2.0) as resp:
        text = resp.read().decode("utf-8")
        return json.loads(text) if text else {"ok": True}


def _stop_process(sensor_id: str) -> None:
    with _STATE_LOCK:
        proc = _SENSOR_PROCESSES.pop(sensor_id, None)
        if not proc:
            _debug_log(f"WARN: Sensor {sensor_id} not running")
            return

    try:
        # First try graceful shutdown.
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            # On Windows, ensure child processes are also terminated.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                proc.kill()
            proc.wait(timeout=2.0)

        _debug_log(f"Stopped {sensor_id} (PID {proc.pid})")
    except Exception as e:
        _debug_log(f"ERROR stopping {sensor_id}: {e}")


@APP.route("/")
def index() -> str:
    return render_template_string(HTML_TEMPLATE)


@APP.route("/api/sensors", methods=["GET"])
def list_sensors() -> Any:
    with _STATE_LOCK:
        out = []
        for sid, sensor in _SENSORS.items():
            data = _SENSOR_DATA.get(sid, {})
            raw_payload = data.get("data")
            sensor_payload = raw_payload if isinstance(raw_payload, dict) else {}
            remote_running = sensor_payload.get("remote_running")
            active = sid in _ACTIVE_SENSORS
            running = active and ((sid in _SENSOR_PROCESSES) or bool(remote_running) or sensor.get("control_mode", "auto") in ("remote", "auto"))
            out.append({
                **sensor,  # Include all sensor config
                "last_update": data.get("last_update"),
                "data": data.get("data"),
                "last_error": data.get("last_error"),
                "running": running,
                "active": active,
            })
        return jsonify(out)


@APP.route("/api/sensors/<sensor_id>", methods=["GET"])
def get_sensor(sensor_id: str) -> Any:
    with _STATE_LOCK:
        sensor = _SENSORS.get(sensor_id)
        if not sensor:
            return jsonify({}), 404
        return jsonify(sensor)


@APP.route("/api/sensors", methods=["POST"])
def add_or_update_sensor() -> Any:
    data = request.get_json(force=True)
    if not data or "id" not in data:
        return jsonify({"error": "Missing id"}), 400

    sid = str(data["id"])
    with _STATE_LOCK:
        _SENSORS[sid] = {**_SENSORS.get(sid, {}), **data}
        # Editing a sensor should not auto-connect; require explicit Start click.
        _ACTIVE_SENSORS.discard(sid)
        _save_config()
    return jsonify({"ok": True})


@APP.route("/api/sensors/<sensor_id>/start", methods=["POST"])
def start_sensor(sensor_id: str) -> Any:
    _debug_log(f"*** START BUTTON CLICKED for {sensor_id}")
    try:
        with _STATE_LOCK:
            sensor = _SENSORS.get(sensor_id)
        if not sensor:
            return jsonify({"ok": False, "error": "Sensor not found"}), 404

        host = sensor.get("host", "localhost")
        control_mode = str(sensor.get("control_mode", "auto")).lower()
        use_remote = (control_mode == "remote") or (control_mode == "auto" and not _is_local_host(host))

        if use_remote:
            result = _remote_control(sensor, "start")
            _debug_log(f"*** REMOTE START for {sensor_id}: {result}")
        else:
            _start_process(sensor_id)
        with _STATE_LOCK:
            _ACTIVE_SENSORS.add(sensor_id)
        _debug_log(f"*** START SUCCESSFUL for {sensor_id}")
        return jsonify({"ok": True})
    except Exception as e:
        _debug_log(f"*** START FAILED for {sensor_id}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@APP.route("/api/sensors/<sensor_id>/stop", methods=["POST"])
def stop_sensor(sensor_id: str) -> Any:
    _debug_log(f"*** STOP BUTTON CLICKED for {sensor_id}")
    try:
        with _STATE_LOCK:
            sensor = _SENSORS.get(sensor_id)
        if not sensor:
            return jsonify({"ok": False, "error": "Sensor not found"}), 404

        host = sensor.get("host", "localhost")
        control_mode = str(sensor.get("control_mode", "auto")).lower()
        use_remote = (control_mode == "remote") or (control_mode == "auto" and not _is_local_host(host))

        if use_remote:
            result = _remote_control(sensor, "stop")
            _debug_log(f"*** REMOTE STOP for {sensor_id}: {result}")
        else:
            _stop_process(sensor_id)
        with _STATE_LOCK:
            _ACTIVE_SENSORS.discard(sensor_id)
            _SENSOR_DATA.pop(sensor_id, None)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@APP.route("/api/debug", methods=["GET"])
def get_debug_log() -> Any:
    with _STATE_LOCK:
        return jsonify({"logs": _DEBUG_LOG})


@APP.route("/api/comports", methods=["GET"])
def list_comports() -> Any:
    if not _SERIAL_AVAILABLE or _list_ports is None:
        return jsonify({"ports": [], "error": "pyserial not installed"})
    results = []
    for port in _list_ports.comports():
        device = port.device or ""
        description = port.description or ""
        hwid = port.hwid or ""
        if device.startswith("/dev/tty") and not device.startswith("/dev/ttyUSB"):
            continue
        if re.match(r"COM\d+", device, re.IGNORECASE):
            desc_lower = description.lower()
            hwid_lower = hwid.lower()
            if not any(kw in desc_lower or kw in hwid_lower for kw in
                       ["silicon labs", "cp210", "ftdi", "usb serial", "usb-serial"]):
                continue
        results.append({"device": device, "description": description or "Unknown device"})
    return jsonify({"ports": results})


@APP.route("/api/profiles", methods=["GET"])
def list_profiles() -> Any:
    with _STATE_LOCK:
        return jsonify(_PROFILES)


@APP.route("/api/profiles", methods=["POST"])
def save_profile() -> Any:
    data = request.get_json(force=True)
    if not data or "name" not in data:
        return jsonify({"error": "Missing name"}), 400
    name = str(data["name"]).strip()
    if not name:
        return jsonify({"error": "Name must not be empty"}), 400
    profile = {k: data[k] for k in _PROFILE_KEYS if k in data}
    with _STATE_LOCK:
        _PROFILES[name] = profile
        _save_profiles()
    return jsonify({"ok": True})


@APP.route("/api/profiles/<path:profile_name>", methods=["DELETE"])
def delete_profile(profile_name: str) -> Any:
    with _STATE_LOCK:
        if profile_name not in _PROFILES:
            return jsonify({"error": "Not found"}), 404
        del _PROFILES[profile_name]
        _save_profiles()
    return jsonify({"ok": True})


def main() -> None:
    _load_config()
    _load_profiles()
    _start_poller()
    APP.run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
