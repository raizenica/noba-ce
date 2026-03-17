#!/bin/bash
# Shared functions for Noba Web
# Sourced by bin/noba-web — do NOT execute directly.

# ── Logging ───────────────────────────────────────────────────────────────────
# Emit coloured output only when stdout/stderr is an interactive terminal.
# Piping to a log file or systemd journal produces clean plain text.

_has_color() { [[ -t 1 ]]; }
_has_color_err() { [[ -t 2 ]]; }

log_info() {
    if _has_color; then
        echo -e "\033[1;34m[INFO]\033[0m $*"
    else
        echo "[INFO] $*"
    fi
}

log_success() {
    if _has_color; then
        echo -e "\033[1;32m[OK]\033[0m $*"
    else
        echo "[OK] $*"
    fi
}

log_warn() {
    if _has_color_err; then
        echo -e "\033[1;33m[WARN]\033[0m $*" >&2
    else
        echo "[WARN] $*" >&2
    fi
}

log_error() {
    if _has_color_err; then
        echo -e "\033[1;31m[ERROR]\033[0m $*" >&2
    else
        echo "[ERROR] $*" >&2
    fi
}

# ── Dependency check ──────────────────────────────────────────────────────────
# Usage: check_deps python3 yq ip
check_deps() {
    local missing=()
    for dep in "$@"; do
        command -v "$dep" &>/dev/null || missing+=("$dep")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing[*]}"
        exit 1
    fi
}

# ── Network helpers ───────────────────────────────────────────────────────────
# Print the primary outbound IPv4 address, falling back to 127.0.0.1.
local_ip() {
    ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[\d.]+' || echo "127.0.0.1"
}

# ── Process helpers ───────────────────────────────────────────────────────────
# Returns 0 if PID is alive, 1 otherwise.
_is_running() {
    local pid="$1"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

# Read PID from file; echo it on success, return 1 if file is missing or empty.
_read_pid() {
    local pid_file="$1"
    local pid
    pid=$(cat "$pid_file" 2>/dev/null || true)
    [[ -n "$pid" ]] && echo "$pid" && return 0
    return 1
}

# ── Kill server ───────────────────────────────────────────────────────────────
# Usage: kill_server <pid_file> <url_file> <html_dir>
#
# html_dir is removed only after a strict safety check — it must be a
# non-empty path that strictly resides in /tmp/ or /var/tmp/.
kill_server() {
    local pid_file="$1" url_file="$2" html_dir="$3"

    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(_read_pid "$pid_file") || true

        if _is_running "$pid"; then
            log_info "Stopping server (PID $pid)…"
            kill -TERM "$pid" 2>/dev/null || true

            # Wait up to 5 s for graceful exit before escalating to SIGKILL.
            local i
            for i in 1 2 3 4 5; do
                _is_running "$pid" || break
                sleep 1
            done

            if _is_running "$pid"; then
                log_warn "Server did not stop gracefully — sending SIGKILL."
                kill -KILL "$pid" 2>/dev/null || true
            fi
        fi

        rm -f "$pid_file" "$url_file"
    fi

    # Guard: only remove html_dir if it strictly looks like a safe temp path.
    if [[ -n "$html_dir" && "$html_dir" != "/" ]] && \
       [[ "$html_dir" =~ ^(/tmp/|/var/tmp/) ]]; then
        log_info "Cleaning up ephemeral sandbox: $html_dir"
        rm -rf "$html_dir"
    elif [[ -n "$html_dir" && -d "$html_dir" ]]; then
        log_warn "html_dir '$html_dir' is outside expected ephemeral locations — skipping removal."
    fi
}

# ── Show status ───────────────────────────────────────────────────────────────
# Usage: show_status <pid_file> <url_file> <log_file>
show_status() {
    local pid_file="$1" url_file="$2" log_file="$3"

    if [[ ! -f "$pid_file" ]]; then
        log_info "Server is not running."
        return 0
    fi

    local pid url
    pid=$(_read_pid "$pid_file") || { log_warn "PID file is empty."; return 1; }
    url=$(cat "$url_file" 2>/dev/null || echo "unknown URL")

    if _is_running "$pid"; then
        local uptime_str=""
        # Read process start time from /proc for a human-readable uptime.
        if [[ -r "/proc/$pid/stat" ]]; then
            local start_ticks hz elapsed
            start_ticks=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || echo "")
            hz=$(getconf CLK_TCK 2>/dev/null || echo "100")
            if [[ -n "$start_ticks" ]]; then
                local uptime_s
                uptime_s=$(awk '{print int($1)}' /proc/uptime)
                elapsed=$(( uptime_s - start_ticks / hz ))
                local d h m
                d=$(( elapsed / 86400 )); h=$(( (elapsed % 86400) / 3600 )); m=$(( (elapsed % 3600) / 60 ))
                uptime_str="  uptime=${d}d${h}h${m}m"
            fi
        fi
        log_success "Server running  PID=$pid  URL=$url${uptime_str}"
        echo "  Log: $log_file"
    else
        log_warn "PID file present but server is not running (stale). Cleaning up."
        rm -f "$pid_file" "$url_file"
        return 1
    fi
}

