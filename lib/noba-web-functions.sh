#!/bin/bash
# Shared functions for Noba Web

# Logging functions
log_info()    { echo -e "\033[1;34m[INFO]\033[0m $*"; }
log_success() { echo -e "\033[1;32m[OK]\033[0m $*"; }
log_warn()    { echo -e "\033[1;33m[WARN]\033[0m $*" >&2; }
log_error()   { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; }

# Check dependencies
check_deps() {
    local missing=()
    for dep in "$@"; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing dependencies: ${missing[*]}"
        exit 1
    fi
}

# Get local IP
local_ip() {
    ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[\d.]+' || echo "127.0.0.1"
}

# Create default YAML config if not exists
create_default_yaml() {
    local yaml_file="$1"
    if [[ -f "$yaml_file" ]]; then return; fi
    log_info "Creating default YAML config at $yaml_file"
    mkdir -p "$(dirname "$yaml_file")"
    cat > "$yaml_file" <<EOF
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

checksum:
  default_algo: "sha256"

images2pdf:
  default_paper_size: "A4"
  default_orientation: "portrait"
  default_quality: 92

logs:
  dir: "$HOME/.local/share/noba"
  log_rotation:
    days: 30

update:
  repo_dir: "$HOME/.local/bin"
  remote: "origin"
  branch: "main"

motd:
  quote_file: "$HOME/.config/quotes.txt"
  show_updates: true
  show_backup: true

services:
  monitor:
    - sshd
    - docker
    - NetworkManager
  notify: true

cron:
  scripts:
    - backup-to-nas.sh
    - disk-sentinel.sh
    - organize-downloads.sh

cloud:
  remote: "mycloud:backups/$USER"
  rclone_ops: "-v --checksum --progress"

web:
  service_list:
    - backup-to-nas.service
    - organize-downloads.service
    - noba-web.service
    - syncthing.service
  piholeUrl: "dnsa01.vannieuwenhove.org"
  piholeToken: ""
  monitoredServices: "backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service"
  radarIps: "192.168.100.1, 1.1.1.1, 8.8.8.8"
  bookmarksStr: "TrueNAS (vnnas)|http://vnnas.vannieuwenhove.org|fa-server, TrueNAS (vdhnas)|http://vdhnas.vannieuwenhove.org|fa-server, Pi-Hole|http://dnsa01.vannieuwenhove.org/admin|fa-shield-alt, Home Assistant|http://homeassistant.local:8123|fa-home, ROMM|http://romm.local|fa-gamepad, Prowlarr|http://localhost:9696|fa-search, ASUS Router|http://192.168.100.1|fa-network-wired"
EOF
    log_success "Default YAML created. Please edit: $yaml_file"
}

# Kill running server
kill_server() {
    local pid_file="$1" url_file="$2" html_dir="$3"
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || true)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping server (PID $pid)..."
            kill "$pid" 2>/dev/null && sleep 1
            kill -0 "$pid" 2>/dev/null && { kill -9 "$pid" 2>/dev/null || true; }
        fi
        rm -f "$pid_file" "$url_file"
        rm -rf "$html_dir"
    fi
}

# Show status
show_status() {
    local pid_file="$1" url_file="$2" log_file="$3"
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || true)
        local url
        url=$(cat "$url_file" 2>/dev/null || echo "unknown URL")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_success "Server running  PID=$pid  URL=$url"
            echo "  Log: $log_file"
        else
            log_warn "PID file present but server is not running (stale PID file)."
            rm -f "$pid_file" "$url_file"
        fi
    else
        log_info "Server is not running."
    fi
}

# Generate systemd unit
generate_systemd() {
    local self="$1" host="$2"
    cat <<EOF
# Save to: ~/.config/systemd/user/noba-web.service
# Enable:  systemctl --user enable --now noba-web.service

[Unit]
Description=Nobara Command Center Web Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${self} --host ${host}
ExecStop=/bin/kill -TERM \$MAINPID
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=noba-web

[Install]
WantedBy=default.target
EOF
}

# Set password (PBKDF2)
set_password() {
    local yaml_file="$1"
    echo "Setting up login credentials for Nobara Web Dashboard"
    read -rp "Username: " username
    read -rs -p "Password: " password; echo
    read -rs -p "Confirm password: " password2; echo
    if [[ "$password" != "$password2" ]]; then
        echo "Passwords do not match."; exit 1
    fi
    if [[ ${#password} -lt 8 ]]; then
        echo "Password must be at least 8 characters."; exit 1
    fi
    mkdir -p "$HOME/.config/noba-web"
    (umask 077; python3 - "$HOME/.config/noba-web/auth.conf" "$password" "$username" <<'PYEOF'
import hashlib, secrets, sys
salt  = secrets.token_hex(16)
dk    = hashlib.pbkdf2_hmac('sha256', sys.argv[2].encode(), salt.encode(), 200_000)
hstr  = 'pbkdf2:' + salt + ':' + dk.hex()
with open(sys.argv[1], 'w') as f:
    f.write(f'{sys.argv[3]}:{hstr}:admin\n')
PYEOF
    )
    echo "Credentials saved to ~/.config/noba-web/auth.conf  (PBKDF2-SHA256, 200k rounds)"
    create_default_yaml "$yaml_file"
}

# Help function (optional, but can be placed here)
show_help() {
    cat <<EOF
Usage: noba-web [OPTIONS]
Launch the Nobara Command Center web dashboard on port 8080.

Options:
  --host     HOST        Bind to specific host/IP (default: 0.0.0.0)
  -k, --kill             Kill any running noba-web server and exit
  -v, --verbose          After starting, tail the server log (Ctrl+C to stop)
  --set-password         Set or change the login credentials (PBKDF2-SHA256)
  --restart              Kill any running server and start a new one
  --status               Show whether the server is running (PID + URL)
  --generate-systemd     Print a systemd .service unit to stdout and exit
  --help                 Show this help message
  --version              Show version information

Configuration file: ~/.config/noba-web.conf (optional)
  Override HOST, HTML_DIR, LOG_FILE, SERVER_PID_FILE, etc.
EOF
}
