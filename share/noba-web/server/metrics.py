import psutil
import time

def get_system_metrics() -> dict:
    """
    Directly queries the kernel for system metrics using psutil.
    Eliminates all blocking subprocess calls.
    """
    # CPU & Memory
    cpu_percent = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()

    # Disk Usage
    disk_metrics = []
    for part in psutil.disk_partitions(all=False):
        # Ignore read-only or virtual filesystems (crucial for Docker/TrueNAS)
        if 'squashfs' in part.fstype or 'tmpfs' in part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disk_metrics.append({
                "mount": part.mountpoint,
                "percent": usage.percent,
                "free_gb": round(usage.free / (1024**3), 2),
                "total_gb": round(usage.total / (1024**3), 2)
            })
        except PermissionError:
            continue

    # Network I/O (Bytes sent/recv)
    net_io = psutil.net_io_counters()

    # Temperatures (Hardware dependent, fails gracefully)
    temps = {}
    try:
        hw_temps = psutil.sensors_temperatures()
        for name, entries in hw_temps.items():
            if entries:
                temps[name] = entries[0].current
    except Exception:
        pass

    return {
        "timestamp": int(time.time()),
        "cpu_percent": cpu_percent,
        "memory_percent": mem.percent,
        "memory_used_gb": round(mem.used / (1024**3), 2),
        "disks": disk_metrics,
        "network": {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv
        },
        "temperatures": temps
    }
