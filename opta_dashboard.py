#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template_string, request

APP = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "opta_dashboard_config.json"
DATA_CACHE_PATH = BASE_DIR / "opta_data.json"
CONTROL_CACHE_PATH = BASE_DIR / "opta_control.json"
CSV_LOG_PATH = BASE_DIR / "opta_json_history.csv"

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "192.168.1.50",
    "port": 80,
    "poll_interval_s": 1.0,
    "dashboard_port": 5051,
}

STATE_LOCK = threading.RLock()
STATE: Dict[str, Any] = {
    "config": dict(DEFAULT_CONFIG),
    "data": {},
    "control": {},
    "last_poll": None,
    "last_error": None,
    "csv_logging": False,
}

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Opta Flow Dashboard</title>
  <style>
    :root {
      --bg: #f4efe6;
      --panel: #fffaf2;
      --ink: #1f2a30;
      --muted: #6b7074;
      --line: #d8c8ab;
      --accent: #1a7f6b;
      --accent-soft: #dff3ed;
      --warn: #9d3d2d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(26,127,107,0.14), transparent 30%),
        linear-gradient(135deg, #f8f1e4, var(--bg));
      color: var(--ink);
    }
    .page {
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px;
    }
    h1, h2 { margin: 0 0 12px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(31, 42, 48, 0.08);
    }
    .hero {
      margin-bottom: 16px;
      padding: 20px;
      border-radius: 20px;
      background: linear-gradient(135deg, rgba(26,127,107,0.12), rgba(255,250,242,0.9));
      border: 1px solid rgba(26,127,107,0.18);
    }
    .meta {
      color: var(--muted);
      font-size: 0.95rem;
    }
    .value {
      font-size: 2.2rem;
      font-weight: 700;
      line-height: 1.1;
    }
    .unit {
      font-size: 0.95rem;
      color: var(--muted);
    }
    .row {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-top: 10px;
      flex-wrap: wrap;
    }
    label {
      display: block;
      font-size: 0.92rem;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input {
      width: 100%;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      background: var(--accent);
      color: #fff;
      cursor: pointer;
      font-weight: 600;
    }
    button.alt {
      background: #d9ece7;
      color: #194d43;
    }
    button.warn {
      background: var(--warn);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
    }
    th, td {
      text-align: left;
      padding: 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      max-height: 300px;
      overflow: auto;
    }
    .pill {
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 600;
    }
    .error {
      color: var(--warn);
      font-weight: 600;
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <h1>Opta Flow Dashboard</h1>
      <div class="meta">Runs independently from the Water Velocity dashboard and mirrors the Opta JSON endpoints into local files on this Ubuntu machine.</div>
      <div class="row">
        <span class="pill" id="poll-state">polling...</span>
        <span class="meta" id="last-poll">last poll: -</span>
        <span class="meta" id="last-error"></span>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <h2>Connection</h2>
        <div class="row">
          <div style="flex:2;min-width:180px;">
            <label for="host">Opta Host</label>
            <input id="host" value="192.168.1.50">
          </div>
          <div style="flex:1;min-width:120px;">
            <label for="port">Port</label>
            <input id="port" type="number" value="80">
          </div>
        </div>
        <div class="row">
          <button onclick="saveConfig()">Save Connection</button>
          <button class="alt" onclick="refreshState()">Refresh Now</button>
        </div>
      </div>

      <div class="card">
        <h2>Control</h2>
        <div class="row">
          <div style="flex:1;min-width:180px;">
            <label for="qsoll">Qsoll</label>
            <input id="qsoll" type="number" min="0" max="200" step="0.1" value="0">
          </div>
        </div>
        <div class="row">
          <button onclick="setRunning(true)">Start</button>
          <button class="warn" onclick="setRunning(false)">Stop</button>
          <button class="alt" onclick="updateQSoll()">Apply Qsoll</button>
        </div>
        <div class="row meta">Current control file: <span id="control-summary">-</span></div>
      </div>

      <div class="card">
        <h2>CSV Logging</h2>
        <div class="row">
          <button onclick="setCsvLogging(true)">Start CSV</button>
          <button class="warn" onclick="setCsvLogging(false)">Stop CSV</button>
        </div>
        <div class="row meta">Status: <span id="csv-state">stopped</span></div>
        <div class="row meta">File: opta_json_history.csv</div>
      </div>
    </div>

    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <h2>Q</h2>
        <div class="value" id="q-flow">-</div>
        <div class="unit">l/s, calculated from input 1 with 4 mA = 0 and 20 mA = 200</div>
      </div>
      <div class="card">
        <h2>h</h2>
        <div class="value" id="h-level">-</div>
        <div class="unit">cm, calculated from input 2 with 4 mA = 50 and 20 mA = 0</div>
      </div>
      <div class="card">
        <h2>K</h2>
        <div class="value" id="k-angle">-</div>
        <div class="unit">deg, exported as 4 mA = 0 deg and 20 mA = 90 deg</div>
        <div class="meta" id="k-ma">-</div>
      </div>
    </div>

    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <h2>Raw mA Inputs</h2>
        <table id="raw-table"><tbody></tbody></table>
      </div>
      <div class="card">
        <h2>Mirrored JSON Files</h2>
        <div class="meta">opta_data.json</div>
        <pre id="data-json">{}</pre>
        <div class="meta">opta_control.json</div>
        <pre id="control-json">{}</pre>
      </div>
    </div>
  </div>

  <script>
    async function api(path, options) {
      const response = await fetch(path, options);
      if (!response.ok) {
        throw new Error(await response.text());
      }
      return response.json();
    }

    function fmt(value, digits = 2) {
      return value == null ? '-' : Number(value).toFixed(digits);
    }

    async function refreshState() {
      const state = await api('/api/state');
      document.getElementById('host').value = state.config.host || '';
      document.getElementById('port').value = state.config.port || 80;
      document.getElementById('qsoll').value = state.control.q_soll_l_s ?? 0;
      document.getElementById('poll-state').textContent = state.last_error ? 'poll error' : 'poll ok';
      document.getElementById('last-poll').textContent = `last poll: ${state.last_poll || '-'}`;
      document.getElementById('last-error').textContent = state.last_error || '';
      document.getElementById('csv-state').textContent = state.csv_logging ? 'running' : 'stopped';
      document.getElementById('q-flow').textContent = fmt(state.data.q_flow_l_s, 2);
      document.getElementById('h-level').textContent = fmt(state.data.h_level_cm, 2);
      document.getElementById('k-angle').textContent = fmt(state.data.k_angle_deg, 2);
      document.getElementById('k-ma').textContent = `K output: ${fmt(state.data.k_output_mA, 3)} mA`;
      document.getElementById('control-summary').textContent = `running=${state.control.running ?? '-'}, q_soll_l_s=${fmt(state.control.q_soll_l_s, 2)}`;
      document.getElementById('data-json').textContent = JSON.stringify(state.data, null, 2);
      document.getElementById('control-json').textContent = JSON.stringify(state.control, null, 2);

      const tbody = document.querySelector('#raw-table tbody');
      tbody.innerHTML = '';
      (state.data.raw_mA || []).forEach((value, index) => {
        const row = document.createElement('tr');
        row.innerHTML = `<td>I${index + 1}</td><td>${fmt(value, 3)} mA</td>`;
        tbody.appendChild(row);
      });
    }

    async function saveConfig() {
      await api('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: document.getElementById('host').value,
          port: Number(document.getElementById('port').value),
        }),
      });
      await refreshState();
    }

    async function setRunning(running) {
      await api('/api/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ running, q_soll_l_s: Number(document.getElementById('qsoll').value) }),
      });
      await refreshState();
    }

    async function updateQSoll() {
      await api('/api/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q_soll_l_s: Number(document.getElementById('qsoll').value) }),
      });
      await refreshState();
    }

    async function setCsvLogging(enabled) {
      await api('/api/logging', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      await refreshState();
    }

    refreshState();
    setInterval(() => refreshState().catch((error) => {
      document.getElementById('last-error').textContent = error.message;
    }), 1500);
  </script>
</body>
</html>
"""


def load_json_file(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        path.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
        return dict(fallback)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(fallback)


def write_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def get_base_url() -> str:
    cfg = STATE["config"]
    return f"http://{cfg['host']}:{int(cfg['port'])}"


def fetch_json(url: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request_obj = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request_obj, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def append_csv_snapshot(data_payload: Dict[str, Any], control_payload: Dict[str, Any]) -> None:
    file_exists = CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "logged_at",
                "running",
                "q_soll_l_s",
                "q_flow_l_s",
                "h_level_cm",
                "k_angle_deg",
                "k_output_mA",
                "data_json",
                "control_json",
            ],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "logged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "running": control_payload.get("running"),
                "q_soll_l_s": control_payload.get("q_soll_l_s"),
                "q_flow_l_s": data_payload.get("q_flow_l_s"),
                "h_level_cm": data_payload.get("h_level_cm"),
                "k_angle_deg": data_payload.get("k_angle_deg"),
                "k_output_mA": data_payload.get("k_output_mA"),
                "data_json": json.dumps(data_payload, sort_keys=True),
                "control_json": json.dumps(control_payload, sort_keys=True),
            }
        )


def poll_opta_once() -> None:
    base_url = get_base_url()
    data_payload = fetch_json(f"{base_url}/data.json")
    control_payload = fetch_json(f"{base_url}/control.json")
    with STATE_LOCK:
        STATE["data"] = data_payload
        STATE["control"] = control_payload
        STATE["last_poll"] = time.strftime("%Y-%m-%d %H:%M:%S")
        STATE["last_error"] = None
        csv_logging = bool(STATE["csv_logging"])
    write_json_file(DATA_CACHE_PATH, data_payload)
    write_json_file(CONTROL_CACHE_PATH, control_payload)
    if csv_logging:
        append_csv_snapshot(data_payload, control_payload)


def poller_loop() -> None:
    while True:
        with STATE_LOCK:
            poll_interval = float(STATE["config"].get("poll_interval_s", 1.0))
        try:
            poll_opta_once()
        except Exception as exc:
            with STATE_LOCK:
                STATE["last_error"] = str(exc)
        time.sleep(max(0.25, poll_interval))


def push_control_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    base_url = get_base_url()
    control_payload = fetch_json(f"{base_url}/control.json", method="POST", payload=payload)
    write_json_file(CONTROL_CACHE_PATH, control_payload)
    with STATE_LOCK:
        merged = dict(STATE.get("control", {}))
        merged.update(control_payload)
        STATE["control"] = merged
    return control_payload


@APP.route("/")
def index() -> str:
    return render_template_string(HTML_TEMPLATE)


@APP.route("/api/state", methods=["GET"])
def api_state() -> Any:
    with STATE_LOCK:
        return jsonify(dict(STATE))


@APP.route("/api/config", methods=["POST"])
def api_config() -> Any:
    payload = request.get_json(force=True, silent=False) or {}
    with STATE_LOCK:
        STATE["config"]["host"] = str(payload.get("host", STATE["config"]["host"]))
        STATE["config"]["port"] = int(payload.get("port", STATE["config"]["port"]))
        write_json_file(CONFIG_PATH, STATE["config"])
    try:
        poll_opta_once()
    except Exception as exc:
        with STATE_LOCK:
            STATE["last_error"] = str(exc)
    return jsonify({"ok": True, "config": STATE["config"]})


@APP.route("/api/control", methods=["GET", "POST"])
def api_control() -> Any:
    if request.method == "GET":
        with STATE_LOCK:
            return jsonify(dict(STATE["control"]))

    payload = request.get_json(force=True, silent=False) or {}
    forwarded: Dict[str, Any] = {}
    if "running" in payload:
        forwarded["running"] = bool(payload["running"])
    if "q_soll_l_s" in payload:
        forwarded["q_soll_l_s"] = max(0.0, min(200.0, float(payload["q_soll_l_s"])))
    control_payload = push_control_update(forwarded)
    try:
        poll_opta_once()
    except Exception as exc:
        with STATE_LOCK:
            STATE["last_error"] = str(exc)
    return jsonify({"ok": True, "control": control_payload})


@APP.route("/api/logging", methods=["POST"])
def api_logging() -> Any:
    payload = request.get_json(force=True, silent=False) or {}
    enabled = bool(payload.get("enabled"))
    with STATE_LOCK:
        STATE["csv_logging"] = enabled
    return jsonify({"ok": True, "csv_logging": enabled})


def bootstrap_state() -> None:
    config = load_json_file(CONFIG_PATH, DEFAULT_CONFIG)
    data_cache = load_json_file(DATA_CACHE_PATH, {})
    control_cache = load_json_file(CONTROL_CACHE_PATH, {"running": True, "q_soll_l_s": 0.0})
    with STATE_LOCK:
        STATE["config"] = config
        STATE["data"] = data_cache
        STATE["control"] = control_cache


def main() -> None:
    bootstrap_state()
    poller = threading.Thread(target=poller_loop, name="opta-poller", daemon=True)
    poller.start()
    dashboard_port = int(STATE["config"].get("dashboard_port", 5051))
    APP.run(host="0.0.0.0", port=dashboard_port, debug=False)


if __name__ == "__main__":
    main()