# ── Systemd unit generator ────────────────────────────────────────────────────
# Usage: generate_systemd <launcher_path> <host>
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

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.local %h/.config
RestrictSUIDSGID=true

[Install]
WantedBy=default.target
EOF
}

# ── Password setup ────────────────────────────────────────────────────────────
# Usage: set_password <yaml_file>
set_password() {
    local yaml_file="$1"
    echo "Setting up login credentials for Nobara Web Dashboard"

    # Validate username
    local username
    while true; do
        read -rp "Username: " username
        if [[ -z "$username" ]]; then
            echo "Username cannot be empty."
        elif [[ ! "$username" =~ ^[a-zA-Z0-9_-]{1,32}$ ]]; then
            echo "Username must be 1–32 characters: letters, digits, _ or - only."
        else
            break
        fi
    done

    local password password2
    while true; do
        read -rs -p "Password: " password; echo
        if [[ ${#password} -lt 12 ]]; then
            echo "Password must be at least 12 characters."
            continue
        fi
        read -rs -p "Confirm password: " password2; echo
        if [[ "$password" != "$password2" ]]; then
            echo "Passwords do not match. Try again."
            continue
        fi
        break
    done

    local auth_dir="$HOME/.config/noba-web"
    mkdir -p "$auth_dir"

    # Hash the password with PBKDF2-SHA256 (200k rounds) via Python.
    # Arguments are passed as positional params — never interpolated into code.
    local tmp_auth="$auth_dir/auth.conf.tmp"
    (umask 077; python3 - "$tmp_auth" "$username" "$password" <<'PYEOF'
import hashlib, secrets, sys
auth_file = sys.argv[1]
username  = sys.argv[2]
password  = sys.argv[3]
salt      = secrets.token_hex(16)
dk        = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000)
hstr      = f'pbkdf2:{salt}:{dk.hex()}'
with open(auth_file, 'w') as f:
    f.write(f'{username}:{hstr}:admin\n')
PYEOF
    )
    mv "$tmp_auth" "$auth_dir/auth.conf"

    log_success "Credentials saved to $auth_dir/auth.conf  (PBKDF2-SHA256, 200k rounds)"
    create_default_yaml "$yaml_file"
}

# ── Default YAML config ───────────────────────────────────────────────────────
# Usage: create_default_yaml <yaml_file>
create_default_yaml() {
    local yaml_file="$1"
    [[ -f "$yaml_file" ]] && return 0

    log_info "Creating default config at $yaml_file"
    mkdir -p "$(dirname "$yaml_file")"

    cat > "$yaml_file" <<EOF
# Nobara Automation Suite — configuration
# Edit this file to match your environment.
email: "you@example.com"

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
  # Comma-separated list of systemd services to monitor.
  monitoredServices: "sshd, docker, NetworkManager"
  # Comma-separated IPs to ping in the radar panel.
  radarIps: "192.168.1.1, 1.1.1.1, 8.8.8.8"
  # Pi-hole base URL (leave blank to disable).
  piholeUrl: ""
  piholeToken: ""
  # Bookmarks format: "Label|URL|fa-icon-name" separated by commas.
  bookmarksStr: ""
EOF

    log_success "Default config created. Edit before first use: $yaml_file"
}

# ── User database management ──────────────────────────────────────────────────
NOBA_USER_DB="${NOBA_USER_DB:-$HOME/.config/noba-web/users.conf}"

init_user_db() {
    if [[ ! -f "$NOBA_USER_DB" ]]; then
        mkdir -p "$(dirname "$NOBA_USER_DB")"
        touch "$NOBA_USER_DB"
        chmod 600 "$NOBA_USER_DB"
    fi
}

add_user() {
    local username="$1"
    local password="$2"
    local role="${3:-admin}"
    init_user_db
    if grep -q "^$username:" "$NOBA_USER_DB" 2>/dev/null; then
        log_error "User '$username' already exists."
        return 1
    fi
    local hash
    hash=$(python3 -c "
import hashlib, secrets, sys
salt = secrets.token_hex(16)
dk = hashlib.pbkdf2_hmac('sha256', sys.argv[1].encode(), salt.encode(), 200000)
print('pbkdf2:' + salt + ':' + dk.hex())
" "$password")

    # Atomic save
    touch "$NOBA_USER_DB.tmp"
    chmod 600 "$NOBA_USER_DB.tmp"
    cp "$NOBA_USER_DB" "$NOBA_USER_DB.tmp"
    echo "$username:$hash:$role" >> "$NOBA_USER_DB.tmp"
    mv "$NOBA_USER_DB.tmp" "$NOBA_USER_DB"
    log_success "User '$username' added with role '$role'."
}

list_users() {
    if [[ ! -f "$NOBA_USER_DB" ]]; then
        echo "No users found."
        return
    fi
    printf "%-20s %-10s\n" "USERNAME" "ROLE"
    printf "%-20s %-10s\n" "--------" "----"
    while IFS=: read -r user hash role; do
        printf "%-20s %-10s\n" "$user" "$role"
    done < "$NOBA_USER_DB"
}

remove_user() {
    local username="$1"
    if [[ ! -f "$NOBA_USER_DB" ]]; then
        log_error "No user database."
        return 1
    fi
    if ! grep -q "^$username:" "$NOBA_USER_DB"; then
        log_error "User '$username' not found."
        return 1
    fi

    # Atomic save
    touch "$NOBA_USER_DB.tmp"
    chmod 600 "$NOBA_USER_DB.tmp"
    grep -v "^$username:" "$NOBA_USER_DB" > "$NOBA_USER_DB.tmp"
    mv "$NOBA_USER_DB.tmp" "$NOBA_USER_DB"
    log_success "User '$username' removed."
}

change_password() {
    local username="$1"
    local password="$2"
    if [[ ! -f "$NOBA_USER_DB" ]]; then
        log_error "No user database."
        return 1
    fi
    if ! grep -q "^$username:" "$NOBA_USER_DB"; then
        log_error "User '$username' not found."
        return 1
    fi
    local hash role
    hash=$(python3 -c "
import hashlib, secrets, sys
salt = secrets.token_hex(16)
dk = hashlib.pbkdf2_hmac('sha256', sys.argv[1].encode(), salt.encode(), 200000)
print('pbkdf2:' + salt + ':' + dk.hex())
" "$password")
    role=$(grep "^$username:" "$NOBA_USER_DB" | cut -d: -f3)

    # Atomic save
    touch "$NOBA_USER_DB.tmp"
    chmod 600 "$NOBA_USER_DB.tmp"
    grep -v "^$username:" "$NOBA_USER_DB" > "$NOBA_USER_DB.tmp"
    echo "$username:$hash:$role" >> "$NOBA_USER_DB.tmp"
    mv "$NOBA_USER_DB.tmp" "$NOBA_USER_DB"
    log_success "Password changed for '$username'."
}

# ── Help ──────────────────────────────────────────────────────────────────────
show_help() {
    cat <<EOF
Usage: noba-web [OPTIONS]
Launch the Nobara Command Center web dashboard (default port: 8080).

Options:
  --host HOST            Bind to a specific host or IP  (default: 0.0.0.0)
  -k, --kill             Stop any running noba-web server and exit
  --restart              Stop any running server, then start a new one
  --status               Show running state (PID, URL, uptime)
  --set-password         Create or update single login credential (legacy)
  --add-user             Add a new user (interactive)
  --list-users           List all users
  --remove-user USER     Remove a user
  --change-password      Change a user's password (interactive)
  --generate-systemd     Print a systemd user-service unit and exit
  -v, --verbose          Tail the server log after starting  (Ctrl-C to stop)
  --version              Print version information and exit
  --help                 Show this help message and exit

Configuration:
  Runtime config  ~/.config/noba-web.conf   (HOST, LOG_FILE, PID_FILE, …)
  App config      ~/.config/noba/config.yaml
  Credentials     ~/.config/noba-web/users.conf   (multi‑user)
EOF
}
