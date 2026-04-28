#!/usr/bin/env python3
"""
Raspberry Pi Radar Sensor Daemon
==================================
Lightweight headless daemon for Acconeer XE125 radar sensor on Raspberry Pi 3.

Features:
- Continuous radar measurement (velocity or distance mode)
- CSV data logging with automatic rotation
- JSON HTTP API for remote monitoring
- Systemd service integration
- Low resource usage optimized for Pi 3
- Signal-based graceful shutdown

Installation:
    pip install acconeer-exptool scipy requests

Usage:
    python pi_radar_daemon.py --config sensors_rpi.json
    
Configuration:
    See sensors_rpi.json for sensor configuration examples
"""

from __future__ import annotations

import argparse
import csv
import datetime
import http.server
import json
import logging
import os
import signal
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from acconeer.exptool import a121
    from acconeer.exptool.a121.algo.surface_velocity import (
        ExampleApp as VelocityApp,
        ExampleAppConfig as VelocityAppConfig,
    )
    from acconeer.exptool.a121.algo.distance import (
        Detector as DistanceDetector,
        DetectorConfig as DistanceDetectorConfig,
    )
    _SDK_AVAILABLE = True
except ImportError as e:
    _SDK_AVAILABLE = False
    _SDK_ERROR = str(e)


# Configuration constants
DEFAULT_CONFIG_FILE = "sensors_rpi.json"
DEFAULT_LOG_DIR = "./logs"
DEFAULT_LOG_MAX_SIZE = 10 * 1024 * 1024  # 10MB per log file
BAD_SIGNAL_OUTPUT = 42.0

logger = logging.getLogger(__name__)


class JSONAPIHandler(http.server.BaseHTTPRequestHandler):
    """Simple HTTP handler for JSON status API."""

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(payload, default=str).encode("utf-8"))
    
    def do_GET(self) -> None:
        if self.path in ("/", "/status"):
            payload = self.server.daemon.get_labview_payload()
            self._send_json(200, payload)
        elif self.path == "/daemon_status":
            status_data = self.server.daemon.get_status()
            self._send_json(200, status_data)
        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:
        if self.path not in ("/control/start", "/control/stop"):
            self.send_error(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body_text = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        payload: Dict[str, Any] = {}
        if body_text.strip():
            try:
                payload = json.loads(body_text)
            except json.JSONDecodeError:
                self._send_json(400, {"ok": False, "error": "Invalid JSON body"})
                return

        sensor_id = payload.get("sensor_id")

        try:
            if self.path == "/control/start":
                result = self.server.daemon.control_start(sensor_id, payload)
            else:
                result = self.server.daemon.control_stop(sensor_id)
            self._send_json(200, {"ok": True, **result})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})
    
    def log_message(self, format: str, *args: object) -> None:
        # Suppress standard HTTP logging
        pass


class JSONAPIServer(socketserver.ThreadingTCPServer):
    """Thread-safe HTTP server for JSON API."""
    allow_reuse_address = True
    daemon_threads = True
    
    def __init__(
        self, 
        server_address: tuple[str, int],
        handler_class,
        daemon: "RadarDaemon"
    ) -> None:
        self.daemon = daemon
        super().__init__(server_address, handler_class)


