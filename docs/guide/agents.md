# Remote Agents

NOBA agents are lightweight Python daemons that run on remote Linux or Windows hosts. They report system metrics to the NOBA server over HTTPS and accept commands via WebSocket.

## Deploy an Agent

### Method 1 — SSH Deploy (from the UI)

1. Open **Agents** in the sidebar.
2. Click **Deploy Agent**.
3. Enter the target host, SSH user, and port.
4. NOBA connects via SSH, installs the agent, and registers it automatically.

Requirements: the NOBA server must be able to reach the target over SSH; `python3` must be installed on the target.

### Method 2 — Install Script (manual)

Run on the target host:

```bash
curl -sf http://<noba-server>:8080/api/agents/install-script?key=<agent-key> | bash
```

The script:
- Downloads `noba-agent.pyz` from the NOBA server.
- Installs it to `/opt/noba-agent/`.
- Creates a systemd unit `noba-agent.service` and enables it.
- Writes the server URL and key to `/etc/noba-agent/agent.conf`.

### Method 3 — Windows Agent

Download the Windows agent from **Agents → Deploy → Windows** and run the installer. It installs as a Windows Service.

## Agent Keys

Each agent authenticates with a unique API key. Keys are generated in **Settings → Agent Keys** (see [Agent Keys](/config/agent-keys)).

## Command Palette

Click any online agent to open its detail panel, then use the **Command** field or the Command Palette button to send a command.

Supported command types (42 total, risk-tiered):

| Risk | Category | Commands |
|------|----------|----------|
| Low | System info | `ping`, `system_info`, `disk_usage`, `package_updates` |
| Low | Services | `check_service`, `list_services` |
| Low | Files | `file_read`, `file_list`, `file_checksum`, `file_stat` |
| Low | Containers | `container_list`, `container_logs` |
| Low | Network | `dns_lookup`, `network_config`, `network_stats`, `endpoint_check`, `network_discover` |
| Low | Logs | `get_logs`, `follow_logs`, `stop_stream`, `get_stream` |
| Low | Discovery | `discover_services`, `security_scan` |
| Low | Users | `list_users` |
| Medium | Services | `restart_service`, `service_control`, `set_interval` |
| Medium | Files | `file_transfer`, `file_push` |
| Medium | Containers | `container_control` |
| Medium | Maintenance | `verify_backup` |
| High | Execution | `exec` |
| High | Files | `file_write`, `file_delete` |
| High | System | `reboot`, `update_agent`, `uninstall_agent` |
| High | Packages | `package_install`, `package_remove` |
| High | Users | `user_manage` |
| High | Processes | `process_kill` |

Commands are delivered via WebSocket for near-instant execution. Results are returned and displayed in the command history panel.

## Log Streaming

Click **Stream Logs** in an agent's detail panel to open a live log viewer. Supported log sources:

- `journald` — filtered by unit name
- Arbitrary file paths (e.g. `/var/log/nginx/access.log`)

The stream uses SSE from the agent's `/stream` endpoint, proxied through the NOBA server.

## File Transfer

Use **File Transfer** in the agent panel to upload or download files:

- **Upload** — select a local file; it is sent to the agent's target path.
- **Download** — enter a remote path; the file is fetched and downloaded to your browser.

## Remote Desktop

Click **Remote Desktop** in an agent's detail panel to open a live screen view of the remote host.

- **Supported platforms**: Wayland (Mutter D-Bus), X11, Windows (GDI), macOS (Quartz)
- **Viewer-only** for `viewer` role — `operator` and `admin` can send mouse, keyboard, and clipboard events
- **Clipboard bridge**: paste your local clipboard into the remote session (Ctrl+V), or copy the remote clipboard to your local browser
- **Quality controls**: adjust JPEG quality and frame rate mid-session from the toolbar
- Multiple viewers can connect simultaneously; the agent captures once and the server fans frames out to all subscribers

The remote desktop session is served over a dedicated WebSocket (`/api/agents/{hostname}/rdp`). Auth uses the same short-lived WS token as the terminal.

## Embedded Terminal

Click **Terminal** in an agent's detail panel to open a full PTY session directly in the browser.

- Full xterm.js terminal with color support
- Session is managed by a WebSocket PTY (`/api/agents/{hostname}/terminal`)
- Terminal access is restricted to `admin` role
- Session timeout is configurable via `NOBA_TERMINAL_TIMEOUT` (default: 30 minutes)

## Agent Delete

To remove an agent:

1. Open the agent's detail panel.
2. Click **Delete Agent**.
3. Confirm. The agent record and all associated history are removed from the database.

The agent service on the remote host is not automatically stopped — run `systemctl disable --now noba-agent` on the remote host after deletion.

## Agent Status

| Status | Meaning |
|--------|---------|
| Online | Last heartbeat within 30 seconds |
| Offline | No heartbeat for 30–300 seconds |
| Dead | No heartbeat for more than 5 minutes |

Agents send a heartbeat every 15 seconds by default.
