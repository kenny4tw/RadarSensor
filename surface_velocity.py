#!/usr/bin/env python3
"""
Water Surface Velocity Measurement using Acconeer XE125 Radar
=============================================================
Uses the Acconeer Exploration Tool SDK (acconeer-exptool) with the
A121 Sparse IQ service and the built-in surface velocity algorithm.

The XE125 is mounted at an angle above the water surface.  Doppler
processing of the reflected signal yields the line-of-sight velocity
component, which the processor converts to true surface velocity using
the configured radar tilt angle.

Installation:
    pip install acconeer-exptool

Usage examples:
    python surface_velocity.py                        # auto-detect USB
    python surface_velocity.py --port COM3            # Windows serial
    python surface_velocity.py --port /dev/ttyUSB0    # Linux serial
    python surface_velocity.py --ip 192.168.1.100     # TCP/IP
    python surface_velocity.py --log results.csv      # log to file
"""

from __future__ import annotations

import argparse
import csv
import signal
import sys
import time
from typing import Optional

try:
    from acconeer.exptool import a121
    from acconeer.exptool.a121.algo.surface_velocity import (
        Processor,
        ProcessorConfig,
        ProcessorContext,
    )
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False


# ── Acconeer XE125 / A121 physical constants ────────────────────────────────
RADAR_CENTER_FREQ_HZ: float = 60.5e9      # XE125 carrier frequency
SPEED_OF_LIGHT_M_S: float = 2.998e8
WAVELENGTH_M: float = SPEED_OF_LIGHT_M_S / RADAR_CENTER_FREQ_HZ  # ≈ 4.96 mm

# A121 point spacing (Profile 1, free-space: 1 point = 2.5 mm)
METERS_PER_POINT: float = 2.5e-3


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Measure water surface velocity with Acconeer XE125.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    conn = p.add_mutually_exclusive_group()
    conn.add_argument(
        "--port", metavar="PORT",
        help="Serial / USB-CDC port, e.g. COM3 (Windows) or /dev/ttyUSB0 (Linux).",
    )
    conn.add_argument(
        "--ip", metavar="ADDR",
        help="IP address for TCP/IP connection to XC112 / XE125 exploration server.",
    )

    p.add_argument("--start", type=float, default=0.3,
                   help="Measurement range start [m] (distance from radar face).")
    p.add_argument("--end",   type=float, default=2.0,
                   help="Measurement range end [m].")
    p.add_argument("--num-points", type=int, default=4,
                   help="Number of range points inside the measurement window.")
    p.add_argument("--sweeps", type=int, default=16,
                   help="Sweeps per frame.  More sweeps → better velocity resolution.")
    p.add_argument("--frame-rate", type=float, default=10.0,
                   help="Output frame rate [Hz].")
    p.add_argument("--angle", type=float, default=45.0,
                   help="Radar tilt angle from horizontal [°]. 45° is typical for "
                        "open-channel flow gauging.")
    p.add_argument("--gain", type=int, default=16,
                   help="Receiver gain [0–23 dB].  Reduce if signal is saturated.")
    p.add_argument("--time-series", type=int, default=512,
                   help="Length of the velocity time series used inside the processor.")
    p.add_argument("--lp-coeff", type=float, default=0.5,
                   help="Low-pass filter coefficient for velocity output [0–1].")
    p.add_argument("--threshold-db", type=float, default=0.0,
                   help="Detection threshold [dB] relative to noise floor.")
    p.add_argument("--log", metavar="FILE",
                   help="Append measurements to a CSV file.")
    return p


# ── Helpers ──────────────────────────────────────────────────────────────────

def _m_to_pt(meters: float) -> int:
    """Convert a distance in meters to an A121 range-point index."""
    return max(0, round(meters / METERS_PER_POINT))


def _open_client(args: argparse.Namespace) -> "a121.Client":
    if args.ip:
        print(f"[XE125] Connecting via TCP  → {args.ip}")
        return a121.Client.open(ip_address=args.ip)
    if args.port:
        print(f"[XE125] Connecting via UART → {args.port}")
        return a121.Client.open(serial_port=args.port)
    print("[XE125] Auto-detecting USB/UART connection …")
    return a121.Client.open()