class RadarDaemon:
    """Main radar sensor daemon for Raspberry Pi."""
    
    def __init__(self, config_file: str) -> None:
        self.config_file = config_file
        self.config: Dict[str, Any] = {}
        self.running = False
        self.sensors: Dict[str, Dict[str, Any]] = {}
        self.primary_sensor_id: Optional[str] = None
        self.measurement_threads: Dict[str, threading.Thread] = {}
        self.api_server: Optional[JSONAPIServer] = None
        self.api_thread: Optional[threading.Thread] = None
        
        # Signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # Load configuration
        self._load_config()
        self._setup_logging()
        self._initialize_sensors()
    
    def _signal_handler(self, signum: int, frame) -> None:
        """Handle termination signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
    
    def _load_config(self) -> None:
        """Load configuration from JSON file."""
        if not os.path.exists(self.config_file):
            logger.error(f"Config file not found: {self.config_file}")
            raise FileNotFoundError(f"Config file not found: {self.config_file}")
        
        with open(self.config_file, "r") as f:
            self.config = json.load(f)
        
        logger.info(f"Loaded configuration from {self.config_file}")
    
    def _setup_logging(self) -> None:
        """Configure logging."""
        log_dir = self.config.get("log_dir", DEFAULT_LOG_DIR)
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, "radar_daemon.log")
        
        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        
        # Also log to console
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        logger.info("Logging initialized")
    
    def _initialize_sensors(self) -> None:
        """Initialize sensor configurations."""
        sensors_config = self.config.get("sensors", [])
        
        if not sensors_config:
            logger.warning("No sensors configured in config file")
            return
        
        for sensor_cfg in sensors_config:
            sensor_id = sensor_cfg.get("id", "sensor_unknown")
            self.sensors[sensor_id] = {
                "config": sensor_cfg,
                "running": False,
                "stop_requested": False,
                "last_measurement": None,
                "last_payload": {},
                "last_timestamp": None,
                "started_monotonic": None,
                "distance_buffer": [],
                "measurement_count": 0,
                "error_count": 0,
                "client": None,
                "app": None,
                "detector": None,
                "log_file": None,
                "csv_writer": None,
                "log_file_size": 0,
            }
            logger.info(f"Initialized sensor: {sensor_id}")

        if self.sensors and self.primary_sensor_id is None:
            self.primary_sensor_id = next(iter(self.sensors.keys()))
    
    def start(self) -> None:
        """Start the daemon."""
        if self.running:
            logger.warning("Daemon already running")
            return
        
        if not _SDK_AVAILABLE:
            logger.error(f"SDK not available: {_SDK_ERROR}")
            raise ImportError(f"acconeer-exptool not installed: {_SDK_ERROR}")
        
        self.running = True
        logger.info("Starting radar daemon...")
        
        # Start JSON API server if configured
        if self.config.get("enable_json_api", False):
            self._start_api_server()
        
        # Start measurement threads for each sensor
        for sensor_id in self.sensors:
            thread = threading.Thread(
                target=self._measurement_loop,
                args=(sensor_id,),
                name=f"measure-{sensor_id}",
                daemon=False
            )
            thread.start()
            self.measurement_threads[sensor_id] = thread
            logger.info(f"Started measurement thread for {sensor_id}")
        
        # Keep daemon alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")
            self.stop()
    
    def stop(self) -> None:
        """Stop the daemon gracefully."""
        if not self.running:
            return
        
        logger.info("Stopping daemon...")
        self.running = False
        
        # Signal all sensors to stop
        for sensor_id in self.sensors:
            self.sensors[sensor_id]["stop_requested"] = True
        
        # Wait for threads to finish
        for sensor_id, thread in self.measurement_threads.items():
            logger.info(f"Waiting for {sensor_id} thread to finish...")
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning(f"Thread {sensor_id} did not finish gracefully")
        
        # Stop API server
        if self.api_server:
            self.api_server.shutdown()
            self.api_thread.join(timeout=5)
        
        # Close all log files
        for sensor_id, sensor in self.sensors.items():
            if sensor["log_file"]:
                sensor["log_file"].close()
                logger.info(f"Closed log file for {sensor_id}")
        
        logger.info("Daemon stopped")
        sys.exit(0)
    
    def _start_api_server(self) -> None:
        """Start JSON API server."""
        port = self.config.get("json_api_port", 8080)
        try:
            self.api_server = JSONAPIServer(
                ("0.0.0.0", port),
                JSONAPIHandler,
                self
            )
            self.api_thread = threading.Thread(
                target=self.api_server.serve_forever,
                name="api-server",
                daemon=True
            )
            self.api_thread.start()
            logger.info(f"JSON API server started on port {port}")
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")

    def _resolve_sensor_id(self, sensor_id: Optional[str]) -> str:
        if sensor_id is not None:
            sid = str(sensor_id)
            if sid not in self.sensors:
                raise KeyError(f"Unknown sensor_id: {sid}")
            return sid

        if len(self.sensors) == 1:
            return next(iter(self.sensors.keys()))

        raise ValueError("sensor_id is required when multiple sensors are configured")

    def _apply_runtime_config(self, sensor: Dict[str, Any], request_payload: Dict[str, Any]) -> None:
        """Apply optional runtime configuration from remote control payload."""
        cfg = sensor["config"]

        mode = request_payload.get("mode")
        if isinstance(mode, str) and mode in ("velocity", "distance"):
            cfg["mode"] = mode

        # Flat payload keys from dashboard for velocity mode.
        velocity_keys = [
            "surface_distance", "angle", "hwaas", "sweeps", "time_series",
            "lp_coeff", "cfar_sensitivity", "max_peak_interval", "slow_zone",
        ]
        if any(k in request_payload for k in velocity_keys):
            velocity_cfg = dict(cfg.get("velocity_config", {}))
            for key in velocity_keys:
                if key in request_payload:
                    velocity_cfg[key] = request_payload[key]
            cfg["velocity_config"] = velocity_cfg

        # Flat payload keys from dashboard for distance mode.
        distance_keys = [
            "start", "end", "update_rate", "signal_quality",
            "threshold_sensitivity", "min_strength", "avg_window",
        ]
        if any(k in request_payload for k in distance_keys):
            distance_cfg = dict(cfg.get("distance_config", {}))
            for key in distance_keys:
                if key in request_payload:
                    distance_cfg[key] = request_payload[key]
            cfg["distance_config"] = distance_cfg

    def control_start(self, sensor_id: Optional[str] = None, request_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        sid = self._resolve_sensor_id(sensor_id)
        sensor = self.sensors[sid]
        self.primary_sensor_id = sid

        restart_required = False
        if request_payload:
            requested_mode = request_payload.get("mode")
            if isinstance(requested_mode, str) and requested_mode in ("velocity", "distance"):
                current_mode = str(sensor["config"].get("mode", "velocity"))
                restart_required = requested_mode != current_mode

        if request_payload:
            self._apply_runtime_config(sensor, request_payload)

        existing = self.measurement_threads.get(sid)
        if existing is not None and existing.is_alive():
            if not restart_required:
                return {"sensor_id": sid, "message": "already running", "mode": sensor["config"].get("mode")}

            logger.info(f"Restarting {sid} to apply new mode/config")
            sensor["stop_requested"] = True
            try:
                # Force-close current app/detector/client to unblock get_next().
                self._disconnect_sensor(sid)
            except Exception as exc:
                logger.warning(f"Disconnect during restart for {sid} raised: {exc}")
            existing.join(timeout=5)
            if existing.is_alive():
                raise RuntimeError(f"Could not stop existing measurement thread for {sid}")

        sensor["stop_requested"] = False
        sensor["started_monotonic"] = time.monotonic()
        sensor["distance_buffer"] = []
        thread = threading.Thread(
            target=self._measurement_loop,
            args=(sid,),
            name=f"measure-{sid}",
            daemon=False,
        )
        thread.start()
        self.measurement_threads[sid] = thread
        logger.info(f"Control start requested for {sid}")
        return {
            "sensor_id": sid,
            "message": "restarted" if restart_required else "started",
            "mode": sensor["config"].get("mode"),
        }

    def control_stop(self, sensor_id: Optional[str] = None) -> Dict[str, Any]:
        sid = self._resolve_sensor_id(sensor_id)
        sensor = self.sensors[sid]
        sensor["stop_requested"] = True

        thread = self.measurement_threads.get(sid)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

        if self.primary_sensor_id == sid:
            running_ids = [k for k, s in self.sensors.items() if s.get("running")]
            self.primary_sensor_id = running_ids[0] if running_ids else sid

        logger.info(f"Control stop requested for {sid}")
        return {"sensor_id": sid, "message": "stopped"}
    
    def _measurement_loop(self, sensor_id: str) -> None:
        """Main measurement loop for a sensor."""
        sensor = self.sensors[sensor_id]
        cfg = sensor["config"]
        
        try:
            logger.info(f"Starting measurement loop for {sensor_id}")
            
            # Establish connection
            self._connect_sensor(sensor_id)
            
            # Create mode-specific app or detector
            self._setup_measurement_mode(sensor_id)
            sensor["running"] = True
            if sensor["started_monotonic"] is None:
                sensor["started_monotonic"] = time.monotonic()
            
            # Main measurement loop
            while self.running and not sensor["stop_requested"]:
                try:
                    self._take_measurement(sensor_id)
                    time.sleep(1.0 / cfg.get("output_rate", 2.0))
                except Exception as e:
                    sensor["error_count"] += 1
                    logger.error(f"Error in measurement loop for {sensor_id}: {e}")
                    if sensor["error_count"] > 10:
                        logger.error(f"Too many errors for {sensor_id}, stopping")
                        break
                    time.sleep(1)
        
        except Exception as e:
            logger.error(f"Fatal error in measurement loop for {sensor_id}: {e}")
        
        finally:
            sensor["running"] = False
            self._disconnect_sensor(sensor_id)
            logger.info(f"Stopped measurement loop for {sensor_id}")
    
    def _connect_sensor(self, sensor_id: str) -> None:
        """Establish connection to sensor."""
        sensor = self.sensors[sensor_id]
        cfg = sensor["config"]
        
        connection_type = cfg.get("connection_type", "serial")
        
        try:
            if connection_type == "serial":
                port = cfg.get("serial_port")
                self._connect_serial(sensor, port)
            elif connection_type == "network":
                host = cfg.get("host", "localhost")
                self._connect_network(sensor, host)
            else:
                raise ValueError(f"Unknown connection type: {connection_type}")
            
            logger.info(f"Connected to {sensor_id} via {connection_type}")
        except Exception as e:
            logger.error(f"Failed to connect {sensor_id}: {e}")
            raise
    
    def _connect_serial(self, sensor: Dict[str, Any], port: str) -> None:
        """Connect via serial port."""
        sensor_id = sensor["config"].get("id", "unknown")
        client = a121.Client.open(serial_port=port)
        sensor["client"] = client
    
    def _connect_network(self, sensor: Dict[str, Any], host: str) -> None:
        """Connect via network."""
        sensor_id = sensor["config"].get("id", "unknown")
        client = a121.Client.open(ip_address=host)
        sensor["client"] = client
    
    def _setup_measurement_mode(self, sensor_id: str) -> None:
        """Setup measurement mode (velocity or distance)."""
        sensor = self.sensors[sensor_id]
        cfg = sensor["config"]
        mode = cfg.get("mode", "distance")
        client = sensor["client"]
        
        try:
            if mode == "velocity":
                self._setup_velocity_mode(sensor)
            elif mode == "distance":
                self._setup_distance_mode(sensor)
            else:
                raise ValueError(f"Unknown mode: {mode}")
            
            logger.info(f"Setup {mode} mode for {sensor_id}")
        except Exception as e:
            logger.error(f"Failed to setup {mode} mode for {sensor_id}: {e}")
            raise
    
    def _setup_velocity_mode(self, sensor: Dict[str, Any]) -> None:
        """Setup surface velocity measurement mode."""
        cfg = sensor["config"]
        client = sensor["client"]
        
        # Get velocity configuration
        velocity_cfg = cfg.get("velocity_config", {})
        
        # Create velocity app config
        app_config = VelocityAppConfig(
            surface_distance=velocity_cfg.get("surface_distance", 0.25),
            sensor_angle=velocity_cfg.get("angle", 45.0),
            num_points=velocity_cfg.get("num_points", 4),
            sweeps_per_frame=velocity_cfg.get("sweeps", 128),
            frame_rate=velocity_cfg.get("frame_rate", None),
            hwaas=velocity_cfg.get("hwaas", 16),
            time_series_length=velocity_cfg.get("time_series", 512),
            velocity_lp_coeff=velocity_cfg.get("lp_coeff", 0.75),
            cfar_sensitivity=velocity_cfg.get("cfar_sensitivity", 0.5),
            max_peak_interval_s=velocity_cfg.get("max_peak_interval", 1.0),
            slow_zone=velocity_cfg.get("slow_zone", 3),
        )
        
        sensor_id = int(cfg.get("sensor_id", 1))
        app = VelocityApp(
            client=client,
            sensor_id=sensor_id,
            example_app_config=app_config,
        )
        app.start()
        sensor["app"] = app
    
    def _setup_distance_mode(self, sensor: Dict[str, Any]) -> None:
        """Setup distance measurement mode."""
        cfg = sensor["config"]
        client = sensor["client"]
        
        # Get distance configuration
        distance_cfg = cfg.get("distance_config", {})
        
        # Create distance detector config
        detector_config = DistanceDetectorConfig(
            start_m=distance_cfg.get("start", 0.25),
            end_m=distance_cfg.get("end", 3.0),
            update_rate=distance_cfg.get("update_rate", cfg.get("output_rate", 2.0)),
            signal_quality=distance_cfg.get("signal_quality", 25.0),
            threshold_sensitivity=distance_cfg.get("threshold_sensitivity", 0.35),
        )
        
        sensor_id = int(cfg.get("sensor_id", 1))
        detector = DistanceDetector(
            client=client,
            sensor_ids=[sensor_id],
            detector_config=detector_config,
        )
        detector.calibrate_detector()
        detector.start()
        sensor["detector"] = detector
    
    def _take_measurement(self, sensor_id: str) -> None:
        """Take a single measurement."""
        sensor = self.sensors[sensor_id]
        cfg = sensor["config"]
        mode = cfg.get("mode", "distance")
        
        measurement_value = None
        payload: Dict[str, Any] = {}
        now_ts = time.time()
        started_monotonic = sensor.get("started_monotonic")
        elapsed = 0.0
        if started_monotonic is not None:
            elapsed = max(0.0, time.monotonic() - float(started_monotonic))
        
        try:
            if mode == "velocity" and sensor["app"]:
                app = sensor["app"]
                result = app.get_next()
                if result is not None:
                    velocity = getattr(result, "velocity", None)
                    distance = getattr(result, "distance_m", None)
                    velocity_out = float(velocity) if velocity is not None else BAD_SIGNAL_OUTPUT
                    distance_out = float(distance) if distance is not None else BAD_SIGNAL_OUTPUT
                    measurement_value = velocity_out
                    velocity_cfg = cfg.get("velocity_config", {})
                    payload = {
                        "mode": "velocity",
                        "timestamp": now_ts,
                        "elapsed_s": elapsed,
                        "velocity_m_s": velocity_out,
                        "distance_m": distance_out,
                        "surface_distance_m": float(velocity_cfg.get("surface_distance", 0.25)),
                        "angle_deg": float(velocity_cfg.get("angle", 45.0)),
                    }
            
            elif mode == "distance" and sensor["detector"]:
                detector = sensor["detector"]
                sensor_index = int(cfg.get("sensor_id", 1))
                results = detector.get_next()
                result = results.get(sensor_index)
                distance_cfg = cfg.get("distance_config", {})
                if result is not None and result.distances is not None and len(result.distances) > 0:
                    strengths = result.strengths
                    min_strength = distance_cfg.get("min_strength", 5.0)
                    best_dist = None
                    best_str = -float("inf")
                    for dist_m, strength in zip(result.distances, strengths):
                        if strength >= min_strength and strength > best_str:
                            best_dist = dist_m
                            best_str = strength
                    if best_dist is not None:
                        measurement_value = float(best_dist)
                        sensor["distance_buffer"].append(float(best_dist))
                        avg_window = int(distance_cfg.get("avg_window", 5))
                        if avg_window > 0 and len(sensor["distance_buffer"]) > avg_window:
                            sensor["distance_buffer"] = sensor["distance_buffer"][-avg_window:]

                    avg_distance = BAD_SIGNAL_OUTPUT
                    if sensor["distance_buffer"]:
                        avg_distance = float(sum(sensor["distance_buffer"]) / len(sensor["distance_buffer"]))

                    payload = {
                        "mode": "distance",
                        "timestamp": now_ts,
                        "elapsed_s": elapsed,
                        "distance_m": float(best_dist) if best_dist is not None else BAD_SIGNAL_OUTPUT,
                        "avg_distance_m": avg_distance,
                        "strength_db": float(best_str) if best_dist is not None else BAD_SIGNAL_OUTPUT,
                        "start_m": float(distance_cfg.get("start", 0.25)),
                        "end_m": float(distance_cfg.get("end", 3.0)),
                        "update_rate_hz": float(distance_cfg.get("update_rate", cfg.get("output_rate", 2.0))),
                    }
            
            if measurement_value is not None:
                sensor["last_measurement"] = measurement_value
                sensor["last_payload"] = payload
                sensor["last_timestamp"] = now_ts
                sensor["measurement_count"] += 1
                sensor["error_count"] = 0  # Reset error counter on success
                
                # Log to CSV
                self._log_measurement(sensor_id, measurement_value)
        
        except Exception as e:
            logger.warning(f"Measurement error for {sensor_id}: {e}")
            raise
    
    def _log_measurement(self, sensor_id: str, value: float) -> None:
        """Log measurement to CSV file."""
        sensor = self.sensors[sensor_id]
        cfg = sensor["config"]
        global_logging_enabled = bool(self.config.get("enable_logging", True))
        sensor_logging_enabled = cfg.get("enable_logging", None)
        logging_enabled = global_logging_enabled and bool(sensor_logging_enabled if sensor_logging_enabled is not None else True)

        # Close open file immediately if logging was disabled in config.
        if not logging_enabled:
            if sensor["log_file"]:
                sensor["log_file"].close()
                sensor["log_file"] = None
                sensor["csv_writer"] = None
                logger.info(f"CSV logging disabled for {sensor_id}")
            return
        
        # Open or rotate log file
        if sensor["log_file"] is None:
            self._open_log_file(sensor_id)
        
        # Check if file needs rotation
        current_size = os.path.getsize(sensor["log_file"].name)
        max_size = cfg.get("log_max_size", DEFAULT_LOG_MAX_SIZE)
        
        if current_size > max_size:
            logger.info(f"Rotating log file for {sensor_id}")
            self._rotate_log_file(sensor_id)
        
        # Write measurement
        timestamp = datetime.datetime.now().isoformat()
        sensor["csv_writer"].writerow({
            "timestamp": timestamp,
            "value": value,
            "measurement_count": sensor["measurement_count"],
        })
        sensor["log_file"].flush()
    
    def _open_log_file(self, sensor_id: str) -> None:
        """Open log file for sensor."""
        sensor = self.sensors[sensor_id]
        cfg = sensor["config"]

        log_dir = cfg.get("log_dir", self.config.get("log_dir", DEFAULT_LOG_DIR))
        os.makedirs(log_dir, exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        mode = cfg.get("mode", "distance")
        filename = f"{sensor_id}_{mode}_{timestamp}.csv"
        filepath = os.path.join(log_dir, filename)
        
        # Open file
        log_file = open(filepath, "w", newline="", buffering=1)
        sensor["log_file"] = log_file
        
        # Create CSV writer with header
        csv_writer = csv.DictWriter(
            log_file,
            fieldnames=["timestamp", "value", "measurement_count"]
        )
        csv_writer.writeheader()
        sensor["csv_writer"] = csv_writer
        
        logger.info(f"Opened log file for {sensor_id}: {filepath}")
    
    def _rotate_log_file(self, sensor_id: str) -> None:
        """Rotate log file when size limit reached."""
        sensor = self.sensors[sensor_id]
        
        if sensor["log_file"]:
            sensor["log_file"].close()
        
        self._open_log_file(sensor_id)
    
    def _disconnect_sensor(self, sensor_id: str) -> None:
        """Disconnect from sensor."""
        sensor = self.sensors[sensor_id]
        
        try:
            if sensor["app"]:
                sensor["app"].stop()
                logger.info(f"Stopped velocity app for {sensor_id}")
        except Exception as e:
            logger.error(f"Error stopping velocity app for {sensor_id}: {e}")

        try:
            if sensor["detector"]:
                sensor["detector"].stop()
                logger.info(f"Stopped distance detector for {sensor_id}")
        except Exception as e:
            logger.error(f"Error stopping distance detector for {sensor_id}: {e}")

        try:
            if sensor["client"]:
                sensor["client"].close()
                logger.info(f"Closed client for {sensor_id}")
        except Exception as e:
            logger.error(f"Error closing client for {sensor_id}: {e}")
        
        if sensor["log_file"]:
            try:
                sensor["log_file"].close()
            except Exception as e:
                logger.error(f"Error closing log file for {sensor_id}: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current daemon status as JSON."""
        sensors_status = {}
        
        for sensor_id, sensor in self.sensors.items():
            cfg = sensor["config"]
            sensors_status[sensor_id] = {
                "running": sensor["running"],
                "mode": cfg.get("mode", "unknown"),
                "last_measurement": sensor["last_measurement"],
                "measurement_count": sensor["measurement_count"],
                "error_count": sensor["error_count"],
                "connected": sensor["client"] is not None,
                **(sensor.get("last_payload") or {}),
            }

        status: Dict[str, Any] = {
            "timestamp": time.time(),
            "daemon_timestamp": datetime.datetime.now().isoformat(),
            "daemon_running": self.running,
            "sensors": sensors_status,
        }

        # Compatibility: expose first sensor payload at top-level so LabVIEW VI
        # can parse this daemon with the same schema as the Linux program output.
        if sensors_status:
            first_sensor = next(iter(sensors_status.values()))
            for key in [
                "mode",
                "timestamp",
                "elapsed_s",
                "velocity_m_s",
                "distance_m",
                "avg_distance_m",
                "strength_db",
                "surface_distance_m",
                "angle_deg",
                "start_m",
                "end_m",
                "update_rate_hz",
            ]:
                if key in first_sensor:
                    status[key] = first_sensor[key]

        return status

    def get_labview_payload(self) -> Dict[str, Any]:
        """Return strict Linux-compatible netvar payload with stable keys.

        The payload always exposes the same top-level fields so one LabVIEW VI
        can parse both Linux and Pi sources without conditional key checks.
        """
        now_ts = time.time()

        # Use explicitly selected/controlled sensor first.
        first_sensor: Optional[Dict[str, Any]] = None
        selected_id: Optional[str] = self.primary_sensor_id
        if selected_id and selected_id in self.sensors:
            first_sensor = self.sensors[selected_id]
        elif self.sensors:
            selected_id = next(iter(self.sensors.keys()))
            first_sensor = self.sensors[selected_id]

        cfg = first_sensor.get("config", {}) if first_sensor else {}
        mode = str(cfg.get("mode", "velocity"))
        velocity_cfg = cfg.get("velocity_config", {})
        distance_cfg = cfg.get("distance_config", {})
        last_payload = first_sensor.get("last_payload", {}) if first_sensor else {}

        payload: Dict[str, Any] = {
            "sensor_id": selected_id,
            "mode": mode,
            "timestamp": float(last_payload.get("timestamp", now_ts)),
            "elapsed_s": float(last_payload.get("elapsed_s", 0.0)),
            "velocity_m_s": float(last_payload.get("velocity_m_s", BAD_SIGNAL_OUTPUT)),
            "distance_m": float(last_payload.get("distance_m", BAD_SIGNAL_OUTPUT)),
            "avg_distance_m": float(last_payload.get("avg_distance_m", BAD_SIGNAL_OUTPUT)),
            "strength_db": float(last_payload.get("strength_db", BAD_SIGNAL_OUTPUT)),
            "surface_distance_m": float(last_payload.get("surface_distance_m", velocity_cfg.get("surface_distance", 0.25))),
            "angle_deg": float(last_payload.get("angle_deg", velocity_cfg.get("angle", 45.0))),
            "start_m": float(last_payload.get("start_m", distance_cfg.get("start", 0.25))),
            "end_m": float(last_payload.get("end_m", distance_cfg.get("end", 3.0))),
            "update_rate_hz": float(last_payload.get("update_rate_hz", distance_cfg.get("update_rate", cfg.get("output_rate", 2.0)))),
        }

        return payload


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Raspberry Pi Radar Sensor Daemon"
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help=f"Configuration file (default: {DEFAULT_CONFIG_FILE})"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )
    
    args = parser.parse_args()
    
    try:
        daemon = RadarDaemon(args.config)
        daemon.start()
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
