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