def _build_sensor_config(args: argparse.Namespace) -> "a121.SensorConfig":
    """
    Configure the A121 sensor for coherent (Sparse IQ) sweeps.

    Profile 1 gives shortest pulse (≈5 cm range resolution) and is
    appropriate for near-field surface measurements.
    """
    start_pt = _m_to_pt(args.start)

    return a121.SensorConfig(
        start_point=start_pt,
        num_points=args.num_points,
        step_length=1,
        profile=a121.Profile.PROFILE_1,
        sweeps_per_frame=args.sweeps,
        frame_rate=args.frame_rate,
        # Let the firmware pick the fastest sweep rate for the chosen frame rate.
        sweep_rate=None,
        inter_frame_idle_state=a121.IdleState.DEEP_SLEEP,
        inter_sweep_idle_state=a121.IdleState.READY,
        continuous_sweep_mode=True,
        double_buffering=True,
        receiver_gain=args.gain,
        tx_disable=False,
        phase_enhancement=True,
    )


def _build_processor(
    sensor_cfg: "a121.SensorConfig",
    args: argparse.Namespace,
) -> "Processor":
    proc_cfg = ProcessorConfig(
        surface_distance=args.start,
        time_series_length=args.time_series,
        lp_coeff=args.lp_coeff,
        threshold_db=args.threshold_db,
        radar_angle=args.angle,
    )
    return Processor(
        sensor_config=sensor_cfg,
        processor_config=proc_cfg,
        context=ProcessorContext(),
    )


# ── Main measurement loop ────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    client = _open_client(args)

    log_fh: Optional[object] = None
    writer: Optional[csv.writer] = None

    try:
        sensor_cfg = _build_sensor_config(args)
        processor  = _build_processor(sensor_cfg, args)

        client.setup_session(sensor_cfg)
        client.start_session()

        if args.log:
            log_fh = open(args.log, "a", newline="", encoding="utf-8")
            writer = csv.writer(log_fh)
            # Write header only when the file is empty.
            if log_fh.tell() == 0:
                writer.writerow(["timestamp_s", "elapsed_s",
                                  "velocity_m_s", "peak_snr_db"])

        print()
        print(f"  XE125 session active")
        print(f"  Range         : {args.start:.2f} – "
              f"{args.start + args.num_points * METERS_PER_POINT:.3f} m  "
              f"({args.num_points} points)")
        print(f"  Radar angle   : {args.angle:.1f}° from horizontal")
        print(f"  Sweeps/frame  : {args.sweeps}  |  Frame rate: {args.frame_rate} Hz")
        print(f"  Receiver gain : {args.gain} dB")
        if args.log:
            print(f"  Logging to    : {args.log}")
        print()
        print(f"  Press Ctrl-C to stop.")
        print()
        print(f"{'Elapsed':>9}  {'Velocity (m/s)':>16}  {'SNR (dB)':>10}  Status")
        print("─" * 52)

        running = True
        start_t  = time.monotonic()

        def _stop(sig, frame):   # noqa: ANN001
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, _stop)

        while running:
            frame      = client.get_next()
            result     = processor.process(frame)
            elapsed    = time.monotonic() - start_t
            timestamp  = time.time()

            velocity: Optional[float] = result.velocity
            snr_db: float = getattr(result, "peak_signal_to_noise", float("nan"))

            if velocity is not None:
                status = "OK"
                print(f"  {elapsed:>7.1f}s  {velocity:>+14.4f}  {snr_db:>10.2f}  {status}")
                if writer is not None:
                    writer.writerow([
                        f"{timestamp:.3f}",
                        f"{elapsed:.3f}",
                        f"{velocity:.6f}",
                        f"{snr_db:.2f}",
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
            client.stop_session()
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
            "    pip install acconeer-exptool",
            file=sys.stderr,
        )
        sys.exit(1)

    args = _build_parser().parse_args()

    if args.start >= args.end:
        print("ERROR: --start must be less than --end.", file=sys.stderr)
        sys.exit(1)
    if not (0 < args.angle < 90):
        print("ERROR: --angle must be between 0° and 90° (exclusive).", file=sys.stderr)
        sys.exit(1)
    if not (0 <= args.gain <= 23):
        print("ERROR: --gain must be between 0 and 23.", file=sys.stderr)
        sys.exit(1)

    run(args)


if __name__ == "__main__":
    main()
