#!/bin/bash
# noba-web.sh – Ultimate dashboard (full version with all embedded code)
# Version: 3.2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
START_PORT="${START_PORT:-8080}"
MAX_PORT="${MAX_PORT:-8090}"
HTML_DIR="${HTML_DIR:-/tmp/noba-web}"
SERVER_PID_FILE="${SERVER_PID_FILE:-/tmp/noba-web-server.pid}"
LOG_FILE="${LOG_FILE:-/tmp/noba-web.log}"
KILL_ONLY=false
HOST="${HOST:-0.0.0.0}"
DEFAULT_SERVICES="backup-to-nas.service organize-downloads.service noba-web.service syncthing.service"

# -------------------------------------------------------------------
# Load user configuration (stateless)
# -------------------------------------------------------------------
START_PORT="$(get_config ".web.start_port" "$START_PORT")"
MAX_PORT="$(get_config ".web.max_port" "$MAX_PORT")"
HOST="$(get_config ".web.host" "$HOST")"
SERVICES_LIST=$(get_config_array ".web.service_list" | tr '\n' ',' | sed 's/,$//')
if [ -n "$SERVICES_LIST" ]; then
    export NOBA_WEB_SERVICES="$SERVICES_LIST"
else
    export NOBA_WEB_SERVICES="${DEFAULT_SERVICES// /,}"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-web.sh version 3.2.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Launch an interactive web dashboard for Nobara automation.

Options:
  -p, --port PORT   Start searching from PORT (default: $START_PORT)
  -m, --max PORT    Maximum port to try (default: $MAX_PORT)
  --host HOST       Bind to specific host/IP (default: $HOST)
  -k, --kill        Kill any running noba-web server and exit
  --help            Show this help message
  --version         Show version information
EOF
    exit 0
}

kill_server() {
    if [ -f "$SERVER_PID_FILE" ]; then
        local pid
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping old server (PID $pid)..."
            kill "$pid" 2>/dev/null && sleep 1
            if kill -0 "$pid" 2>/dev/null; then
                log_warn "Force killing server..."
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$SERVER_PID_FILE"
    fi
}

find_free_port() {
    local start="$1"
    local max="$2"
    local port

    if command -v ss &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            if ! ss -tuln 2>/dev/null | grep -q ":$port[[:space:]]"; then
                echo "$port"
                return 0
            fi
        done
    elif command -v lsof &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            if ! lsof -i:"$port" -sTCP:LISTEN -t 2>/dev/null | grep -q .; then
                echo "$port"
                return 0
            fi
        done
    else
        log_error "Neither 'ss' nor 'lsof' found – cannot check port availability."
        exit 1
    fi
    return 1
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o p:m:k -l port:,max:,host:,kill,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -p|--port)    START_PORT="$2"; shift 2 ;;
        -m|--max)     MAX_PORT="$2"; shift 2 ;;
        --host)       HOST="$2"; shift 2 ;;
        -k|--kill)    KILL_ONLY=true; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *)            break ;;
    esac
done

if [ "$KILL_ONLY" = true ]; then
    kill_server
    log_info "Server stopped (if any)."
    exit 0
fi

check_deps python3
if ! command -v ss &>/dev/null && ! command -v lsof &>/dev/null; then
    log_error "Need either 'ss' or 'lsof' to check port availability."
    exit 1
fi

PORT=$(find_free_port "$START_PORT" "$MAX_PORT") || {
    log_error "No free port found between $START_PORT and $MAX_PORT."
    exit 1
}
log_info "Using port $PORT"

