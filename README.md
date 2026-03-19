# NOBA Automation Suite

System monitoring, automation, and backup tooling for Linux workstations and servers, with a real-time web dashboard.

## Overview

NOBA is a collection of bash scripts for backups, disk monitoring, and cloud sync, paired with a web-based Command Center built on FastAPI and Alpine.js. It provides live system metrics, integration with popular self-hosted services, and configurable alerting -- all from a single dashboard.

## Features

- **System Monitoring** -- CPU, memory, disk, network, temperatures, ZFS pools, and container status (Docker and Podman).
- **SMART Disk Health** -- surface scan results and drive health indicators.
- **Real-time Updates** -- Server-Sent Events (SSE) push metrics to the browser as they change.
- **Metrics History** -- time-series charts rendered with Chart.js.
- **Anomaly Detection** -- flag unusual resource usage patterns automatically.
- **Audit Logging** -- track user actions and configuration changes.
- **Voice Alerts** -- optional browser-based spoken notifications for critical events.
- **Dark / Light Themes** -- switchable UI themes.
- **Authentication** -- PBKDF2 password hashing, per-request bearer tokens, and rate limiting.
- **Integrations** -- Pi-hole, Plex, Uptime Kuma, TrueNAS, Radarr, Sonarr, qBittorrent, and Proxmox VE.

## Quick Start

### Prerequisites

- Python 3.10 or later
- FastAPI, uvicorn, psutil, pyyaml, httpx (installed automatically)

### Install

```bash
bash install.sh
```

For unattended installs or environments where dependencies are already present:

```bash
bash install.sh -y --skip-deps
```

The installer deploys scripts, the web dashboard, and a systemd user service.

### Run

```bash
systemctl --user enable --now noba-web.service
```

The dashboard listens on port **8080** by default. Open `http://localhost:8080` in a browser.

## Configuration

All configuration lives in:

```
~/.config/noba/config.yaml
```

Edit this file to set integration URLs, API keys, alert thresholds, and other options. Changes take effect after restarting the service.

## First Run

On first launch, a random admin password is generated and printed to the service log. Retrieve it with:

```bash
journalctl --user -u noba-web.service | grep password
```

Change the password from the dashboard settings page after logging in.

## Integrations

Configure each integration in `config.yaml` by providing the service URL and, where required, an API key:

| Service       | Config key         |
|---------------|--------------------|
| Pi-hole       | `pihole`           |
| Plex          | `plex`             |
| Uptime Kuma   | `uptime_kuma`      |
| TrueNAS       | `truenas`          |
| Radarr        | `radarr`           |
| Sonarr        | `sonarr`           |
| qBittorrent   | `qbittorrent`      |
| Proxmox VE    | `proxmox`          |

## HTTPS

To enable TLS, set the certificate and key paths before starting the service:

```bash
export SSL_CERT=/path/to/fullchain.pem
export SSL_KEY=/path/to/privkey.pem
systemctl --user restart noba-web.service
```

You can persist these in a systemd override or in your shell profile.

## Environment Variables

| Variable   | Default | Description                        |
|------------|---------|------------------------------------|
| `PORT`     | `8080`  | HTTP listen port                   |
| `SSL_CERT` | --      | Path to TLS certificate            |
| `SSL_KEY`  | --      | Path to TLS private key            |

## Development

Install the project in editable mode with dev dependencies:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

The web dashboard source is located at `share/noba-web/`. The FastAPI backend entry point is `share/noba-web/server.py`.

## Uninstall

```bash
systemctl --user disable --now noba-web.service
bash uninstall.sh
```

## License

MIT
