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
    cat <<EOF
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
