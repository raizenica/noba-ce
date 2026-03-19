#!/usr/bin/env python3
"""NOBA Agent -- Lightweight system telemetry collector.

Collects CPU, memory, disk, network, temperature, and top process metrics
and reports them to the NOBA Command Center via authenticated HTTP POST.

Usage:
    python agent.py --server http://noba:8080 --key YOUR_API_KEY
    python agent.py --config /etc/noba-agent.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
import urllib.error
import urllib.request

# -- Configuration ------------------------------------------------------------
DEFAULT_INTERVAL = 30
DEFAULT_CONFIG = "/etc/noba-agent.yaml"


def load_config(path: str | None = None) -> dict:
    """Load config from YAML file or environment."""
    cfg = {
        "server": os.environ.get("NOBA_SERVER", ""),
        "api_key": os.environ.get("NOBA_AGENT_KEY", ""),
        "interval": int(os.environ.get("NOBA_AGENT_INTERVAL", DEFAULT_INTERVAL)),
        "hostname": os.environ.get("NOBA_AGENT_HOSTNAME", ""),
        "tags": os.environ.get("NOBA_AGENT_TAGS", ""),
    }
    if path and os.path.exists(path):
        try:
            import yaml
            with open(path) as f:
                file_cfg = yaml.safe_load(f) or {}
            for k, v in file_cfg.items():
                if v:
                    cfg[k] = v
        except ImportError:
            # Parse simple key: value without yaml
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if ":" in line and not line.startswith("#"):
                        k, v = line.split(":", 1)
                        cfg[k.strip()] = v.strip()
    return cfg


# -- Metrics Collection -------------------------------------------------------
def collect_metrics() -> dict:
    """Collect system metrics using psutil."""
    import psutil

    # CPU
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)

    # Memory
    mem = psutil.virtual_memory()

    # Disk
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "mount": part.mountpoint,
                "total": usage.total,
                "used": usage.used,
                "percent": usage.percent,
                "fstype": part.fstype,
            })
        except (PermissionError, OSError):
            pass

    # Network I/O
    net = psutil.net_io_counters()

    # Temperature
    temps = {}
    try:
        for name, entries in psutil.sensors_temperatures().items():
            for entry in entries:
                if entry.current > 0:
                    key = f"{name}_{entry.label}" if entry.label else name
                    temps[key] = round(entry.current, 1)
    except (AttributeError, RuntimeError):
        pass

    # Top processes by CPU
    top_procs = []
    try:
        for proc in sorted(
            psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
            key=lambda p: p.info.get("cpu_percent", 0) or 0,
            reverse=True,
        )[:5]:
            info = proc.info
            top_procs.append({
                "pid": info.get("pid", 0),
                "name": info.get("name", ""),
                "cpu": round(info.get("cpu_percent", 0) or 0, 1),
                "mem": round(info.get("memory_percent", 0) or 0, 1),
            })
    except (psutil.Error, OSError):
        pass

    # Uptime
    boot_time = psutil.boot_time()
    uptime_s = int(time.time() - boot_time)

    return {
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "arch": platform.machine(),
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "load_1m": round(load[0], 2),
        "load_5m": round(load[1], 2),
        "load_15m": round(load[2], 2),
        "mem_total": mem.total,
        "mem_used": mem.used,
        "mem_percent": round(mem.percent, 1),
        "disks": disks,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
        "temperatures": temps,
        "top_processes": top_procs,
        "uptime_s": uptime_s,
        "timestamp": int(time.time()),
    }


# -- Reporting -----------------------------------------------------------------
def report(server: str, api_key: str, metrics: dict) -> bool:
    """Send metrics to NOBA server."""
    url = f"{server.rstrip('/')}/api/agent/report"
    data = json.dumps(metrics).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Agent-Key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError) as e:
        print(f"[agent] Report failed: {e}", file=sys.stderr)
        return False


# -- Main Loop -----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="NOBA Agent")
    parser.add_argument("--server", help="NOBA server URL")
    parser.add_argument("--key", help="Agent API key")
    parser.add_argument("--interval", type=int, help="Collection interval (seconds)")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Config file path")
    parser.add_argument("--once", action="store_true", help="Collect and report once, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Collect and print, don't send")
    args = parser.parse_args()

    cfg = load_config(args.config)
    server = args.server or cfg["server"]
    api_key = args.key or cfg["api_key"]
    interval = args.interval or cfg.get("interval", DEFAULT_INTERVAL)

    if not server and not args.dry_run:
        print("Error: --server or NOBA_SERVER required", file=sys.stderr)
        sys.exit(1)

    hostname = cfg.get("hostname") or socket.gethostname()
    print(f"[agent] NOBA Agent starting on {hostname}")
    print(f"[agent] Server: {server or '(dry-run)'}")
    print(f"[agent] Interval: {interval}s")

    while True:
        try:
            metrics = collect_metrics()
            metrics["hostname"] = hostname
            if cfg.get("tags"):
                metrics["tags"] = cfg["tags"]

            if args.dry_run:
                print(json.dumps(metrics, indent=2))
            else:
                ok = report(server, api_key, metrics)
                if not ok:
                    print(f"[agent] Report failed at {time.strftime('%H:%M:%S')}", file=sys.stderr)

            if args.once or args.dry_run:
                break
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[agent] Stopped")
            break
        except Exception as e:
            print(f"[agent] Error: {e}", file=sys.stderr)
            if args.once:
                break
            time.sleep(interval)


if __name__ == "__main__":
    main()
