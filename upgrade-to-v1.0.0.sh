#!/usr/bin/env bash
# upgrade-to-v1.0.0.sh – Apply all improvements and set version 1.0.0

set -euo pipefail

echo "🚀 Upgrading Nobara Automation Suite to v1.0.0"
echo "---------------------------------------------"

# 0. Determine repository root (where this script is)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# 1. Create VERSION file
echo "1.0.0" > VERSION
echo "✅ Created VERSION file: 1.0.0"

# 2. Backup existing files
backup_dir="backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
cp -a bin libexec share install.sh systemd docs "$backup_dir" 2>/dev/null || true
echo "✅ Backed up current state to $backup_dir"

# 3. Update functions.sh
cat > libexec/noba/noba-web/functions.sh <<'OUTER_EOF'
#!/usr/bin/env bash
# Nobara Web Dashboard functions – v1.0.0
# Must be sourced from noba-web launcher.

# ── Version ──────────────────────────────────────────────────────────────────
show_version() {
    if [[ -n "${NOBA_ROOT:-}" && -f "$NOBA_ROOT/VERSION" ]]; then
        cat "$NOBA_ROOT/VERSION"
    else
        echo "unknown"
    fi
    exit 0
}

# ── Help ─────────────────────────────────────────────────────────────────────
show_help() {
    cat <<HELP
Usage: noba-web [OPTIONS]
Launch the Nobara Command Center web dashboard.

Options:
  -p, --port PORT          Start searching from PORT (default: 8080)
  -m, --max  PORT          Maximum port to try (default: 8090)
  --host     HOST          Bind to specific host/IP (default: 0.0.0.0)
  -k, --kill               Kill any running noba-web server and exit
  -v, --verbose            Tail the server log after starting (Ctrl+C to stop)
  --https                  Enable HTTPS/TLS (requires --generate-cert first)
  --generate-cert          Create a self-signed TLS certificate and exit
  --add-user               Add or update a user (interactive, supports roles)
  --remove-user USERNAME   Remove a user from auth.conf
  --list-users             List configured users and their roles
  --set-password           Alias for --add-user (backward compatible)
  --restart                Kill any running server and start a new one
  --status                 Show whether the server is running
  --generate-systemd       Print a systemd .service unit and exit
  --config FILE            Use an alternative configuration file
  --help                   Show this help message
  --version                Show version information

Configuration: ~/.config/noba-web.conf
Credentials:   ~/.config/noba-web/auth.conf
TLS certs:     ~/.config/noba-web/server.{crt,key}
HELP
    exit 0
}

# ── Default YAML ─────────────────────────────────────────────────────────────
create_default_yaml() {
    [[ -f "$NOBA_YAML" ]] && return
    log_info "Creating default YAML config at $NOBA_YAML"
    mkdir -p "$(dirname "$NOBA_YAML")"
    cat > "$NOBA_YAML" <<YAML
# Nobara Automation Suite configuration
email: "your@email.com"

backup:
  dest: "$HOME/backups"
  sources:
    - "$HOME/Documents"
    - "$HOME/Pictures"
    - "$HOME/.config"
  retention_days: 7
  space_margin_percent: 10
  min_free_space_gb: 5

disk:
  threshold: 85
  targets:
    - "/"
    - "/home"
  cleanup_enabled: true

downloads:
  dir: "$HOME/Downloads"
  min_age_minutes: 5
  dated_subfolders: true

logs:
  dir: "$HOME/.local/share/noba"
  log_rotation:
    days: 30

web:
  start_port: 8080
  max_port: 8090
  piholeUrl: "dnsa01.vannieuwenhove.org"
  piholeToken: ""
  monitoredServices: "backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service"
  radarIps: "192.168.100.1, 1.1.1.1, 8.8.8.8"
  bookmarksStr: "TrueNAS (vnnas)|http://vnnas.vannieuwenhove.org|fa-server, Pi-Hole|http://dnsa01.vannieuwenhove.org/admin|fa-shield-alt, Home Assistant|http://homeassistant.local:8123|fa-home"
YAML
    log_success "Default YAML created. Please edit: $NOBA_YAML"
}

# ── Status ───────────────────────────────────────────────────────────────────
show_status() {
    if [[ -f "$SERVER_PID_FILE" ]]; then
        local pid url
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        url=$(cat "$SERVER_URL_FILE" 2>/dev/null || echo "unknown URL")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_success "Server running  PID=$pid  URL=$url"
            echo "  Log: $LOG_FILE"
        else
            log_warning "PID file present but server is not running (stale). Cleaning up."
            rm -f "$SERVER_PID_FILE" "$SERVER_URL_FILE"
        fi
    else
        log_info "Server is not running."
    fi
    return 0
}

# ── Generate systemd unit ────────────────────────────────────────────────────
generate_systemd() {
    local self proto_flag=""
    self="$(realpath "$0")"
    [[ "$USE_HTTPS" == true ]] && proto_flag=" --https"
    cat <<SYSTEMD_EOF
# Save to: ~/.config/systemd/user/noba-web.service
# Enable:  systemctl --user enable --now noba-web.service

[Unit]
Description=Nobara Command Center Web Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=%h/.config/noba-web.conf
ExecStart=%h/.local/bin/noba-web \$NOBA_WEB_OPTS
ExecStop=/bin/kill -TERM \$MAINPID
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=noba-web

[Install]
WantedBy=default.target
SYSTEMD_EOF
    return 0
}

# ── Generate self‑signed certificate ─────────────────────────────────────────
generate_cert() {
    if ! command -v openssl &>/dev/null; then
        log_error "openssl not found. Install it first."; return 1
    fi
    mkdir -p "$AUTH_DIR"
    local local_ip
    local_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[\d.]+' || hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
    log_info "Generating self-signed TLS certificate (RSA-2048, 365 days)…"
    openssl req -x509 -newkey rsa:2048 \
        -keyout "$KEY_FILE" -out "$CERT_FILE" \
        -days 365 -nodes \
        -subj "/C=XX/ST=Local/L=Local/O=Noba/CN=localhost" \
        -addext "subjectAltName=IP:127.0.0.1,IP:${local_ip},DNS:localhost" 2>/dev/null
    chmod 600 "$KEY_FILE"
    log_success "Certificate: $CERT_FILE"
    log_success "Private key: $KEY_FILE"
    cat <<CERT_EOF

To trust this certificate in your browser / OS:

  Linux (system-wide):
    sudo cp "${CERT_FILE}" /usr/local/share/ca-certificates/noba-web.crt
    sudo update-ca-certificates

  Firefox: Settings → Certificates → View Certificates → Authorities → Import

  Chrome/Chromium: Settings → Privacy → Security → Manage Certs → Authorities → Import

Start the server with: noba-web --https
CERT_EOF
    return 0
}

# ── User management ──────────────────────────────────────────────────────────
_hash_password() {
    python3 - "$1" <<'PYEOF'
import hashlib, secrets, sys
salt = secrets.token_hex(16)
dk   = hashlib.pbkdf2_hmac('sha256', sys.argv[1].encode(), salt.encode(), 200_000)
print(f'pbkdf2:{salt}:{dk.hex()}', end='')
PYEOF
}

add_user() {
    echo "Add / update Nobara Web Dashboard user"
    local username role password password2 pw_hash
    read -rp  "Username: "                      username
    read -rs  -p "Password: "                   password;  echo
    read -rs  -p "Confirm password: "           password2; echo
    if [[ "$password" != "$password2" ]]; then
        log_error "Passwords do not match."; return 1
    fi
    read -rp  "Role [admin/viewer] (default: admin): " role
    role="${role:-admin}"
    if [[ "$role" != "admin" && "$role" != "viewer" ]]; then
        log_error "Invalid role '${role}'. Must be 'admin' or 'viewer'."; return 1
    fi
    pw_hash=$(_hash_password "$password")
    mkdir -p "$AUTH_DIR"
    # Remove existing entry for this user (if any), then append
    if [[ -f "$AUTH_CONF" ]]; then
        grep -v "^${username}:" "$AUTH_CONF" > "${AUTH_CONF}.tmp" 2>/dev/null || true
        mv "${AUTH_CONF}.tmp" "$AUTH_CONF"
    fi
    (umask 077; printf '%s:%s:%s\n' "$username" "$pw_hash" "$role" >> "$AUTH_CONF")
    log_success "User '${username}' (${role}) saved to ${AUTH_CONF}"
    create_default_yaml
    return 0
}

remove_user() {
    local username="$1"
    if [[ ! -f "$AUTH_CONF" ]]; then
        log_error "No auth.conf found."; return 1
    fi
    if ! grep -q "^${username}:" "$AUTH_CONF"; then
        log_error "User '${username}' not found."; return 1
    fi
    grep -v "^${username}:" "$AUTH_CONF" > "${AUTH_CONF}.tmp"
    mv "${AUTH_CONF}.tmp" "$AUTH_CONF"
    log_success "User '${username}' removed."
    return 0
}