# Create clean HTML directory
mkdir -p "$HTML_DIR"
rm -f "$HTML_DIR"/*.html "$HTML_DIR"/server.py "$HTML_DIR"/stats.json 2>/dev/null || true

# -------------------------------------------------------------------
# Write index.html
# -------------------------------------------------------------------
cat > "$HTML_DIR/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nobara Interactive Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg-gradient: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            --card-bg: rgba(30, 41, 59, 0.7);
            --card-border: rgba(255, 255, 255, 0.08);
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --accent: #3b82f6;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            --card-blur: blur(12px);
        }
        body {
            background: var(--bg-gradient);
            color: var(--text-primary);
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            min-height: 100vh;
            padding: 2rem;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }
        h1 { font-size: 2.5rem; font-weight: 600; letter-spacing: -0.02em; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.75rem; }
        h1 i { color: var(--accent); font-size: 2rem; }
        .timestamp { color: var(--text-secondary); margin-bottom: 2.5rem; font-size: 0.95rem; display: flex; align-items: center; gap: 0.5rem; }

        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }
        .card { background: var(--card-bg); backdrop-filter: var(--card-blur); -webkit-backdrop-filter: var(--card-blur); border: 1px solid var(--card-border); border-radius: 1.5rem; padding: 1.5rem; box-shadow: var(--glass-shadow); transition: transform 0.2s ease, box-shadow 0.2s ease; }
        .card:hover { transform: translateY(-4px); box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4); }
        .card-header { font-size: 1.25rem; font-weight: 600; margin-bottom: 1.25rem; display: flex; align-items: center; gap: 0.5rem; border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding-bottom: 0.75rem; }
        .card-header i { color: var(--accent); width: 1.5rem; }

        .stat-row { display: flex; justify-content: space-between; margin: 0.75rem 0; font-size: 0.95rem; }
        .stat-label { color: var(--text-secondary); }
        .stat-value { font-weight: 500; }
        .success { color: var(--success); }
        .warning { color: var(--warning); }
        .danger { color: var(--danger); }

        .disk-item { display: flex; align-items: center; gap: 0.75rem; margin: 0.75rem 0; }
        .disk-item span:first-child { min-width: 80px; font-size: 0.9rem; color: var(--text-secondary); }
        .disk-bar { flex: 1; height: 0.5rem; background: rgba(255, 255, 255, 0.1); border-radius: 1rem; overflow: hidden; }
        .disk-bar-fill { height: 100%; border-radius: 1rem; transition: width 0.3s ease; }
        .disk-percent { min-width: 3rem; text-align: right; font-weight: 500; }

        pre { background: rgba(0, 0, 0, 0.3); padding: 0.75rem; border-radius: 0.75rem; font-size: 0.8rem; font-family: 'Fira Code', monospace; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; color: var(--text-secondary); border: 1px solid rgba(255, 255, 255, 0.05); margin: 1rem 0 0.5rem; }

        .button-grid { display: flex; gap: 0.75rem; margin-top: 1rem; flex-wrap: wrap; }
        .btn { padding: 0.6rem 1.2rem; border: none; border-radius: 2rem; background: rgba(255, 255, 255, 0.1); color: var(--text-primary); font-size: 0.9rem; font-weight: 500; cursor: pointer; transition: all 0.2s ease; display: inline-flex; align-items: center; gap: 0.4rem; border: 1px solid rgba(255, 255, 255, 0.05); }
        .btn:hover { background: rgba(255, 255, 255, 0.2); transform: translateY(-2px); }
        .btn-primary { background: var(--accent); border-color: rgba(59, 130, 246, 0.5); }
        .btn-primary:hover { background: #2563eb; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

        .modal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(8px); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .modal-content { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 1.5rem; padding: 2rem; width: 90%; max-width: 700px; box-shadow: var(--glass-shadow); }
        .modal-content pre { max-height: 50vh; overflow-y: auto; }
        .modal-header { font-size: 1.5rem; font-weight: 600; margin-bottom: 1rem; }

        .footer { margin-top: 2rem; text-align: center; color: var(--text-secondary); display: flex; justify-content: center; gap: 1.5rem; align-items: center; font-size: 0.9rem; }
        canvas.sparkline { width: 100%; height: 40px; max-height: 40px; }
        .collapsible { cursor: pointer; user-select: none; }
        .collapsible i { transition: transform 0.2s; }
        .collapsible.open i { transform: rotate(90deg); }
        .collapsible-content { max-height: 0; overflow: hidden; transition: max-height 0.3s ease-out; }
        .collapsible-content.open { max-height: 500px; }

        @media (max-width: 640px) { body { padding: 1rem; } h1 { font-size: 2rem; } }
    </style>
</head>
<body x-data="dashboard()" x-init="init()">
    <h1><i class="fas fa-chart-pie"></i> Nobara Dashboard</h1>
    <div class="timestamp">
        <i class="fas fa-sync-alt" :class="refreshing ? 'fa-spin' : ''"></i>
        Last updated: <span x-text="timestamp"></span>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-header"><i class="fas fa-microchip"></i> System Health</div>
            <div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value" x-text="uptime"></span></div>
            <div class="stat-row"><span class="stat-label">Load Average</span><span class="stat-value" x-text="loadavg"></span></div>
            <div class="stat-row"><span class="stat-label">Memory</span><span class="stat-value" x-text="memory"></span></div>
            <div class="stat-row"><span class="stat-label">CPU Temp</span><span class="stat-value" :class="cpuTempClass" x-text="cpuTemp"></span></div>
        </div>

        <div class="card">
            <div class="card-header"><i class="fas fa-gamepad"></i> GPU</div>
            <div class="stat-row"><span class="stat-label">Temperature</span><span class="stat-value" :class="gpuTempClass" x-text="gpuTemp"></span></div>
            <div class="stat-row"><span class="stat-label">Load</span><span class="stat-value" x-text="gpuLoad"></span></div>
        </div>

        <div class="card" x-show="zfs.pools && zfs.pools.length > 0">
            <div class="card-header"><i class="fas fa-layer-group"></i> ZFS Pools</div>
            <template x-for="pool in zfs.pools" :key="pool.name">
                <div class="stat-row"><span class="stat-label" x-text="pool.name"></span><span class="stat-value" :class="{'success': pool.health==='ONLINE','warning': pool.health==='DEGRADED','danger': pool.health==='FAULTED'}" x-text="pool.health"></span></div>
            </template>
        </div>

        <div class="card" style="grid-column: span 2;">
            <div class="card-header"><i class="fas fa-hdd"></i> Disk Usage</div>
            <template x-for="disk in disks" :key="disk.mount">
                <div class="disk-item">
                    <span x-text="disk.mount"></span>
                    <div class="disk-bar"><div class="disk-bar-fill" :style="'width:'+disk.percent+'%; background: var(--'+disk.barClass+');'"></div></div>
                    <span class="disk-percent" x-text="disk.percent+'%'"></span>
                </div>
            </template>
        </div>

        <div class="card" style="grid-column: span 2;">
            <div class="card-header"><i class="fas fa-cogs"></i> Monitored Services</div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                <template x-for="svc in services" :key="svc.name">
                    <div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 0.5rem;">
                        <div class="stat-row" style="margin-top:0"><span class="stat-label" style="font-weight:600; color:var(--text-primary)" x-text="svc.name.replace('.service','')"></span><span class="stat-value" :class="{'success': svc.status==='active','warning': svc.status==='inactive','danger': svc.status==='failed'}" x-text="svc.status"></span></div>
                        <div class="stat-row" style="font-size:0.85rem; margin-bottom:0" x-show="svc.memory"><span class="stat-label">Mem:</span><span class="stat-value" x-text="svc.memory"></span></div>
                        <div class="stat-row" style="font-size:0.85rem; margin:0" x-show="svc.cpu"><span class="stat-label">CPU:</span><span class="stat-value" x-text="svc.cpu"></span></div>
                    </div>
                </template>
            </div>
        </div>

        <div class="card">
            <div class="card-header"><i class="fas fa-play-circle"></i> Scripts & Actions</div>
            <div class="button-grid" style="flex-direction: column;">
                <button class="btn btn-primary" :disabled="runningScript" @click="runScript('backup')"><i class="fas fa-database"></i> Run NAS Backup</button>
                <button class="btn" :disabled="runningScript" @click="runScript('verify')"><i class="fas fa-check-double"></i> Verify Backups</button>
                <button class="btn" :disabled="runningScript" @click="runScript('organize')"><i class="fas fa-folder-open"></i> Organize Downloads</button>
                <button class="btn" :disabled="runningScript" @click="runScript('diskcheck')"><i class="fas fa-stethoscope"></i> Check Disks</button>
            </div>
        </div>

        <div class="card">
            <div class="card-header"><i class="fas fa-network-wired"></i> Quick Info</div>
            <div class="stat-row"><span class="stat-label">Default IP</span><span class="stat-value" x-text="defaultIp"></span></div>
            <div class="stat-row"><span class="stat-label">Containers</span><span class="stat-value" x-text="dockerContainers.length + ' Running'"></span></div>
            <div class="stat-row"><span class="stat-label">Updates</span><span class="stat-value" x-text="(dnfUpdates + flatpakUpdates) + ' Pending'"></span></div>
            <div class="button-grid" style="margin-top:1rem;"><button class="btn" :disabled="runningScript" @click="runScript('speedtest')"><i class="fas fa-tachometer-alt"></i> Speed Test</button></div>
        </div>
    </div>

    <div x-show="showModal" class="modal" @click.self="showModal=false" style="display: none;">
        <div class="modal-content">
            <div class="modal-header" x-text="modalTitle"></div>
            <pre x-text="modalOutput"></pre>
            <div class="button-grid" style="justify-content: flex-end;">
                <button class="btn" :disabled="runningScript" @click="showModal=false">Close</button>
            </div>
        </div>
    </div>

    <script>
        function dashboard() {
            return {
                timestamp: '', uptime: '', loadavg: '', memory: '', cpuTemp: '', gpuTemp: '', gpuLoad: '',
                dnfUpdates: 0, flatpakUpdates: 0, defaultIp: '',
                disks: [], services: [], dockerContainers: [], zfs: { pools: [] },

                showModal: false, modalTitle: '', modalOutput: '', runningScript: false, refreshing: false,

                get cpuTempClass() { const t = parseInt(this.cpuTemp) || 0; return t > 80 ? 'danger' : t > 60 ? 'warning' : ''; },
                get gpuTempClass() { const t = parseInt(this.gpuTemp) || 0; return t > 85 ? 'danger' : t > 70 ? 'warning' : ''; },

                async init() {
                    await this.refreshStats();
                    setInterval(() => this.refreshStats(), 60000);
                },

                async refreshStats() {
                    if(this.refreshing) return;
                    this.refreshing = true;
                    try {
                        const response = await fetch('/api/stats');
                        if (!response.ok) return;
                        const data = await response.json();
                        Object.assign(this, data);
                    } catch (e) {
                        console.error('Stats fetch failed', e);
                    } finally {
                        this.refreshing = false;
                    }
                },

                async runScript(script) {
                    if (this.runningScript) return;
                    this.runningScript = true;
                    this.modalTitle = `Running ${script}...`;
                    this.modalOutput = 'Executing... This might take a moment.';
                    this.showModal = true;

                    try {
                        const response = await fetch('/api/run', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ script })
                        });
                        const result = await response.json();
                        this.modalOutput = result.output;
                        this.modalTitle = result.success ? '✅ Success' : '❌ Failed';
                    } catch (e) {
                        this.modalOutput = 'Error: ' + e.message;
                        this.modalTitle = '❌ Failed';
                    }
                    this.runningScript = false;
                    await this.refreshStats();
                }
            }
        }
    </script>
</body>
</html>
EOF

# -------------------------------------------------------------------
# Write server.py
# -------------------------------------------------------------------
cat > "$HTML_DIR/server.py" <<'EOF'
#!/usr/bin/env python3
"""
Nobara Dashboard Server - Improved Concurrency & Caching
Listens on HOST:PORT and serves the dashboard with real-time stats.
"""

import http.server
import socketserver
import json
import subprocess
import os
import time
import re
import logging
from datetime import datetime, timedelta

# -------------------- Configuration --------------------
PORT = int(os.environ.get('PORT', 8080))
HOST = os.environ.get('HOST', '0.0.0.0')
SCRIPT_DIR = os.path.expanduser("~/.local/bin")
LOG_DIR = os.path.expanduser("~/.local/share")
CACHE_TTL = 30  # seconds
PID_FILE = os.environ.get('PID_FILE', '/tmp/noba-web-server.pid')

logging.basicConfig(
    filename=os.path.join(LOG_DIR, 'noba-web-server.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# -------------------- Helper functions --------------------
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(s):
    return ansi_escape.sub('', s)

def human_bytes(b):
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if b < 1024.0: return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PiB"

class TTLCache:
    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self.cache = {}
        self.timestamps = {}

    def get(self, key):
        if key in self.cache and datetime.now() - self.timestamps[key] < timedelta(seconds=self.ttl):
            return self.cache[key]
        return None

    def set(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = datetime.now()

_cache = TTLCache(CACHE_TTL)

def run_cmd(cmd_list, timeout=2, cache_ttl=None):
    """Executes a subprocess and returns stripped stdout. Allows optional caching."""
    cache_key = " ".join(cmd_list)
    if cache_ttl:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout)
        out = res.stdout.strip() if res.returncode == 0 else ""
        if cache_ttl and out:
            _cache.set(cache_key, out)
        return out
    except Exception as e:
        logging.debug(f"Command failed: {cache_key} -> {e}")
        return ""

# -------------------- Threaded Server Class --------------------
class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

# -------------------- Handler class --------------------
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='.', **kwargs)

    def log_message(self, format, *args):
        # Silence standard HTTP logs to keep stderr clean
        pass

    # ---------- System Stats ----------
    def get_zfs_pools(self):
        pools = []
        out = run_cmd(['zpool', 'list', '-H', '-o', 'name,health'], timeout=2, cache_ttl=10)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2: pools.append({'name': parts[0], 'health': parts[1]})
        return pools

    def get_gpu_info(self):
        # NVIDIA Temp
        out = run_cmd(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'], timeout=1, cache_ttl=5)
        if out: return f"{out}°C", run_cmd(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader'], timeout=1, cache_ttl=5)

        # AMD Temp
        out = run_cmd(['rocm-smi', '--showtemp', '--json'], timeout=1, cache_ttl=5)
        if out:
            try:
                data = json.loads(out)
                for card in data.values():
                    if isinstance(card, dict):
                        for k, v in card.items():
                            if 'temperature' in k.lower(): return f"{float(v):.0f}°C", "N/A"
            except: pass
        return "N/A", "N/A"

    def get_docker_containers(self):
        containers = []
        out = run_cmd(['docker', 'ps', '--format', '{{.Names}} ({{.Status}})'], timeout=3, cache_ttl=10)
        return out.splitlines() if out else []

    def get_service_details(self, service):
        details = {}
        out = run_cmd(['systemctl', '--user', 'show', service], timeout=1, cache_ttl=10)
        for line in out.splitlines():
            if '=' in line:
                key, val = line.split('=', 1)
                if key == 'MemoryCurrent' and val != '0' and val.isdigit():
                    details['memory'] = human_bytes(int(val))
                elif key == 'CPUUsageNSec' and val != '0' and val.isdigit():
                    sec = int(val) / 1_000_000_000
                    details['cpu'] = f"{sec:.1f}s" if sec < 60 else f"{int(sec//60)}m{int(sec%60)}s"
        return details

    # ---------- GET /api/stats ----------
    def do_GET(self):
        if self.path == '/api/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(self.get_stats()).encode())
        else:
            # Only serve basic files from current dir to prevent traversal
            if self.path in ['/', '/index.html']:
                super().do_GET()
            else:
                self.send_error(404, "Not Found")

    # ---------- POST /api/run ----------
    def do_POST(self):
        if self.path == '/api/run':
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_len)
                data = json.loads(post_data)
                script = data.get('script', '')

                script_map = {
                    'backup': 'backup-to-nas.sh',
                    'verify': 'backup-verifier.sh',
                    'organize': 'organize-downloads.sh',
                    'diskcheck': 'disk-sentinel.sh',
                    'cloudbackup': 'cloud-backup.sh',
                }

                if script == 'speedtest':
                    proc = subprocess.run(['speedtest-cli', '--simple'], capture_output=True, text=True, timeout=60)
                    output = proc.stdout + proc.stderr
                    success = proc.returncode == 0
                else:
                    script_file = os.path.join(SCRIPT_DIR, script_map.get(script, ''))
                    if not os.path.exists(script_file):
                        output = f"Script {script} not found at {script_file}"
                        success = False
                    else:
                        proc = subprocess.run([script_file, '--verbose'], capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR)
                        output = strip_ansi(proc.stdout + proc.stderr)
                        success = proc.returncode == 0

                result = {'success': success, 'output': output}
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except subprocess.TimeoutExpired:
                self._send_json({'success': False, 'output': 'Script timed out.'})
            except Exception as e:
                self._send_json({'success': False, 'output': f"Error: {str(e)}"})
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    # ---------- Main stats collector ----------
    def get_stats(self):
        stats = {'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}

        try:
            uptime_sec = float(open('/proc/uptime').read().split()[0])
            stats['uptime'] = f"{int(uptime_sec//3600)}h {int((uptime_sec%3600)//60)}m"
        except: stats['uptime'] = 'N/A'

        try: stats['loadavg'] = open('/proc/loadavg').read().split()[0]
        except: stats['loadavg'] = 'N/A'

        try:
            with open('/proc/meminfo') as f:
                lines = f.readlines()
            mem_tot = next(int(l.split()[1])//1024 for l in lines if 'MemTotal' in l)
            mem_av = next(int(l.split()[1])//1024 for l in lines if 'MemAvailable' in l)
            stats['memory'] = f"{mem_av}Mi/{mem_tot}Mi"
        except: stats['memory'] = 'N/A'

        gpu_temp, gpu_load = self.get_gpu_info()
        stats['gpuTemp'], stats['gpuLoad'], stats['cpuTemp'] = gpu_temp, gpu_load, gpu_temp

        # Updates (Cached)
        cached_updates = _cache.get('updates')
        if cached_updates:
            stats['dnfUpdates'], stats['flatpakUpdates'] = cached_updates
        else:
            dnf_out = run_cmd(['dnf', 'check-update', '-q'], timeout=10)
            flat_out = run_cmd(['flatpak', 'remote-ls', '--updates'], timeout=10)
            dnf_c = len([l for l in dnf_out.splitlines() if l and not l.startswith('Last metadata')])
            flat_c = len([l for l in flat_out.splitlines() if l])
            _cache.set('updates', (dnf_c, flat_c))
            stats['dnfUpdates'], stats['flatpakUpdates'] = dnf_c, flat_c

        # Disk usage
        disks = []
        df_out = run_cmd(['df', '-h'], timeout=2, cache_ttl=10)
        for line in df_out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5 and parts[0].startswith('/dev/'):
                mount = parts[5] if len(parts) > 5 else ''
                if mount.startswith(('/var/lib/snapd', '/boot')): continue
                pct = parts[4].replace('%', '')
                bar_class = 'danger' if int(pct) >= 90 else 'warning' if int(pct) >= 75 else 'success'
                disks.append({'mount': mount, 'percent': pct, 'barClass': bar_class})
        stats['disks'] = disks

        # Default IP
        ip_out = run_cmd(['ip', '-4', 'route', 'get', '1'], timeout=1, cache_ttl=30)
        match = re.search(r'src\s+(\d+\.\d+\.\d+\.\d+)', ip_out)
        stats['defaultIp'] = match.group(1) if match else 'N/A'

        # Services
        service_list = os.environ.get('NOBA_WEB_SERVICES', '').split(',')
        services_status = []
        for svc in service_list:
            if not svc.strip(): continue
            status = run_cmd(['systemctl', '--user', 'is-active', svc.strip()], timeout=1) or 'unknown'
            svc_info = {'name': svc.strip(), 'status': status}
            svc_info.update(self.get_service_details(svc.strip()))
            services_status.append(svc_info)
        stats['services'] = services_status

        stats['dockerContainers'] = self.get_docker_containers()
        stats['zfs'] = {'pools': self.get_zfs_pools()}

        return stats

# -------------------- Server setup --------------------
def run_server():
    with ThreadedTCPServer((HOST, PORT), Handler) as httpd:
        logging.info(f"Serving dashboard at http://{HOST}:{PORT}")
        print(f"Serving dashboard at http://{HOST}:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logging.info("Shutting down...")
            httpd.shutdown()

if __name__ == '__main__':
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    run_server()
EOF

# -------------------------------------------------------------------
# Start the server
# -------------------------------------------------------------------
kill_server

export PORT
export HOST
export PID_FILE="$SERVER_PID_FILE"
cd "$HTML_DIR"

: > "$LOG_FILE"

nohup python3 server.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$SERVER_PID_FILE"

sleep 2
if kill -0 "$SERVER_PID" 2>/dev/null; then
    log_success "Web dashboard started on http://$HOST:$PORT"
    log_info "Log file: $LOG_FILE"
    log_info "Use '$0 --kill' to stop the server."
else
    log_error "Server failed to start. Last 20 lines of log:"
    tail -20 "$LOG_FILE" >&2
    exit 1
fi
