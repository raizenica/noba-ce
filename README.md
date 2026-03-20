# NOBA Command Center

A full-featured operations center for homelab and multi-site infrastructure management. Real-time monitoring, remote agent management, predictive intelligence, and 40+ service integrations — all from a single dashboard.

**Stack:** FastAPI · Alpine.js · Chart.js · SQLite WAL · No build step

## Features

### Core Monitoring
- **System Metrics** — CPU, memory, disk, network, temperatures, ZFS pools, containers (Docker/Podman)
- **Real-time SSE** — Server-Sent Events push live metrics to the browser every 5 seconds
- **Metrics History** — Time-series charts with zoom/pan, multi-metric correlation overlay
- **Sparkline Charts** — Inline SVG trend charts in dashboard cards
- **Health Bar** — Color-coded status pips for instant infrastructure overview
- **Anomaly Detection** — Automatic flagging of unusual resource patterns

### Remote Agents
- **Zero-dependency agent** — Standalone Python script, works on any Linux (reads /proc directly), optional psutil for cross-platform
- **Bidirectional commands** — 9 command types: exec, restart_service, get_logs, check_service, network_test, package_updates, update_agent, set_interval, ping
- **Agent metric persistence** — CPU/RAM/disk history stored in SQLite, queryable per-agent
- **One-click deployment** — Deploy from the dashboard via SSH, or copy-paste a one-liner (Linux/Windows)
- **Self-update** — Agents pull updates from the NOBA server and restart
- **Exponential backoff** — Graceful retry on connection failures

### Alerting & Incidents
- **Composite alert rules** — AND/OR conditions with escalation policies
- **Incident timeline** — Auto-generated from fired alerts, with resolve actions
- **Notification channels** — Pushover, Gotify, Slack, email, voice alerts
- **Maintenance windows** — Suppress alerts during planned downtime
- **SLA Dashboard** — Uptime percentages per agent/service (7d/30d/90d)

### 40+ Integrations

| Category | Services |
|----------|----------|
| **Media** | Plex, Jellyfin, Tautulli, Overseerr, Radarr, Sonarr, Lidarr, Readarr, Bazarr, Prowlarr, qBittorrent |
| **Infrastructure** | TrueNAS, Proxmox VE, Scrutiny (SMART), Frigate (NVR), InfluxDB, Uptime Kuma |
| **Network** | Pi-hole v5/v6, AdGuard Home, Traefik, Nginx Proxy Manager, Cloudflare, UniFi |
| **IoT & Home** | Home Assistant, Homebridge, Zigbee2MQTT, ESPHome, UniFi Protect, PiKVM |
| **DevOps** | Kubernetes, Gitea, GitLab, GitHub, Paperless-ngx, Vaultwarden |
| **Auth** | SSO/OIDC, LDAP/AD, TOTP 2FA, API keys, IP whitelisting |
| **Monitoring** | Tailscale mesh, certificate expiry, domain expiry, weather, energy (Shelly) |

### Operations Center
- **Multi-site awareness** — Site A/B toggle filters the entire dashboard
- **Tailscale network map** — Visual node grid with online/offline, direct/relay, subnet routes
- **Predictive disk intelligence** — SMART attribute trend analysis with failure prediction
- **Dependency map** — Service dependency graph with blast radius calculation
- **Recovery actions** — One-click Tailscale reconnect, DNS flush, service restart (admin-only, audit-logged)
- **Graylog integration** — Search centralized logs from the dashboard
- **InfluxDB query panel** — Flux query editor with Chart.js visualization
- **Config changelog** — Tracks every settings change with old→new diffs
- **Runbooks** — JSON-defined playbooks linked to alert triggers
- **Metrics correlation** — Overlay multiple metrics on a single timeline
- **Public status page** — No-auth HTML page at `/status` with auto-refresh

### Automation Engine
- **8 automation types** — Script, webhook, service, workflow, condition, delay, notify, HTTP
- **Workflow engine** — Sequential/parallel steps with retry and exponential backoff
- **Triggers** — Cron schedule, file system changes, RSS feeds, webhooks (HMAC validated), HA events
- **Approval gates** — Require manual approval before execution

### Security
- **Authentication** — PBKDF2 hashing, TOTP 2FA, OIDC, LDAP, API keys
- **Role-based access** — Admin, operator, viewer with fine-grained permissions
- **Input validation** — Regex + length limits on all user inputs, no command injection
- **Audit logging** — Every action tracked with username, IP, timestamp
- **Rate limiting** — Per-IP and per-user with lockout

### UI/UX
- **6 themes** — Nord, dark, light, and more
- **Glassmorphism modals** — Backdrop blur with accent glow
- **Quick glance mode** — Press `g` to collapse all cards to headers
- **Context menus** — Right-click cards for quick actions
- **Mobile responsive** — Bottom nav on mobile viewports
- **Keyboard shortcuts** — Customizable hotkeys
- **Notification center** — Bell icon with unread count
- **Embedded terminal** — WebSocket PTY via xterm.js (admin-only)

## Quick Start

### Prerequisites
- Python 3.10+
- Linux (Fedora, Ubuntu, Debian, Raspberry Pi OS, TrueNAS SCALE)

### Install

```bash
git clone https://github.com/raizenica/noba.git
cd noba
bash install.sh
```

The installer deploys scripts, the web dashboard, and a systemd user service on port **8080**.

### First Login

```bash
journalctl --user -u noba-web.service | grep password
```

### Deploy Agents

From the dashboard: **Agents card → Deploy Agent** (SSH or install script)

Or manually on any Linux node:
```bash
curl -sf "http://noba-server:8080/api/agent/install-script?key=YOUR_KEY" | sudo bash
```

Windows (PowerShell):
```powershell
.\install-agent.ps1 -Server "http://noba-server:8080" -Key "YOUR_KEY"
```

## Configuration

```
~/.config/noba/config.yaml
```

All settings are also configurable from the dashboard UI under **Settings → Integrations** (organized into 7 categories: Infrastructure, Media, Network, IoT & Home, DevOps, Notifications, Auth & Security).

## Project Layout

```
share/noba-web/server/   → Python backend (FastAPI, 160+ API routes)
share/noba-web/static/   → Frontend (Alpine.js, Chart.js, vanilla CSS)
share/noba-web/index.html → Dashboard UI
share/noba-web/status.html → Public status page
share/noba-agent/        → Remote agent + installers (Linux, Windows)
libexec/                 → Shell scripts (backup, disk check, cloud sync)
dev/                     → Developer toolkit (8 tools)
tests/                   → pytest test suite (344 tests)
```

## Developer Toolkit

```bash
dev/eye.py               # Playwright UI screenshot tool
dev/harness.sh           # Dev server lifecycle manager
dev/e2e.py               # 10 browser E2E tests
dev/smoke.py             # API smoke tester (160+ routes)
dev/crossref.py          # Multi-file cross-reference validator
dev/trace.py             # Request trace middleware + analyzer
dev/recon.py             # Tailscale infrastructure scanner
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | HTTP listen port |
| `SSL_CERT` | — | Path to TLS certificate |
| `SSL_KEY` | — | Path to TLS private key |
| `NOBA_REDIS_URL` | — | Optional Redis for caching |
| `NOBA_CELERY_BROKER` | — | Optional Celery for job queue |
| `NOBA_TERMINAL_ENABLED` | `true` | Enable/disable web terminal |

## License

MIT