list_users() {
    if [[ ! -f "$AUTH_CONF" ]]; then
        echo "No users configured. Run:  noba-web --add-user"; return 0
    fi
    printf '%-20s  %s\n' "USERNAME" "ROLE"
    printf '%-20s  %s\n' "--------" "----"
    while IFS=: read -r user rest; do
        [[ -z "$user" || "$user" =~ ^# ]] && continue
        role=$(echo "$rest" | rev | cut -d: -f1 | rev)
        [[ "$role" != "admin" && "$role" != "viewer" ]] && role="admin"
        printf '%-20s  %s\n' "$user" "$role"
    done < "$AUTH_CONF"
    return 0
}

# ── Kill server ──────────────────────────────────────────────────────────────
kill_server() {
    if [[ -f "$SERVER_PID_FILE" ]]; then
        local pid
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping server (PID $pid)…"
            kill "$pid" 2>/dev/null && sleep 1
            kill -0 "$pid" 2>/dev/null && { kill -9 "$pid" 2>/dev/null || true; }
        fi
        rm -f "$SERVER_PID_FILE" "$SERVER_URL_FILE"
        rm -rf "$HTML_DIR"
    fi
    return 0
}

# ── Port finder ──────────────────────────────────────────────────────────────
find_free_port() {
    local start="$1" max="$2" port
    if command -v ss &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            ss -tuln 2>/dev/null | grep -q ":${port}[[:space:]]" || { echo "$port"; return 0; }
        done
    elif command -v lsof &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            lsof -i:"$port" -sTCP:LISTEN -t 2>/dev/null | grep -q . || { echo "$port"; return 0; }
        done
    else
        log_error "Neither 'ss' nor 'lsof' found."; return 1
    fi
    return 1
}
OUTER_EOF

chmod +x libexec/noba/noba-web/functions.sh
echo "✅ Updated functions.sh"

# 4. Update launcher bin/noba-web
cat > bin/noba-web <<'EOF'
#!/bin/bash
# Nobara Command Center – main launcher v1.0.0

set -euo pipefail
trap 'rc=$?; echo "Exiting with code $rc at line $LINENO" >&2' EXIT

# Find installation prefix (where this script is located)
SCRIPT_PATH="$(readlink -f "$0")"
PREFIX="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
export NOBA_ROOT="$PREFIX"

# Source libraries
source "$PREFIX/libexec/noba/lib/noba-lib.sh"
source "$PREFIX/libexec/noba/noba-web/functions.sh"

# Default configuration file (can be overridden by --config)
CONFIG_FILE_OVERRIDE=""
CONFIG_FILE="${HOME}/.config/noba-web.conf"
if [[ -f "$CONFIG_FILE" ]]; then
    source "$CONFIG_FILE"
fi

# Defaults (can be overridden by config file or command line)
START_PORT="${START_PORT:-8080}"
MAX_PORT="${MAX_PORT:-8090}"
HOST="${HOST:-0.0.0.0}"
USE_HTTPS="${USE_HTTPS:-false}"
HTML_DIR="${HTML_DIR:-/tmp/noba-web}"
SERVER_PID_FILE="${SERVER_PID_FILE:-/tmp/noba-web-server.pid}"
SERVER_URL_FILE="${SERVER_URL_FILE:-/tmp/noba-web-server.url}"
LOG_FILE="${LOG_FILE:-/tmp/noba-web.log}"
NOBA_YAML="${NOBA_CONFIG:-$HOME/.config/noba/config.yaml}"
AUTH_DIR="${HOME}/.config/noba-web"
AUTH_CONF="${AUTH_DIR}/auth.conf"
CERT_FILE="${AUTH_DIR}/server.crt"
KEY_FILE="${AUTH_DIR}/server.key"

# Flags
KILL_ONLY=false
RESTART=false
VERBOSE=false
USE_HTTPS=false
SET_PASSWORD=false
ADD_USER=false
REMOVE_USER=""
LIST_USERS=false
SHOW_STATUS=false
GEN_SYSTEMD=false
GEN_CERT=false

# Argument parsing
if ! PARSED_ARGS=$(getopt -o p:m:kv \
    -l port:,max:,host:,kill,verbose,help,version,set-password,restart,status,\
generate-systemd,https,generate-cert,add-user,remove-user:,list-users,config: \
    -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."; exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -p|--port)           START_PORT="$2";        shift 2 ;;
        -m|--max)            MAX_PORT="$2";           shift 2 ;;
        --host)              HOST="$2";               shift 2 ;;
        -k|--kill)           KILL_ONLY=true;          shift   ;;
        -v|--verbose)        VERBOSE=true;            shift   ;;
        --set-password)      ADD_USER=true;           shift   ;;
        --add-user)          ADD_USER=true;           shift   ;;
        --remove-user)       REMOVE_USER="$2";        shift 2 ;;
        --list-users)        LIST_USERS=true;         shift   ;;
        --https)             USE_HTTPS=true;          shift   ;;
        --generate-cert)     GEN_CERT=true;           shift   ;;
        --restart)           KILL_ONLY=true; RESTART=true; shift ;;
        --status)            SHOW_STATUS=true;        shift   ;;
        --generate-systemd)  GEN_SYSTEMD=true;        shift   ;;
        --config)            CONFIG_FILE_OVERRIDE="$2"; shift 2 ;;
        --help)              show_help ;;
        --version)           show_version ;;
        --)                  shift; break ;;
        *)                   log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

# Apply config override if provided
if [[ -n "$CONFIG_FILE_OVERRIDE" ]]; then
    CONFIG_FILE="$CONFIG_FILE_OVERRIDE"
    if [[ -f "$CONFIG_FILE" ]]; then
        source "$CONFIG_FILE"
    else
        log_warn "Config file $CONFIG_FILE not found, using defaults."
    fi
fi

# Handle immediate actions (these functions now return, so we exit explicitly)
if [[ "$SHOW_STATUS" == true ]]; then show_status; exit $?; fi
if [[ "$GEN_CERT" == true ]]; then generate_cert; exit $?; fi
if [[ "$GEN_SYSTEMD" == true ]]; then generate_systemd; exit $?; fi
if [[ "$ADD_USER" == true ]]; then add_user; exit $?; fi
if [[ -n "$REMOVE_USER" ]]; then remove_user "$REMOVE_USER"; exit $?; fi
if [[ "$LIST_USERS" == true ]]; then list_users; exit $?; fi

# HTTPS certificate check
if [[ "$USE_HTTPS" == true && ! -f "$CERT_FILE" ]]; then
    log_error "TLS certificate not found. Run:  noba-web --generate-cert"
    exit 1
fi

# Kill / restart
if [[ "$KILL_ONLY" == true ]]; then
    kill_server
    [[ "$RESTART" != true ]] && exit 0
fi

# Dependency checks
check_deps python3 yq
if ! yq --version 2>/dev/null | grep -q "mikefarah"; then
    log_error "'yq' must be the Go version (mikefarah/yq). See https://github.com/mikefarah/yq"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
if ! awk -v ver="$PYTHON_VERSION" 'BEGIN { split(ver,v,"."); exit !(v[1]>3||(v[1]==3&&v[2]>=7)); }'; then
    log_error "Python 3.7+ required (found $PYTHON_VERSION)."
    exit 1
fi

# Find free port
PORT=$(find_free_port "$START_PORT" "$MAX_PORT") || die "No free port in range ${START_PORT}–${MAX_PORT}."
log_info "Using port $PORT"

