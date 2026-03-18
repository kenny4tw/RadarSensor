#!/usr/bin/env python3
"""
Water Surface Velocity & Distance Measurement using Acconeer XE125 Radar
========================================================================
Uses the Acconeer Exploration Tool SDK (acconeer-exptool) v7+ with the
A121 Sparse IQ service.

Two modes:
  velocity  – measure water surface velocity (Doppler-based)
  distance  – measure distance to the water surface

Installation:
    pip install acconeer-exptool scipy

Usage examples:
    python surface_velocity.py velocity                        # auto-detect USB
    python surface_velocity.py velocity --port COM3            # Windows serial
    python surface_velocity.py velocity --log MyVelocity.csv   # custom log file
    python surface_velocity.py distance --port COM3            # distance mode
    python surface_velocity.py distance --log MyDistance.csv    # custom log file
"""

from __future__ import annotations

import argparse
import csv
import datetime
import signal
import sys
import time
from typing import Optional

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
except ImportError:
    _SDK_AVAILABLE = False


# ── CLI ───────────────────────────────────────────────────────────────────────

def _add_connection_args(p: argparse.ArgumentParser) -> None:
    conn = p.add_mutually_exclusive_group()
    conn.add_argument(
        "--port", metavar="PORT",
        help="Serial / USB-CDC port, e.g. COM3 (Windows) or /dev/ttyUSB0 (Linux).",
    )
    conn.add_argument(
        "--ip", metavar="ADDR",
        help="IP address for TCP/IP connection to XC112 / XE125 exploration server.",
    )
    p.add_argument("--sensor-id", type=int, default=1,
                   help="Sensor ID on the module (usually 1).")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Measure water surface velocity or distance with Acconeer XE125.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── velocity subcommand ──────────────────────────────────────────────
    vel = sub.add_parser("velocity", help="Measure water surface velocity.",
                         formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    _add_connection_args(vel)
    vel.add_argument("--surface-distance", type=float, default=1.0,
                     help="Perpendicular distance from sensor to water surface [m].")
    vel.add_argument("--num-points", type=int, default=4,
                     help="Number of range points inside the measurement window.")
    vel.add_argument("--sweeps", type=int, default=128,
                     help="Sweeps per frame.  More sweeps → better velocity resolution.")
    vel.add_argument("--frame-rate", type=float, default=None,
                     help="Output frame rate [Hz]. Do NOT set this — velocity mode "
                          "uses continuous sweep mode which determines it automatically.")
    vel.add_argument("--angle", type=float, default=45.0,
                     help="Sensor angle from vertical (straight down = 0°). "
                          "45° is typical for open-channel flow gauging.")
    vel.add_argument("--hwaas", type=int, default=16,
                     help="Hardware accelerated averaging (HWAAS).")
    vel.add_argument("--time-series", type=int, default=512,
                     help="Length of the velocity time series.")
    vel.add_argument("--lp-coeff", type=float, default=0.75,
                     help="Low-pass filter coefficient for velocity output [0–1]. "
                          "Lower = faster response to direction changes.")
    vel.add_argument("--cfar-sensitivity", type=float, default=0.5,
                     help="CFAR detection sensitivity [0–1].")
    vel.add_argument("--max-peak-interval", type=float, default=1.0,
                     help="Seconds without a peak before velocity resets.")
    vel.add_argument("--slow-zone", type=int, default=3,
                     help="Half-width (FFT bins) of dead zone around 0 m/s.")
    vel.add_argument("--log", metavar="FILE", default="WaterVelocity.csv",
                     help="CSV output file for velocity measurements.")

    # ── distance subcommand ──────────────────────────────────────────────
    dst = sub.add_parser("distance", help="Measure distance to water surface.",
                         formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    _add_connection_args(dst)
    dst.add_argument("--start", type=float, default=0.25,
                     help="Measurement range start [m].")
    dst.add_argument("--end", type=float, default=3.0,
                     help="Measurement range end [m].")
    dst.add_argument("--update-rate", type=float, default=10.0,
                     help="Measurement update rate [Hz].")
    dst.add_argument("--signal-quality", type=float, default=25.0,
                     help="Signal quality [dB]. Higher = more HW averaging → "
                          "less noise but slower update. 15 is default SDK, "
                          "25 gives noticeably steadier readings.")
    dst.add_argument("--threshold-sensitivity", type=float, default=0.35,
                     help="Detection threshold sensitivity [0\u20131]. "
                          "Lower = stricter, rejects weak reflections.")
    dst.add_argument("--min-strength", type=float, default=5.0,
                     help="Minimum peak strength [dB] to accept a detection. "
                          "Readings below this are discarded.")
    dst.add_argument("--avg-window", type=int, default=5,
                     help="Moving-average window size. "
                          "Smooths distance output over N frames (1 = no smoothing).")
    dst.add_argument("--log", metavar="FILE", default="distance.csv",
                     help="CSV output file for distance measurements.")

    return p


# ── Helpers ──────────────────────────────────────────────────────────────────

def _open_client(args: argparse.Namespace) -> "a121.Client":
    if args.ip:
        print(f"[XE125] Connecting via TCP  → {args.ip}")
        return a121.Client.open(ip_address=args.ip)
    if args.port:
        print(f"[XE125] Connecting via UART → {args.port}")
        return a121.Client.open(serial_port=args.port)
    print("[XE125] Auto-detecting USB/UART connection …")
    return a121.Client.open()


def _write_timestamp_fields(dt: datetime.datetime) -> list:
    return [dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
            dt.microsecond // 1000]


TIMESTAMP_HEADER = ["year", "month", "day", "hours", "minutes", "seconds", "milliseconds"]


# ── Velocity measurement ─────────────────────────────────────────────────────

def run_velocity(args: argparse.Namespace) -> None:
    client = _open_client(args)
    app_config = VelocityAppConfig(
        surface_distance=args.surface_distance,
        sensor_angle=args.angle,
        num_points=args.num_points,
        sweeps_per_frame=args.sweeps,
        frame_rate=args.frame_rate,
        hwaas=args.hwaas,
        time_series_length=args.time_series,
        velocity_lp_coeff=args.lp_coeff,
        cfar_sensitivity=args.cfar_sensitivity,
        max_peak_interval_s=args.max_peak_interval,
        slow_zone=args.slow_zone,
    )

    app = VelocityApp(
        client=client,
        sensor_id=args.sensor_id,
        example_app_config=app_config,
    )

    log_fh: Optional[object] = None
    writer: Optional[csv.writer] = None

    try:
        app.start()

        if args.log:
            log_fh = open(args.log, "a", newline="", encoding="utf-8")
            writer = csv.writer(log_fh, delimiter=";")
            if log_fh.tell() == 0:
                writer.writerow(TIMESTAMP_HEADER + ["elapsed_s", "velocity_m_s", "distance_m"])

        print()
        print(f"  XE125 session active — VELOCITY mode")
        print(f"  Surface distance   : {args.surface_distance:.2f} m")
        print(f"  Sensor angle       : {args.angle:.1f}° from vertical")
        print(f"  Sweeps/frame       : {args.sweeps}  |  HWAAS: {args.hwaas}")
        print(f"  LP coeff           : {args.lp_coeff}  |  CFAR sensitivity: {args.cfar_sensitivity}")
        print(f"  Max peak interval  : {args.max_peak_interval:.1f}s  |  Slow zone: ±{args.slow_zone} bins")
        if args.frame_rate:
            print(f"  Frame rate         : {args.frame_rate} Hz")
        if args.log:
            print(f"  Logging to         : {args.log}")
        print()
        print("  Press Ctrl-C to stop.")
        print()
        print(f"{'Elapsed':>9}  {'Velocity (m/s)':>16}  {'Distance (m)':>14}")
        print("─" * 46)

        running = True
        start_t = time.monotonic()

        def _stop(sig, frame):  # noqa: ANN001
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, _stop)

        while running:
            result = app.get_next()
            elapsed = time.monotonic() - start_t
            timestamp = time.time()

            velocity: Optional[float] = result.velocity
            distance: Optional[float] = result.distance_m

            if velocity is not None:
                dist_str = f"{distance:.3f}" if distance is not None else "  n/a "
                print(f"  {elapsed:>7.1f}s  {velocity:>+14.4f}  {dist_str:>14}")
                if writer is not None:
                    dt = datetime.datetime.fromtimestamp(timestamp)
                    writer.writerow(
                        _write_timestamp_fields(dt) + [
                            f"{elapsed:.3f}",
                            f"{velocity:.6f}",
                            f"{distance:.4f}" if distance is not None else "",
                        ])
                    log_fh.flush()  # type: ignore[union-attr]
            else:
                print(f"  {elapsed:>7.1f}s  {'(no detection)':>16}")

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        raise
    finally:
        try:
            app.stop()
        except Exception:
            pass
        client.close()
        if log_fh is not None:
            log_fh.close()  # type: ignore[union-attr]
        print("\n[XE125] Session closed.")


# ── Distance measurement ─────────────────────────────────────────────────────

def run_distance(args: argparse.Namespace) -> None:
    client = _open_client(args)

    detector_config = DistanceDetectorConfig(
        start_m=args.start,
        end_m=args.end,
        update_rate=args.update_rate,
        signal_quality=args.signal_quality,
        threshold_sensitivity=args.threshold_sensitivity,
    )

    detector = DistanceDetector(
        client=client,
        sensor_ids=[args.sensor_id],
        detector_config=detector_config,
    )

    log_fh: Optional[object] = None
    writer: Optional[csv.writer] = None

    try:
        print("[XE125] Calibrating distance detector …")
        detector.calibrate_detector()
        detector.start()

        if args.log:
            log_fh = open(args.log, "a", newline="", encoding="utf-8")
            writer = csv.writer(log_fh, delimiter=";")
            if log_fh.tell() == 0:
                writer.writerow(TIMESTAMP_HEADER + ["elapsed_s", "distance_m", "strength"])

        print()
        print(f"  XE125 session active — DISTANCE mode")
        print(f"  Range              : {args.start:.2f} – {args.end:.2f} m")
        print(f"  Update rate        : {args.update_rate} Hz")
        print(f"  Signal quality     : {args.signal_quality} dB")
        print(f"  Threshold sens.    : {args.threshold_sensitivity}")
        print(f"  Min strength       : {args.min_strength} dB")
        print(f"  Averaging window   : {args.avg_window} frames")
        if args.log:
            print(f"  Logging to         : {args.log}")
        print()
        print("  Press Ctrl-C to stop.")
        print()
        print(f"{'Elapsed':>9}  {'Distance (m)':>14}  {'Avg dist (m)':>14}  {'Strength':>10}")
        print("─" * 55)

        running = True
        start_t = time.monotonic()
        dist_buffer: list[float] = []

        def _stop(sig, frame):  # noqa: ANN001
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, _stop)

        while running:
            results = detector.get_next()
            elapsed = time.monotonic() - start_t
            timestamp = time.time()

            result = results[args.sensor_id]
            distances = result.distances
            strengths = result.strengths

            if distances is not None and len(distances) > 0:
                # Pick the strongest detection that passes the minimum strength filter
                best_dist = None
                best_str = -float("inf")
                for dist_m, strength in zip(distances, strengths):
                    if strength >= args.min_strength and strength > best_str:
                        best_dist = dist_m
                        best_str = strength

                if best_dist is not None:
                    dist_buffer.append(best_dist)
                    if len(dist_buffer) > args.avg_window:
                        dist_buffer.pop(0)
                    avg_dist = sum(dist_buffer) / len(dist_buffer)

                    print(f"  {elapsed:>7.1f}s  {best_dist:>14.4f}  {avg_dist:>14.4f}  {best_str:>10.2f}")
                    if writer is not None:
                        dt = datetime.datetime.fromtimestamp(timestamp)
                        writer.writerow(
                            _write_timestamp_fields(dt) + [
                                f"{elapsed:.3f}",
                                f"{avg_dist:.4f}",
                                f"{best_str:.2f}",
                            ])
                        log_fh.flush()  # type: ignore[union-attr]
                else:
                    print(f"  {elapsed:>7.1f}s  {'(below min strength)':>14}")
            else:
                print(f"  {elapsed:>7.1f}s  {'(no detection)':>14}")

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        raise
    finally:
        try:
            detector.stop()
        except Exception:
            pass
        client.close()
        if log_fh is not None:
            log_fh.close()  # type: ignore[union-attr]
        print("\n[XE125] Session closed.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not _SDK_AVAILABLE:
        print(
            "ERROR: acconeer-exptool is not installed.\n"
            "Install it with:\n"
            "    pip install acconeer-exptool scipy",
            file=sys.stderr,
        )
        sys.exit(1)

    args = _build_parser().parse_args()

    if args.command == "velocity":
        if not (0 < args.angle < 90):
            print("ERROR: --angle must be between 0° and 90° (exclusive).", file=sys.stderr)
            sys.exit(1)
        if not (0 < args.surface_distance):
            print("ERROR: --surface-distance must be positive.", file=sys.stderr)
            sys.exit(1)
        if args.frame_rate is not None:
            print("ERROR: --frame-rate cannot be used with velocity mode "
                  "(continuous sweep mode sets it automatically). "
                  "Remove the --frame-rate parameter.", file=sys.stderr)
            sys.exit(1)
        run_velocity(args)

    elif args.command == "distance":
        if args.start >= args.end:
            print("ERROR: --start must be less than --end.", file=sys.stderr)
            sys.exit(1)
        run_distance(args)


if __name__ == "__main__":
    main()