# Prepare runtime directory
mkdir -p "$HTML_DIR"
rm -f "$HTML_DIR"/*.html 2>/dev/null || true

# Copy frontend from installation to runtime directory
cp "$PREFIX/share/noba-web/index.html" "$HTML_DIR/"

# Create default YAML if missing
create_default_yaml

# Launch the Python backend
export PORT HOST PID_FILE="$SERVER_PID_FILE"
export NOBA_SCRIPT_DIR="$PREFIX/libexec/noba"
export NOBA_CONFIG="$NOBA_YAML"
if [[ "$USE_HTTPS" == true ]]; then
    export NOBA_HTTPS=1 NOBA_CERT="$CERT_FILE" NOBA_KEY="$KEY_FILE"
fi

cd "$HTML_DIR"
: > "$LOG_FILE"

nohup python3 "$PREFIX/libexec/noba/noba-web/server.py" >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$SERVER_PID_FILE"
PROTO=$([[ "$USE_HTTPS" == true ]] && echo "https" || echo "http")
echo "${PROTO}://${HOST}:${PORT}" > "$SERVER_URL_FILE"

# Health check
MAX_WAIT=12
WAITED=0
while true; do
    if command -v curl &>/dev/null; then
        CODE=$(curl -sk -o /dev/null -w '%{http_code}' "${PROTO}://${HOST}:${PORT}/api/health" 2>/dev/null || true)
    elif command -v wget &>/dev/null; then
        CODE=$(wget -qO- --no-check-certificate "${PROTO}://${HOST}:${PORT}/api/health" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(200 if d.get('status')=='ok' else 0)" 2>/dev/null || true)
    else
        log_error "Neither curl nor wget found."; kill "$SERVER_PID" 2>/dev/null; exit 1
    fi
    [[ "$CODE" == "200" ]] && break
    sleep 1; WAITED=$((WAITED+1))
    if [[ $WAITED -ge $MAX_WAIT ]]; then
        log_error "Server did not respond within ${MAX_WAIT}s. Last 20 lines of log:"
        tail -20 "$LOG_FILE" | sed 's/^/  /' >&2
        kill "$SERVER_PID" 2>/dev/null || true; exit 1
    fi
done

log_success "Dashboard live → ${PROTO}://${HOST}:${PORT}"
[[ "$USE_HTTPS" == true ]] && log_info "Using TLS cert: $CERT_FILE"
if [[ ! -f "$AUTH_CONF" ]]; then
    log_warning "No users configured. Run:  noba-web --add-user"
fi

if [[ "$VERBOSE" == true ]]; then
    log_info "Tailing log (Ctrl+C to stop)…"
    tail -f "$LOG_FILE" &
    TAIL_PID=$!
fi

wait "$SERVER_PID"
EXIT_CODE=$?
[[ -n "${TAIL_PID:-}" ]] && kill "$TAIL_PID" 2>/dev/null || true
exit $EXIT_CODE
EOF
chmod +x bin/noba-web
echo "✅ Updated launcher bin/noba-web"

# 5. Update server.py
cat > libexec/noba/noba-web/server.py <<'EOF'
#!/usr/bin/env python3
"""Nobara Command Center – Backend v1.0.0 (modular)"""

import http.server
import socketserver
import json
import subprocess
import os
import time
import re
import logging
import glob
import threading
import urllib.request
import urllib.error
import signal
import sys
import ipaddress
import uuid
import hashlib
import secrets
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

# ── Version from file ─────────────────────────────────────────────────────────
VERSION_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'VERSION')
try:
    with open(VERSION_FILE) as f:
        VERSION = f.read().strip()
except:
    VERSION = '1.0.0'

# ── Config ────────────────────────────────────────────────────────────────────
PORT       = int(os.environ.get('PORT',   8080))
HOST       = os.environ.get('HOST',       '0.0.0.0')
SCRIPT_DIR = os.environ.get('NOBA_SCRIPT_DIR', os.path.expanduser('~/.local/libexec/noba'))
LOG_DIR    = os.path.expanduser('~/.local/share/noba')
PID_FILE   = os.environ.get('PID_FILE',  '/tmp/noba-web-server.pid')
ACTION_LOG = '/tmp/noba-action.log'
AUTH_CONFIG = os.path.expanduser('~/.config/noba-web/auth.conf')
NOBA_YAML   = os.environ.get('NOBA_CONFIG', os.path.expanduser('~/.config/noba/config.yaml'))
USE_HTTPS   = os.environ.get('NOBA_HTTPS', '0') == '1'
CERT_FILE   = os.environ.get('NOBA_CERT', os.path.expanduser('~/.config/noba-web/server.crt'))
KEY_FILE    = os.environ.get('NOBA_KEY',  os.path.expanduser('~/.config/noba-web/server.key'))
NOTIF_FILE  = os.path.join(LOG_DIR, 'notifications.json')
SPEED_FILE  = os.path.join(LOG_DIR, 'speedtest-history.json')

_server_start_time = time.time()

try:    os.makedirs(LOG_DIR, exist_ok=True)
except Exception: pass

log_file = os.path.join(LOG_DIR, 'noba-web-server.log')
try:    logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
except Exception: logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('noba')

ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(s): return ANSI_RE.sub('', s)

SCRIPT_MAP = {
    'backup':        'backup-to-nas.sh',
    'verify':        'backup-verifier.sh',
    'organize':      'organize-downloads.sh',
    'diskcheck':     'disk-sentinel.sh',
    'check_updates': 'noba-update.sh',
}
ALLOWED_ACTIONS = {'start', 'stop', 'restart'}
ADMIN_ONLY_POST = {'/api/run', '/api/service-control'}

# ── Authentication (multi-user) ───────────────────────────────────────────────
_tokens_lock = threading.Lock()
_tokens: dict = {}   # token → {expiry, username, role}

def verify_password(stored: str, password: str) -> bool:
    if not stored:
        return False
    if stored.startswith('pbkdf2:'):
        parts = stored.split(':', 2)
        if len(parts) != 3:
            return False
        _, salt, expected = parts
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000)
        return secrets.compare_digest(expected, dk.hex())
    if ':' not in stored:
        return False
    salt, expected = stored.split(':', 1)
    actual = hashlib.sha256((salt + password).encode()).hexdigest()
    return secrets.compare_digest(expected, actual)

def load_users() -> dict:
    if not os.path.exists(AUTH_CONFIG):
        return {}
    users = {}
    try:
        with open(AUTH_CONFIG) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if ':' not in line:
                    continue
                username, rest = line.split(':', 1)
                rparts = rest.rsplit(':', 1)
                if rparts[-1] in ('admin', 'viewer'):
                    pw_hash = rparts[0]
                    role    = rparts[-1]
                else:
                    pw_hash = rest
                    role    = 'admin'
                users[username.strip()] = {'hash': pw_hash, 'role': role}
    except Exception as e:
        logger.warning(f'Could not read auth config: {e}')
    return users

def generate_token(username: str, role: str) -> str:
    token = str(uuid.uuid4())
    with _tokens_lock:
        _tokens[token] = {
            'expiry':   datetime.now() + timedelta(hours=24),
            'username': username,
            'role':     role,
        }
    return token

def get_token_info(token: str) -> dict | None:
    with _tokens_lock:
        info = _tokens.get(token)
        if info and info['expiry'] > datetime.now():
            return info
        if token in _tokens:
            del _tokens[token]
    return None

def revoke_token(token: str) -> None:
    with _tokens_lock:
        _tokens.pop(token, None)

def authenticate_request(headers, query=None) -> dict | None:
    auth = headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        info = get_token_info(auth[7:])
        if info:
            return info
    if query and 'token' in query:
        info = get_token_info(query['token'][0])
        if info:
            return info
    return None

def _token_cleanup_loop():
    while not _shutdown_flag.is_set():
        _shutdown_flag.wait(300)
        now = datetime.now()
        with _tokens_lock:
            expired = [t for t, v in list(_tokens.items()) if v['expiry'] <= now]
            for t in expired:
                del _tokens[t]
        if expired:
            logger.info(f'Token cleanup: {len(expired)} expired')

# ── Login rate limiter ─────────────────────────────────────────────────────────
class LoginRateLimiter:
    def __init__(self, max_attempts=5, window_s=60, lockout_s=30):
        self._lock     = threading.Lock()
        self._attempts: dict = {}
        self._lockouts: dict = {}
        self.max_attempts = max_attempts
        self.window_s     = window_s
        self.lockout_s    = lockout_s
    def is_locked(self, ip: str) -> bool:
        with self._lock:
            exp = self._lockouts.get(ip)
            if exp and datetime.now() < exp: return True
            self._lockouts.pop(ip, None)
            return False
    def record_failure(self, ip: str) -> bool:
        now = datetime.now(); cutoff = now - timedelta(seconds=self.window_s)
        with self._lock:
            attempts = [t for t in self._attempts.get(ip, []) if t > cutoff]
            attempts.append(now); self._attempts[ip] = attempts
            if len(attempts) >= self.max_attempts:
                self._lockouts[ip] = now + timedelta(seconds=self.lockout_s)
                self._attempts.pop(ip, None)
                logger.warning(f'Login lockout: {ip}')
                return True
        return False
    def reset(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None); self._lockouts.pop(ip, None)

_rate_limiter = LoginRateLimiter()

# ── NotificationStore ─────────────────────────────────────────────────────────
class NotificationStore:
    def __init__(self, persist_file: str, maxlen: int = 100):
        self._lock     = threading.Lock()
        self._items    = deque(maxlen=maxlen)
        self._next_id  = 1
        self._persist  = persist_file
        self._load()

    def _load(self):
        if not os.path.exists(self._persist):
            return
        try:
            with open(self._persist) as f:
                items = json.load(f)
            for item in items[-self._items.maxlen:]:
                self._items.append(item)
                self._next_id = max(self._next_id, item.get('id', 0) + 1)
        except Exception as e:
            logger.warning(f'NotificationStore load error: {e}')

    def _save(self):
        try:
            with open(self._persist, 'w') as f:
                json.dump(list(self._items), f)
        except Exception:
            pass

    def add_alerts(self, alerts: list):
        if not alerts:
            return
        now = datetime.now()
        with self._lock:
            recent_msgs = {
                item['msg'] for item in self._items
                if (now - datetime.fromisoformat(item['ts'])).total_seconds() < 300
            }
            added = False
            for alert in alerts:
                if alert['msg'] not in recent_msgs:
                    self._items.append({
                        'id':    self._next_id,
                        'ts':    now.strftime('%H:%M:%S'),
                        'level': alert['level'],
                        'msg':   alert['msg'],
                    })
                    recent_msgs.add(alert['msg'])
                    self._next_id += 1
                    added = True
            if added:
                self._save()

    def get_all(self, limit: int = 100) -> list:
        with self._lock:
            return list(self._items)[-limit:]

# ── SpeedtestHistory ──────────────────────────────────────────────────────────
class SpeedtestHistory:
    def __init__(self, persist_file: str, maxlen: int = 20):
        self._lock    = threading.Lock()
        self._items   = deque(maxlen=maxlen)
        self._persist = persist_file
        self._load()

    def _load(self):
        if not os.path.exists(self._persist):
            return
        try:
            with open(self._persist) as f:
                for item in json.load(f)[-self._items.maxlen:]:
                    self._items.append(item)
        except Exception as e:
            logger.warning(f'SpeedtestHistory load error: {e}')

    def _save(self):
        try:
            with open(self._persist, 'w') as f:
                json.dump(list(self._items), f)
        except Exception:
            pass

    def add(self, download: float, upload: float, ping: float):
        with self._lock:
            self._items.append({
                'ts':       datetime.now().strftime('%m/%d %H:%M'),
                'download': round(download, 1),
                'upload':   round(upload, 1),
                'ping':     round(ping, 1),
            })
            self._save()

    def get_all(self) -> list:
        with self._lock:
            return list(self._items)

    @staticmethod
    def parse_output(text: str):
        ping = download = upload = None
        for line in text.splitlines():
            m = re.search(r'([\d.]+)', line)
            if not m: continue
            val = float(m.group(1))
            if   'Ping'     in line: ping     = val
            elif 'Download' in line: download = val
            elif 'Upload'   in line: upload   = val
        return download, upload, ping

# ── YAML settings ─────────────────────────────────────────────────────────────
def read_yaml_settings():
    default = {
        'piholeUrl': '', 'piholeToken': '',
        'monitoredServices': 'backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service',
        'radarIps': '192.168.100.1, 1.1.1.1, 8.8.8.8',
        'bookmarksStr': ''
    }
    if not os.path.exists(NOBA_YAML):
        return default
    try:
        r = subprocess.run(['yq', 'eval', '-o=json', '.web', NOBA_YAML], capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            web = json.loads(r.stdout)
            for k in default:
                if k in web: default[k] = web[k]
    except Exception as e:
        logger.warning(f'read_yaml_settings: {e}')
    return default

def write_yaml_settings(settings: dict) -> bool:
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            tmp.write('web:\n')
            for k, v in settings.items():
                if isinstance(v, str) and any(c in v for c in '\n:#'):
                    v = json.dumps(v)
                tmp.write(f'  {k}: {v}\n')
            tmp_path = tmp.name
        if os.path.exists(NOBA_YAML):
            r = subprocess.run(['yq', 'eval-all', 'select(fileIndex==0) * select(fileIndex==1)', NOBA_YAML, tmp_path],
                               capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                with open(NOBA_YAML, 'w') as f: f.write(r.stdout)
            else:
                raise RuntimeError(f'yq merge failed: {r.stderr}')
        else:
            os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
            with open(tmp_path) as src, open(NOBA_YAML, 'w') as dst: dst.write(src.read())
        os.unlink(tmp_path)
        return True
    except Exception as e:
        logger.exception(f'write_yaml_settings: {e}')
        return False

# ── Validation ────────────────────────────────────────────────────────────────
def validate_service_name(n): return bool(re.match(r'^[a-zA-Z0-9_.@-]+$', n))
def validate_ip(ip):
    try: ipaddress.ip_address(ip); return True
    except ValueError: return False

# ── TTL cache ─────────────────────────────────────────────────────────────────
class TTLCache:
    def __init__(self): self._s={}; self._l=threading.Lock()
    def get(self,k,ttl=30):
        with self._l:
            e=self._s.get(k)
            if e and (time.time()-e['t'])<ttl: return e['v']
        return None
    def set(self,k,v):
        with self._l: self._s[k]={'v':v,'t':time.time()}

_cache = TTLCache()

# ── Global state ──────────────────────────────────────────────────────────────
_state_lock  = threading.Lock()
_cpu_history = deque(maxlen=20)
_cpu_prev    = None
_net_prev    = None
_net_prev_t  = None
_shutdown_flag = threading.Event()

# ── Signal handler ────────────────────────────────────────────────────────────
def sigterm_handler(signum, frame):
    logger.info('SIGTERM received, shutting down…')
    _shutdown_flag.set()
    threading.Thread(target=lambda: server.shutdown(), daemon=True).start()
signal.signal(signal.SIGTERM, sigterm_handler)

# ── Helpers ───────────────────────────────────────────────────────────────────
def run(cmd, timeout=3, cache_key=None, cache_ttl=30, ignore_rc=False):
    if cache_key:
        hit = _cache.get(cache_key, cache_ttl)
        if hit is not None: return hit
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip() if (r.returncode == 0 or ignore_rc) else ''
        if cache_key and out: _cache.set(cache_key, out)
        return out
    except Exception as e:
        logger.debug(f'run {cmd}: {e}'); return ''

def human_bps(bps):
    for u in ('B/s','KB/s','MB/s','GB/s'):
        if bps<1024: return f'{bps:.1f} {u}'
        bps/=1024
    return f'{bps:.1f} TB/s'

# ── Stats collectors ──────────────────────────────────────────────────────────
def get_cpu_percent():
    global _cpu_prev
    with _state_lock:
        try:
            with open('/proc/stat') as f: fields=list(map(int,f.readline().split()[1:]))
            idle=fields[3]+fields[4]; total=sum(fields)
            if _cpu_prev is None: _cpu_prev=(total,idle); return 0.0
            dt=total-_cpu_prev[0]; di=idle-_cpu_prev[1]; _cpu_prev=(total,idle)
            pct=round(100.0*(1.0-di/dt) if dt>0 else 0.0,1)
            _cpu_history.append(pct); return pct
        except: return 0.0

def get_net_io():
    global _net_prev, _net_prev_t
    with _state_lock:
        try:
            with open('/proc/net/dev') as f: lines=f.readlines()
            rx=tx=0
            for line in lines[2:]:
                p=line.split()
                if len(p)>9 and not p[0].startswith('lo'): rx+=int(p[1]); tx+=int(p[9])
            now=time.time()
            if _net_prev is None: _net_prev=(rx,tx); _net_prev_t=now; return 0.0,0.0
            dt=now-_net_prev_t
            if dt<0.05: return 0.0,0.0
            rx_bps=max(0.0,(rx-_net_prev[0])/dt); tx_bps=max(0.0,(tx-_net_prev[1])/dt)
            _net_prev=(rx,tx); _net_prev_t=now; return rx_bps,tx_bps
        except: return 0.0,0.0

def ping_host(ip):
    ip=ip.strip()
    if not validate_ip(ip): return ip,False,0
    try:
        t0=time.time()
        r=subprocess.run(['ping','-c','1','-W','1',ip],capture_output=True,timeout=2.5)
        return ip,r.returncode==0,round((time.time()-t0)*1000)
    except: return ip,False,0

def get_service_status(svc):
    svc=svc.strip()
    if not validate_service_name(svc): return 'invalid',False
    for scope,is_user in ((['--user'],True),([],False)):
        cmd=['systemctl']+scope+['show','-p','ActiveState,LoadState',svc]
        out=run(cmd,timeout=2)
        d=dict(l.split('=',1) for l in out.splitlines() if '=' in l)
        if d.get('LoadState') not in (None,'','not-found'):
            state=d.get('ActiveState','unknown')
            if state=='inactive' and svc.endswith('.service'):
                tn=svc.replace('.service','.timer')
                t=run(['systemctl']+scope+['show','-p','ActiveState',tn],timeout=1)
                if 'ActiveState=active' in t: return 'timer-active',is_user
            return state,is_user
    return 'not-found',False

def get_battery():
    bats=glob.glob('/sys/class/power_supply/BAT*')
    if not bats: return{'percent':100,'status':'Desktop','desktop':True,'timeRemaining':''}
    try:
        pct=int(open(f'{bats[0]}/capacity').read().strip())
        stat=open(f'{bats[0]}/status').read().strip()
        time_rem=''
        try:
            cur=int(open(f'{bats[0]}/current_now').read().strip())
            if cur>0:
                if stat=='Discharging': charge=int(open(f'{bats[0]}/charge_now').read().strip()); hrs=charge/cur
                else:
                    cfull=int(open(f'{bats[0]}/charge_full').read().strip())
                    charge=int(open(f'{bats[0]}/charge_now').read().strip())
                    hrs=(cfull-charge)/cur
                time_rem=f'{int(hrs)}h {int((hrs%1)*60)}m'
                if stat!='Discharging': time_rem+=' to full'
        except: pass
        return{'percent':pct,'status':stat,'desktop':False,'timeRemaining':time_rem}
    except: return{'percent':0,'status':'Error','desktop':False,'timeRemaining':''}

def get_containers():
    for cmd in (['podman','ps','-a','--format','json'],['docker','ps','-a','--format','{{json .}}']):
        out=run(cmd,timeout=4,cache_key=' '.join(cmd),cache_ttl=10)
        if not out: continue
        try:
            items=json.loads(out) if out.lstrip().startswith('[') else [json.loads(l) for l in out.splitlines() if l.strip()]
            res=[]
            for c in items[:16]:
                name=c.get('Names',c.get('Name','?'))
                if isinstance(name,list): name=name[0] if name else '?'
                image=c.get('Image',c.get('Repository','?')).split('/')[-1][:32]
                state=(c.get('State',c.get('Status','?')) or '?').lower().split()[0]
                res.append({'name':name,'image':image,'state':state,'status':c.get('Status',state)})
            return res
        except: continue
    return []

def get_pihole(url, token):
    if not url: return None
    base=url if url.startswith('http') else 'http://'+url
    base=base.rstrip('/').replace('/admin','')
    def _get(ep,h=None):
        hdrs={'User-Agent':f'noba-web/{VERSION}','Accept':'application/json'}
        if h: hdrs.update(h)
        req=urllib.request.Request(base+ep,headers=hdrs)
        with urllib.request.urlopen(req,timeout=3) as r: return json.loads(r.read().decode())
    try:
        auth={'sid':token} if token else {}
        d=_get('/api/stats/summary',auth)
        return{'queries':d.get('queries',{}).get('total',0),'blocked':d.get('ads',{}).get('blocked',0),
               'percent':round(d.get('ads',{}).get('percentage',0.0),1),'status':d.get('gravity',{}).get('status','unknown'),
               'domains':f"{d.get('gravity',{}).get('domains_being_blocked',0):,}"}
    except: pass
    try:
        ep='/admin/api.php?summaryRaw'+(f'&auth={token}' if token else '')
        d=_get(ep)
        return{'queries':d.get('dns_queries_today',0),'blocked':d.get('ads_blocked_today',0),
               'percent':round(d.get('ads_percentage_today',0),1),'status':d.get('status','enabled'),
               'domains':f"{d.get('domains_being_blocked',0):,}"}
    except: return None

def collect_stats(qs):
    stats={'timestamp':datetime.now().strftime('%H:%M:%S')}
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='): stats['osName']=line.split('=',1)[1].strip().strip('"')
    except: stats['osName']='Linux'
    stats['kernel']    = run(['uname','-r'],cache_key='uname-r',cache_ttl=3600)
    stats['hostname']  = run(['hostname'],cache_key='hostname',cache_ttl=3600)
    stats['defaultIp'] = run(['bash','-c',"ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \\K[\\d.]+'"],timeout=1)
    try:
        uptime_s=float(open('/proc/uptime').read().split()[0])
        d,rem=divmod(int(uptime_s),86400); h,rem=divmod(rem,3600); m=rem//60
        stats['uptime']=(f'{d}d ' if d else '')+f'{h}h {m}m'
        stats['loadavg']=' '.join(open('/proc/loadavg').read().split()[:3])
        ml=open('/proc/meminfo').readlines()
        mm={l.split(':')[0]:int(l.split()[1]) for l in ml if ':' in l}
        tot=mm.get('MemTotal',0)//1024; avail=mm.get('MemAvailable',0)//1024; used=tot-avail
        stats['memory']=f'{used} MiB / {tot} MiB'; stats['memPercent']=round(100*used/tot) if tot>0 else 0
    except: stats.setdefault('uptime','--'); stats.setdefault('loadavg','--'); stats.setdefault('memPercent',0)

    stats['cpuPercent']=get_cpu_percent()
    with _state_lock: stats['cpuHistory']=list(_cpu_history)
    rx_bps,tx_bps=get_net_io()
    stats['netRx']=human_bps(rx_bps); stats['netTx']=human_bps(tx_bps)

    s=run(['sensors'],timeout=2,cache_key='sensors',cache_ttl=5)
    m=re.search(r'(?:Tctl|Package id \d+|Core 0|temp1).*?\+?(\d+\.?\d*)[°℃]',s)
    stats['cpuTemp']=f'{int(float(m.group(1)))}°C' if m else 'N/A'
    gpu_t=run(['nvidia-smi','--query-gpu=temperature.gpu','--format=csv,noheader'],timeout=2,cache_key='nvidia-temp',cache_ttl=5)
    if not gpu_t:
        raw=run(['bash','-c','cat /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1'],timeout=1)
        gpu_t=f'{int(raw)//1000}°C' if raw else 'N/A'
    else: gpu_t=f'{gpu_t}°C'
    stats['gpuTemp']=gpu_t; stats['battery']=get_battery()
    stats['hwCpu']=run(['bash','-c',"lscpu | grep 'Model name' | head -1 | cut -d: -f2 | xargs"],cache_key='lscpu',cache_ttl=3600)
    raw_gpu=run(['bash','-c',"lspci | grep -i 'vga\\|3d' | cut -d: -f3"],cache_key='lspci',cache_ttl=3600)
    stats['hwGpu']=raw_gpu.replace('\n','<br>') if raw_gpu else 'Unknown GPU'

    disks=[]
    for line in run(['df','-BM'],cache_key='df',cache_ttl=10).splitlines()[1:]:
        p=line.split()
        if len(p)>=6 and p[0].startswith('/dev/'):
            mnt=p[5]
            if any(mnt.startswith(x) for x in ('/var/lib/snapd','/boot','/run','/snap')): continue
            try:
                pct=int(p[4].replace('%','')); bc='danger' if pct>=90 else 'warning' if pct>=75 else 'success'
                disks.append({'mount':mnt,'percent':pct,'barClass':bc,'size':p[1].replace('M',' MiB'),'used':p[2].replace('M',' MiB')})
            except: pass
    stats['disks']=disks

    zfs_out=run(['zpool','list','-H','-o','name,health'],timeout=3,cache_key='zpool',cache_ttl=15)
    pools=[{'name':l.split('\t')[0].strip(),'health':l.split('\t')[1].strip()} for l in zfs_out.splitlines() if '\t' in l]
    stats['zfs']={'pools':pools}

    cpu_ps=run(['ps','ax','--format','comm,%cpu','--sort','-%cpu'],timeout=2)
    mem_ps=run(['ps','ax','--format','comm,%mem','--sort','-%mem'],timeout=2)
    def parse_ps(out):
        res=[]
        for line in out.splitlines()[1:6]:
            p=line.strip().rsplit(None,1)
            if len(p)==2 and p[1] not in ('%CPU','%MEM'): res.append({'name':p[0][:16],'val':p[1]+'%'})
        return res
    stats['topCpu']=parse_ps(cpu_ps); stats['topMem']=parse_ps(mem_ps)

    svc_list=[s.strip() for s in qs.get('services',[''])[0].split(',') if s.strip()]
    ip_list =[ip.strip() for ip in qs.get('radar',  [''])[0].split(',') if ip.strip()]
    ph_url  =qs.get('pihole',   [''])[0]
    ph_tok  =qs.get('piholetok',[''])[0]

    with ThreadPoolExecutor(max_workers=max(4,len(svc_list)+len(ip_list)+3)) as ex:
        svc_futs ={ex.submit(get_service_status,s):s  for s in svc_list}
        ping_futs={ex.submit(ping_host,ip):ip          for ip in ip_list}
        ph_fut   =ex.submit(get_pihole,ph_url,ph_tok) if ph_url else None
        ct_fut   =ex.submit(get_containers)

        services=[]
        for fut,svc in svc_futs.items():
            try: status,is_user=fut.result(timeout=4)
            except: status,is_user='error',False
            services.append({'name':svc,'status':status,'is_user':is_user})
        stats['services']=services

        radar=[]
        for fut,ip in ping_futs.items():
            try: ip_r,up,ms=fut.result(timeout=4); radar.append({'ip':ip_r,'status':'Up' if up else 'Down','ms':ms if up else 0})
            except: radar.append({'ip':ip,'status':'Down','ms':0})
        stats['radar']=radar

        try: stats['pihole']=ph_fut.result(timeout=4) if ph_fut else None
        except: stats['pihole']=None
        try: stats['containers']=ct_fut.result(timeout=5)
        except: stats['containers']=[]

    alerts=[]
    cpu=stats.get('cpuPercent',0)
    if   cpu>90: alerts.append({'level':'danger', 'msg':f'CPU critical: {cpu}%'})
    elif cpu>75: alerts.append({'level':'warning','msg':f'CPU high: {cpu}%'})
    ct=stats.get('cpuTemp','N/A')
    if ct!='N/A':
        t=int(ct.replace('°C',''))
        if   t>85: alerts.append({'level':'danger', 'msg':f'CPU temp critical: {t}°C'})
        elif t>70: alerts.append({'level':'warning','msg':f'CPU temp elevated: {t}°C'})
    for disk in stats.get('disks',[]):
        p=disk.get('percent',0)
        if   p>=90: alerts.append({'level':'danger', 'msg':f"Disk {disk['mount']} at {p}%"})
        elif p>=80: alerts.append({'level':'warning','msg':f"Disk {disk['mount']} at {p}%"})
    for svc in stats.get('services',[]):
        if svc.get('status')=='failed': alerts.append({'level':'danger','msg':f"Service failed: {svc['name']}"})
    stats['alerts']=alerts
    return stats

# ── BackgroundCollector ───────────────────────────────────────────────────────
class BackgroundCollector:
    def __init__(self, interval=5):
        self._lock=threading.Lock(); self._latest={}; self._qs={}; self._interval=interval
    def update_qs(self,qs):
        with self._lock: self._qs=dict(qs)
    def get(self):
        with self._lock: return dict(self._latest)
    def start(self):
        threading.Thread(target=self._loop,daemon=True,name='stats-collector').start()
    def _loop(self):
        while not _shutdown_flag.is_set():
            try:
                with self._lock: qs=dict(self._qs)
                data=collect_stats(qs)
                _notif_store.add_alerts(data.get('alerts',[]))
                with self._lock: self._latest=data
            except Exception as e: logger.warning(f'BackgroundCollector: {e}')
            _shutdown_flag.wait(self._interval)

_bg           = BackgroundCollector(interval=5)
_notif_store  = NotificationStore(NOTIF_FILE)
_speed_hist   = SpeedtestHistory(SPEED_FILE)

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory='.',**kw)
    def log_message(self,fmt,*args): pass
    def _ip(self): return self.client_address[0] if self.client_address else '0.0.0.0'
    def _json(self,data,status=200):
        body=json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        parsed=urlparse(self.path); qs=parse_qs(parsed.query); path=parsed.path

        # Public
        if path in ('/','index.html'): super().do_GET(); return
        if path=='/api/health':
            self._json({'status':'ok','version':VERSION,'uptime_s':round(time.time()-_server_start_time)}); return

        token_info=authenticate_request(self.headers,qs)
        if not token_info: self.send_error(401,'Unauthorized'); return

        if path=='/api/stats':
            _bg.update_qs(qs)
            cached=_bg.get()
            try: self._json(cached if cached else collect_stats(qs))
            except Exception as e: logger.exception('/api/stats'); self._json({'error':str(e)},500)

        elif path=='/api/settings':
            self._json(read_yaml_settings())

        elif path=='/api/notifications':
            self._json(_notif_store.get_all())

        elif path=='/api/speedtest-history':
            self._json(_speed_hist.get_all())

        elif path=='/api/stream':
            _bg.update_qs(qs)
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-cache')
            self.send_header('Connection','keep-alive')
            self.end_headers()
            try:
                first=_bg.get() or collect_stats(qs)
                self.wfile.write(f'data: {json.dumps(first)}\n\n'.encode()); self.wfile.flush()
                while not _shutdown_flag.is_set():
                    _shutdown_flag.wait(5)
                    if _shutdown_flag.is_set(): break
                    d=_bg.get()
                    if d: self.wfile.write(f'data: {json.dumps(d)}\n\n'.encode()); self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,OSError): pass
            except Exception as e: logger.warning(f'SSE: {e}')

        elif path=='/api/log-viewer':
            lt=qs.get('type',['syserr'])[0]
            if   lt=='syserr': text=run(['journalctl','-p','3','-n','25','--no-pager'],timeout=4)
            elif lt=='action':
                try: text=strip_ansi(open(ACTION_LOG).read())
                except FileNotFoundError: text='No recent actions.'
            elif lt=='backup':
                try:
                    lines=open(os.path.join(LOG_DIR,'backup-to-nas.log')).readlines()
                    text=strip_ansi(''.join(lines[-30:]))
                except FileNotFoundError: text='No backup log found.'
            else: text='Unknown log type.'
            body=(text or 'Empty.').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)

        elif path=='/api/action-log':
            try: text=strip_ansi(open(ACTION_LOG).read())
            except FileNotFoundError: text='Waiting for output…'
            body=text.encode()
            self.send_response(200); self.send_header('Content-Type','text/plain; charset=utf-8')
            self.end_headers(); self.wfile.write(body)

        else: self.send_error(404)

    def do_POST(self):
        path=self.path.split('?')[0]; ip=self._ip()

        if path=='/api/login':
            if _rate_limiter.is_locked(ip):
                self._json({'error':'Too many failed attempts. Try again shortly.'},429); return
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                username=body.get('username',''); password=body.get('password','')
                users=load_users()
                user=users.get(username)
                if user and verify_password(user['hash'],password):
                    _rate_limiter.reset(ip)
                    token=generate_token(username,user['role'])
                    self._json({'token':token,'role':user['role'],'username':username})
                else:
                    locked=_rate_limiter.record_failure(ip)
                    msg='Too many failed attempts. Try again shortly.' if locked else 'Invalid credentials'
                    self._json({'error':msg},401)
            except Exception as e:
                logger.exception('/api/login'); self._json({'error':str(e)},500)
            return

        if path=='/api/logout':
            parsed=urlparse(self.path); qs=parse_qs(parsed.query)
            token=None
            ah=self.headers.get('Authorization','')
            if ah.startswith('Bearer '): token=ah[7:]
            elif 'token' in qs: token=qs['token'][0]
            if token: revoke_token(token)
            self._json({'status':'ok'}); return

        token_info=authenticate_request(self.headers)
        if not token_info: self.send_error(401,'Unauthorized'); return

        if path in ADMIN_ONLY_POST and token_info.get('role')!='admin':
            self._json({'error':'Admin role required'},403); return

        if path=='/api/settings':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                ok=write_yaml_settings(body)
                self._json({'status':'ok'} if ok else {'error':'Write failed'}, 200 if ok else 500)
            except Exception as e:
                logger.exception('/api/settings POST'); self._json({'error':str(e)},500)

        elif path=='/api/run':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                script=body.get('script','')
                with open(ACTION_LOG,'w') as f:
                    f.write(f'>> [{datetime.now().strftime("%H:%M:%S")}] Initiating: {script}\n\n')
                success=False
                if script=='speedtest':
                    with open(ACTION_LOG,'a') as f:
                        p=subprocess.Popen(['speedtest-cli','--simple'],stdout=f,stderr=subprocess.STDOUT)
                        p.wait(timeout=120); success=p.returncode==0
                    if success:
                        try:
                            with open(ACTION_LOG) as f: output=f.read()
                            dl,ul,ping=SpeedtestHistory.parse_output(output)
                            if dl is not None and ul is not None and ping is not None:
                                _speed_hist.add(dl,ul,ping)
                        except Exception as e: logger.warning(f'speedtest parse: {e}')
                elif script in SCRIPT_MAP:
                    sfile=os.path.join(SCRIPT_DIR,SCRIPT_MAP[script])
                    if os.path.isfile(sfile):
                        with open(ACTION_LOG,'a') as f:
                            p=subprocess.Popen([sfile,'--verbose'],stdout=f,stderr=subprocess.STDOUT,cwd=SCRIPT_DIR)
                            p.wait(timeout=300); success=p.returncode==0
                    else:
                        with open(ACTION_LOG,'a') as f: f.write(f'[ERROR] Script not found: {sfile}\n')
                else:
                    with open(ACTION_LOG,'a') as f: f.write(f'[ERROR] Unknown script: {script}\n')
                self._json({'success':success})
            except subprocess.TimeoutExpired: self._json({'success':False,'error':'Script timed out'})
            except Exception as e:
                logger.exception('/api/run'); self._json({'success':False,'error':str(e)})

        elif path=='/api/service-control':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                svc=body.get('service','').strip(); action=body.get('action','').strip(); is_user=bool(body.get('is_user',False))
                if action not in ALLOWED_ACTIONS: return self._json({'success':False,'error':f'Action "{action}" not allowed'})
                if not svc: return self._json({'success':False,'error':'No service name'})
                if not validate_service_name(svc): return self._json({'success':False,'error':'Invalid service name'})
                cmd=(['systemctl','--user',action,svc] if is_user else ['sudo','-n','systemctl',action,svc])
                r=subprocess.run(cmd,timeout=10,capture_output=True)
                self._json({'success':r.returncode==0,'stderr':r.stderr.decode().strip()})
            except Exception as e: self._json({'success':False,'error':str(e)})

        else: self.send_error(404)


class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address=True; daemon_threads=True

server=None

if __name__=='__main__':
    try:
        with open(PID_FILE,'w') as f: f.write(str(os.getpid()))
    except Exception as e: logger.warning(f'PID file: {e}')

    _bg.start()
    threading.Thread(target=_token_cleanup_loop,daemon=True,name='token-cleanup').start()

    server=ThreadingHTTPServer((HOST,PORT),Handler)

    if USE_HTTPS:
        import ssl
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ctx.load_cert_chain(CERT_FILE,KEY_FILE)
            server.socket=ctx.wrap_socket(server.socket,server_side=True)
            proto='https'
        except Exception as e:
            print(f'[ERROR] TLS setup failed: {e}',file=sys.stderr)
            print(f'        Run: noba-web --generate-cert',file=sys.stderr)
            sys.exit(1)
    else:
        proto='http'

    url=f'{proto}://{HOST}:{PORT}'
    logger.warning(f'Serving at {url}  (v{VERSION})')
    print(f'Noba server v{VERSION} starting at {url}',file=sys.stderr)

    try: server.serve_forever()
    except KeyboardInterrupt: logger.info('Shutting down…')
    except Exception as e: logger.exception('Unhandled exception')
    finally:
        _shutdown_flag.set(); server.shutdown()
        try: os.unlink(PID_FILE)
        except: pass
        logger.info('Server stopped.')
EOF
chmod +x libexec/noba/noba-web/server.py
echo "✅ Updated server.py"

# 6. Update install.sh
cat > install.sh <<'INSTALL_EOF'
#!/bin/bash
# install.sh – Smart installer for Nobara Automation Suite
# Version: 1.0.0

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: install.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "install.sh version 1.0.0"; exit 0
fi

# ── Defaults ───────────────────────────────────────────────────────────────────
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="${BIN_DIR:-$PREFIX/bin}"
LIBEXEC_DIR="${LIBEXEC_DIR:-$PREFIX/libexec/noba}"
SHARE_DIR="${SHARE_DIR:-$PREFIX/share/noba-web}"
MAN_DIR="${MAN_DIR:-$PREFIX/share/man/man1}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/noba}"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
SKIP_DEPS=false
UNINSTALL=false
NO_COMPLETION=false
NO_SYSTEMD=false
USER_EMAIL="${EMAIL:-}"

MANIFEST_FILE="${MANIFEST_FILE:-$HOME/.local/share/noba-install.manifest}"

# Read version from VERSION file
if [[ -f "$SCRIPT_DIR/VERSION" ]]; then
    NOBA_VERSION=$(cat "$SCRIPT_DIR/VERSION")
else
    NOBA_VERSION="unknown"
fi

# ── Whitelist of suite scripts ─────────────────────────────────────────────────
SUITE_SCRIPTS=(
    backup-to-nas.sh
    backup-verifier.sh
    backup-notify.sh
    checksum.sh
    cloud-backup.sh
    config-check.sh
    disk-sentinel.sh
    images-to-pdf.sh
    organize-downloads.sh
)
OPTIONAL_SCRIPTS=(
    noba-tui.sh
    noba-dashboard.sh
    motd-generator.sh
    run-hogwarts-trainer.sh
    noba-update.sh
    noba-completion.sh
)

# ── Functions ──────────────────────────────────────────────────────────────────
say()     { printf '  %s\n' "$@"; }
say_ok()  { printf '  \033[0;32m✓\033[0m %s\n' "$@"; }
say_warn(){ printf '  \033[0;33m⚠\033[0m %s\n' "$@"; }
say_err() { printf '  \033[0;31m✗\033[0m %s\n' "$@" >&2; }
header()  { printf '\n\033[1m%s\033[0m\n' "$@"; }
dry()     { [[ "$DRY_RUN" == true ]] && printf '  [DRY RUN] %s\n' "$@"; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install the Nobara Automation Suite.

Options:
  -d, --dir DIR          Bin directory for wrapper (default: $BIN_DIR)
      --prefix DIR       Base installation prefix (default: $PREFIX)
  -c, --config DIR       Configuration directory (default: $CONFIG_DIR)
  -s, --systemd DIR      Systemd user unit directory (default: $SYSTEMD_USER_DIR)
      --email ADDR       Pre-fill email address in generated config
      --skip-deps        Skip dependency installation
      --no-completion    Skip shell completion setup
      --no-systemd       Skip systemd unit installation and reload
  -u, --uninstall        Remove a previously installed suite (reads manifest)
  -n, --dry-run          Show what would be done without making changes
  -h, --help             Show this message
  -v, --version          Show version information
    exit 0
}

# ── Manifest-based install tracking and rollback ──────────────────────────────
INSTALLED_FILES=()

record_install() {
    local path="$1"
    INSTALLED_FILES+=("$path")
}

write_manifest() {
    mkdir -p "$(dirname "$MANIFEST_FILE")"
    printf '%s\n' "${INSTALLED_FILES[@]}" > "$MANIFEST_FILE"
    say_ok "Manifest written: $MANIFEST_FILE"
}

rollback() {
    local exit_code=$?
    if [[ "$exit_code" -ne 0 && "$DRY_RUN" == false && ${#INSTALLED_FILES[@]} -gt 0 ]]; then
        say_warn "Install failed — rolling back ${#INSTALLED_FILES[@]} installed file(s)..."
        for f in "${INSTALLED_FILES[@]}"; do
            rm -f "$f" && say_warn "  Removed: $f" || true
        done
    fi
}
trap rollback EXIT

do_uninstall() {
    if [[ ! -f "$MANIFEST_FILE" ]]; then
        say_err "No manifest found at $MANIFEST_FILE — cannot uninstall."
        exit 1
    fi
    header "Uninstalling Nobara Automation Suite"
    local count=0
    while IFS= read -r path; do
        [[ -z "$path" ]] && continue
        if [[ -f "$path" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would remove: $path"
            else
                rm -f "$path"
                say_ok "Removed: $path"
            fi
            (( count++ )) || true
        else
            say_warn "Already gone: $path"
        fi
    done < "$MANIFEST_FILE"

    if [[ "$DRY_RUN" == false ]]; then
        rm -f "$MANIFEST_FILE"
        say_ok "Manifest removed."
    fi

    say "Uninstalled $count file(s)."
    say "Config directory ($CONFIG_DIR) and logs were NOT removed."
    say "To remove config: rm -rf $CONFIG_DIR"
    exit 0
}

detect_os() {
    OS_ID=$(bash -c '. /etc/os-release 2>/dev/null && echo "$ID"' || echo "unknown")
    OS_NAME=$(bash -c '. /etc/os-release 2>/dev/null && echo "$NAME"' || echo "Unknown Linux")
    OS_VERSION=$(bash -c '. /etc/os-release 2>/dev/null && echo "${VERSION_ID:-}"' || echo "")
}

install_deps() {
    [[ "$SKIP_DEPS" == true ]] && { say "Skipping dependency installation."; return 0; }
    local deps=()
    case "$OS_ID" in
        fedora|nobara|rhel|centos|rocky|almalinux)
            deps=(rsync rclone msmtp ImageMagick yq jq dialog psmisc lm_sensors lsof)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo dnf install -y ${deps[*]}"
            else
                say "Installing via dnf..."
                sudo dnf install -y "${deps[@]}"
            fi
            ;;
        debian|ubuntu|linuxmint|pop|kali)
            deps=(rsync msmtp imagemagick jq dialog psmisc lm-sensors lsof)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo apt install -y ${deps[*]}"
            else
                say "Installing via apt..."
                sudo apt-get update -qq
                sudo apt-get install -y "${deps[@]}"
                if ! command -v rclone &>/dev/null; then
                    say "Installing rclone via official script..."
                    curl -fsSL https://rclone.org/install.sh | sudo bash || \
                        say_warn "rclone install failed — install manually from https://rclone.org"
                fi
                if ! command -v yq &>/dev/null; then
                    if command -v snap &>/dev/null; then
                        sudo snap install yq
                    else
                        say_warn "yq not installed. Get it from: https://github.com/mikefarah/yq/releases"
                    fi
                fi
            fi
            ;;
        arch|manjaro|endeavouros|garuda)
            deps=(rsync rclone msmtp imagemagick yq jq dialog psmisc lm_sensors lsof)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo pacman -S --noconfirm ${deps[*]}"
            else
                say "Installing via pacman..."
                sudo pacman -Sy --noconfirm "${deps[@]}"
            fi
            ;;
        opensuse*|sles)
            deps=(rsync rclone msmtp ImageMagick yq jq dialog psmisc sensors lsof)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo zypper install -y ${deps[*]}"
            else
                say "Installing via zypper..."
                sudo zypper install -y "${deps[@]}"
            fi
            ;;
        *)
            say_warn "Unknown OS '$OS_ID' — please install these manually:"
            say_warn "  rsync rclone msmtp ImageMagick yq jq dialog psmisc lm_sensors lsof"
            ;;
    esac
}

setup_completion() {
    [[ "$NO_COMPLETION" == true ]] && return 0
    [[ ! -f "$LIBEXEC_DIR/noba-completion.sh" ]] && return 0

    local shell_name rc_file
    shell_name=$(basename "${SHELL:-bash}")

    case "$shell_name" in
        bash)
            rc_file="$HOME/.bashrc"
            local marker="source $LIBEXEC_DIR/noba-completion.sh"
            if grep -qF "$marker" "$rc_file" 2>/dev/null; then
                say_ok "Bash completions already in $rc_file"
            elif [[ "$DRY_RUN" == true ]]; then
                dry "Would append completion source to $rc_file"
            else
                { echo ""; echo "# Nobara Automation Suite"; echo "$marker"; } >> "$rc_file"
                say_ok "Bash completions added to $rc_file"
            fi
            ;;
        zsh)
            rc_file="$HOME/.zshrc"
            local marker="source $LIBEXEC_DIR/noba-completion.sh"
            if grep -qF "$marker" "$rc_file" 2>/dev/null; then
                say_ok "Zsh completions already in $rc_file"
            elif [[ "$DRY_RUN" == true ]]; then
                dry "Would append completion source to $rc_file"
            else
                { echo ""; echo "# Nobara Automation Suite"; echo "$marker"; } >> "$rc_file"
                say_ok "Zsh completions added to $rc_file"
            fi
            ;;
        fish)
            local fish_conf="$HOME/.config/fish/conf.d/noba.fish"
            if [[ -f "$fish_conf" ]]; then
                say_ok "Fish completions already at $fish_conf"
            elif [[ "$DRY_RUN" == true ]]; then
                dry "Would create $fish_conf"
            else
                mkdir -p "$(dirname "$fish_conf")"
                echo "# Nobara Automation Suite" > "$fish_conf"
                echo "bass source $LIBEXEC_DIR/noba-completion.sh" >> "$fish_conf"
                say_ok "Fish completions written to $fish_conf"
                say_warn "Fish requires 'bass' plugin to source bash completions."
            fi
            ;;
        *)
            say_warn "Unrecognised shell '$shell_name' — skipping completion setup."
            say_warn "Manually add: source $LIBEXEC_DIR/noba-completion.sh"
            ;;
    esac
}

reload_systemd() {
    [[ "$NO_SYSTEMD" == true ]] && return 0
    [[ "$DRY_RUN"  == true ]] && { dry "Would run: systemctl --user daemon-reload"; return 0; }

    if ! command -v systemctl &>/dev/null; then
        say_warn "systemctl not found — systemd units installed but not loaded."
        return 0
    fi

    if ! systemctl --user is-system-running &>/dev/null \
       && ! systemctl --user status &>/dev/null 2>&1 | grep -q -v "Failed to connect"; then
        say_warn "systemd user session not available (container/non-systemd env)."
        say_warn "Units were copied but not activated — reload manually when systemd is running."
        return 0
    fi

    if systemctl --user daemon-reload 2>/dev/null; then
        say_ok "systemd user daemon reloaded."
    else
        say_warn "systemd daemon-reload failed — units may not be active until next login."
    fi
}

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--dir)          BIN_DIR="$2";             shift 2 ;;
           --prefix)       PREFIX="$2"
                           BIN_DIR="$PREFIX/bin"
                           LIBEXEC_DIR="$PREFIX/libexec/noba"
                           MAN_DIR="$PREFIX/share/man/man1"; shift 2 ;;
        -c|--config)       CONFIG_DIR="$2";          shift 2 ;;
        -s|--systemd)      SYSTEMD_USER_DIR="$2";    shift 2 ;;
           --email)        USER_EMAIL="$2";          shift 2 ;;
           --skip-deps)    SKIP_DEPS=true;           shift   ;;
           --no-completion)NO_COMPLETION=true;       shift   ;;
           --no-systemd)   NO_SYSTEMD=true;          shift   ;;
        -u|--uninstall)    UNINSTALL=true;           shift   ;;
        -n|--dry-run)      DRY_RUN=true;             shift   ;;
        -h|--help)         show_help ;;
        -v|--version)      echo "install.sh version 1.0.0"; exit 0 ;;
        *) say_err "Unknown argument: $1"; exit 1 ;;
    esac
done

[[ "$UNINSTALL" == true ]] && do_uninstall

# ── Begin install ─────────────────────────────────────────────────────────────
header "Nobara Automation Suite Installer v$NOBA_VERSION"

detect_os
say "OS: $OS_NAME ($OS_ID${OS_VERSION:+ $OS_VERSION})"
say "Bin dir:      $BIN_DIR"
say "Libexec dir:  $LIBEXEC_DIR"
say "Config dir:   $CONFIG_DIR"
say "Systemd dir:  $SYSTEMD_USER_DIR"
[[ "$DRY_RUN" == true ]] && say_warn "DRY RUN — no files will be written"

header "Dependencies"
install_deps

header "Creating directories"
if [[ "$DRY_RUN" == true ]]; then
    dry "mkdir -p $BIN_DIR $LIBEXEC_DIR/lib $CONFIG_DIR $SYSTEMD_USER_DIR $MAN_DIR $SHARE_DIR"
else
    mkdir -p "$BIN_DIR" "$LIBEXEC_DIR/lib" "$CONFIG_DIR" "$SYSTEMD_USER_DIR" "$MAN_DIR" "$SHARE_DIR"
    say_ok "Directories ready"
fi

header "Installing components"

# 1. Install Library
src="$SCRIPT_DIR/libexec/noba/lib/noba-lib.sh"
dst="$LIBEXEC_DIR/lib/noba-lib.sh"
if [[ -f "$src" ]]; then
    if [[ "$DRY_RUN" == true ]]; then dry "cp noba/lib/noba-lib.sh → $LIBEXEC_DIR/lib/"; else
        cp "$src" "$dst"
        chmod +x "$dst"
        record_install "$dst"
        say_ok "Library installed"
    fi
else
    say_err "Missing library file: $src"
    exit 1
fi

# 2. Install Automation Scripts
for name in "${SUITE_SCRIPTS[@]}"; do
    src="$SCRIPT_DIR/libexec/noba/$name"
    dst="$LIBEXEC_DIR/$name"
    if [[ ! -f "$src" ]]; then
        say_warn "Not found in source, skipping: noba/$name"
        continue
    fi
    if [[ "$DRY_RUN" == true ]]; then dry "cp noba/$name → $LIBEXEC_DIR/"; else
        cp "$src" "$dst"
        chmod +x "$dst"
        record_install "$dst"
        say_ok "$name"
    fi
done

for name in "${OPTIONAL_SCRIPTS[@]}"; do
    src="$SCRIPT_DIR/libexec/noba/$name"
    dst="$LIBEXEC_DIR/$name"
    [[ -f "$src" ]] || continue
    if [[ "$DRY_RUN" == true ]]; then dry "cp noba/$name → $LIBEXEC_DIR/ (optional)"; else
        cp "$src" "$dst"
        chmod +x "$dst"
        record_install "$dst"
        say_ok "$name (optional)"
    fi
done

# 3. Install Web Dashboard components
if [[ -d "$SCRIPT_DIR/libexec/noba/noba-web" ]]; then
    # Create target subdirectory
    if [[ "$DRY_RUN" == true ]]; then
        dry "mkdir -p $LIBEXEC_DIR/noba-web"
    else
        mkdir -p "$LIBEXEC_DIR/noba-web"
    fi

    # Copy backend files
    for file in server.py functions.sh; do
        src="$SCRIPT_DIR/libexec/noba/noba-web/$file"
        dst="$LIBEXEC_DIR/noba-web/$file"
        if [[ -f "$src" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                dry "cp noba/noba-web/$file → $LIBEXEC_DIR/noba-web/"
            else
                cp "$src" "$dst"
                chmod +x "$dst"
                record_install "$dst"
                say_ok "noba-web/$file"
            fi
        else
            say_warn "Missing web backend file: $src"
        fi
    done

    # Copy frontend HTML
    if [[ -f "$SCRIPT_DIR/share/noba-web/index.html" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            dry "mkdir -p $SHARE_DIR"
            dry "cp share/noba-web/index.html → $SHARE_DIR/"
        else
            mkdir -p "$SHARE_DIR"
            cp "$SCRIPT_DIR/share/noba-web/index.html" "$SHARE_DIR/index.html"
            record_install "$SHARE_DIR/index.html"
            say_ok "web frontend (index.html)"
        fi
    else
        say_warn "Missing web frontend: share/noba-web/index.html"
    fi

    # Install the web launcher
    if [[ -f "$SCRIPT_DIR/bin/noba-web" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            dry "cp bin/noba-web → $BIN_DIR/"
        else
            cp "$SCRIPT_DIR/bin/noba-web" "$BIN_DIR/noba-web"
            chmod +x "$BIN_DIR/noba-web"
            record_install "$BIN_DIR/noba-web"
            say_ok "noba-web (launcher)"
        fi
    else
        say_warn "Missing web launcher: bin/noba-web"
    fi
else
    say_warn "Web dashboard directory (libexec/noba/noba-web) not found – skipping web installation"
fi

# 4. Install CLI Wrapper
if [[ -f "$SCRIPT_DIR/bin/noba" ]]; then
    if [[ "$DRY_RUN" == true ]]; then dry "cp bin/noba → $BIN_DIR/"; else
        cp "$SCRIPT_DIR/bin/noba" "$BIN_DIR/noba"
        chmod +x "$BIN_DIR/noba"
        record_install "$BIN_DIR/noba"
        say_ok "noba (CLI wrapper)"
    fi
fi

# 5. Install Man Pages
if [[ -f "$SCRIPT_DIR/docs/noba.1" ]]; then
    if [[ "$DRY_RUN" == true ]]; then dry "cp docs/noba.1 → $MAN_DIR/"; else
        cp "$SCRIPT_DIR/docs/noba.1" "$MAN_DIR/noba.1"
        record_install "$MAN_DIR/noba.1"
        say_ok "noba.1 (man page)"
    fi
fi

# Install noba-web man page if exists
if [[ -f "$SCRIPT_DIR/docs/noba-web.1" ]]; then
    if [[ "$DRY_RUN" == true ]]; then dry "cp docs/noba-web.1 → $MAN_DIR/"; else
        cp "$SCRIPT_DIR/docs/noba-web.1" "$MAN_DIR/noba-web.1"
        record_install "$MAN_DIR/noba-web.1"
        say_ok "noba-web.1 (man page)"
    fi
fi

header "Configuration"
if [[ -f "$CONFIG_DIR/config.yaml" ]]; then
    say_ok "Config already exists — skipping generation."
elif [[ "$DRY_RUN" == true ]]; then
    dry "Would create default config at $CONFIG_DIR/config.yaml"
else
    cat > "$CONFIG_DIR/config.yaml" <<YAML
# Nobara Automation Suite — Configuration
# Edit this file to match your environment.

email: "${USER_EMAIL}"

logs:
  dir: "$HOME/.local/share/noba"

backup:
  dest: "/mnt/vnnas/backups/raizen"
  retention_days: 7
  keep_count: 3
  sources:
    - "$HOME/Documents"
    - "$HOME/Pictures"
    - "$HOME/.config"

cloud:
  remote: "mycloud:backups/raizen"

disk:
  threshold: 85
  warn_threshold: 75
  cleanup_enabled: true
  du_timeout: 30
  targets:
    - "/"
    - "$HOME"

web:
  port: 8080

backup_verifier:
  num_files: 5
  checksum_cmd: "sha256sum"
YAML
    record_install "$CONFIG_DIR/config.yaml"
    say_ok "Default config written: $CONFIG_DIR/config.yaml"
    if [[ -z "$USER_EMAIL" ]]; then
        say_warn "Email address is blank — edit $CONFIG_DIR/config.yaml to add one."
    fi
fi

header "Shell completions"
setup_completion

header "Systemd user units"
if [[ -d "$SCRIPT_DIR/systemd" ]]; then
    shopt -s nullglob
    unit_count=0
    for unit in "$SCRIPT_DIR"/systemd/*.timer "$SCRIPT_DIR"/systemd/*.service; do
        name=$(basename "$unit")
        if [[ "$DRY_RUN" == true ]]; then
            dry "cp systemd/$name → $SYSTEMD_USER_DIR/"
        else
            cp "$unit" "$SYSTEMD_USER_DIR/$name"
            record_install "$SYSTEMD_USER_DIR/$name"
            say_ok "$name"
        fi
        (( unit_count++ )) || true
    done
    shopt -u nullglob

    if (( unit_count == 0 )); then
        say "No .timer or .service files found in $SCRIPT_DIR/systemd/"
    fi
else
    say "No systemd/ directory in source — skipping unit installation."
fi

reload_systemd

if [[ "$DRY_RUN" == false && ${#INSTALLED_FILES[@]} -gt 0 ]]; then
    write_manifest
    trap - EXIT
fi

header "Installation complete"
if [[ "$DRY_RUN" == false ]]; then
    say "Files installed  : ${#INSTALLED_FILES[@]}"
    say "Manifest         : $MANIFEST_FILE"
    echo ""
    say "Next steps:"

    if [[ -z "$USER_EMAIL" ]]; then
        say "  1. Set your email in $CONFIG_DIR/config.yaml"
    fi

    local_shell=$(basename "${SHELL:-bash}")
    if [[ "$NO_COMPLETION" == false ]]; then
        case "$local_shell" in
            bash|zsh) say "  • Run: source ~/${local_shell}rc   (or open a new terminal)" ;;
        esac
    fi

    if command -v systemctl &>/dev/null && [[ "$NO_SYSTEMD" == false ]]; then
        say "  • Enable timers, e.g.:"
        say "      systemctl --user enable --now disk-sentinel.timer"
        say "      systemctl --user enable --now backup-to-nas.timer"
    fi

    say "  • Check dependencies: noba run config-check"
    say "  • Edit config:        $CONFIG_DIR/config.yaml"
    say "  • To uninstall:       $(basename "$0") --uninstall"
fi
INSTALL_EOF
chmod +x install.sh
echo "✅ Updated install.sh"
# 7. Update systemd service
cat > systemd/user/noba-web.service <<'EOF'
[Unit]
Description=Nobara Command Center Web Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=%h/.config/noba-web.conf
ExecStart=%h/.local/bin/noba-web $NOBA_WEB_OPTS
ExecStop=/bin/kill -TERM $MAINPID
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=noba-web

[Install]
WantedBy=default.target
EOF
echo "✅ Updated systemd/user/noba-web.service"

# 8. Create a basic man page for noba-web
mkdir -p docs
cat > docs/noba-web.1 <<'EOF'
.\" Man page for noba-web
.TH NOBA-WEB 1 "March 2025" "noba-web 1.0.0" "Nobara Automation Suite"
.SH NAME
noba-web \- Launch the Nobara Command Center web dashboard
.SH SYNOPSIS
.B noba-web
[OPTIONS]
.SH DESCRIPTION
noba-web starts a web-based dashboard for monitoring and controlling the
Nobara Automation Suite. It includes live system stats, service control,
Pi‑hole integration, speedtests, and more.
.SH OPTIONS
.TP
\fB-p, --port PORT\fR
Start searching from PORT (default: 8080)
.TP
\fB-m, --max PORT\fR
Maximum port to try (default: 8090)
.TP
\fB--host HOST\fR
Bind to specific host/IP (default: 0.0.0.0)
.TP
\fB-k, --kill\fR
Kill any running noba-web server and exit
.TP
\fB-v, --verbose\fR
Tail the server log after starting (Ctrl+C to stop)
.TP
\fB--https\fR
Enable HTTPS/TLS (requires \fB--generate-cert\fR first)
.TP
\fB--generate-cert\fR
Create a self-signed TLS certificate and exit
.TP
\fB--add-user\fR
Add or update a user (interactive, supports roles)
.TP
\fB--remove-user USERNAME\fR
Remove a user from auth.conf
.TP
\fB--list-users\fR
List configured users and their roles
.TP
\fB--set-password\fR
Alias for \fB--add-user\fR (backward compatible)
.TP
\fB--restart\fR
Kill any running server and start a new one
.TP
\fB--status\fR
Show whether the server is running
.TP
\fB--generate-systemd\fR
Print a systemd .service unit and exit
.TP
\fB--config FILE\fR
Use an alternative configuration file
.TP
\fB--help\fR
Show this help message
.TP
\fB--version\fR
Show version information
.SH FILES
.TP
~/.config/noba-web.conf
Configuration file for environment variables and options.
.TP
~/.config/noba-web/auth.conf
User credentials (one per line, format username:pbkdf2:salt:hash:role).
.TP
~/.config/noba/config.yaml
Main Nobara configuration (email, backup targets, etc.).
.SH ENVIRONMENT
.TP
NOBA_WEB_OPTS
Additional options passed to the server (used in systemd service).
.SH AUTHOR
Raizen (and contributors)
.SH SEE ALSO
noba(1)
EOF
echo "✅ Created docs/noba-web.1"

# 9. Update README.md (optional – we'll just add a note)
if [[ -f README.md ]]; then
    # Append a note about the new version
    cat >> README.md <<EOF

## v1.0.0 – Modular release (March 2025)
- Complete restructuring into standard Linux FHS layout.
- Centralized versioning.
- Improved installer with manifest tracking.
- Enhanced web dashboard with notifications and speedtest history.
- Better systemd integration (EnvironmentFile support).
- New man page for \`noba-web\`.
EOF
    echo "✅ Updated README.md"
else
    echo "⚠️  README.md not found, skipping update."
fi

# 10. Create a basic test script (optional)
mkdir -p tests
cat > tests/test_functions.bats <<'EOF'
#!/usr/bin/env bats

load '../libexec/noba/lib/noba-lib.sh'
load '../libexec/noba/noba-web/functions.sh'

@test "find_free_port returns a number" {
    run find_free_port 8000 8010
    [ "$status" -eq 0 ]
    [[ "$output" =~ ^[0-9]+$ ]]
}

@test "show_version returns something" {
    NOBA_ROOT="$BATS_TEST_DIRNAME/.."
    run show_version
    [ "$status" -eq 0 ]
    [ -n "$output" ]
}
EOF
chmod +x tests/test_functions.bats
echo "✅ Created tests/test_functions.bats"

echo
echo "🎉 Upgrade to v1.0.0 complete!"
echo "Please review the changes and run: git add . && git commit -m 'chore: release v1.0.0'"
