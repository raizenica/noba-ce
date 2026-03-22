# Remote Terminal

NOBA provides a full interactive terminal for remote agents directly in the web dashboard. Connect to any online agent and run commands as if you were SSH'd in.

## Accessing the Terminal

1. Navigate to **Agents** in the sidebar
2. Click on any online agent to open the detail modal
3. Select the **Terminal** tab

The terminal connects via WebSocket for real-time interaction. You'll see a green **connected** badge when the session is active.

## How It Works

The terminal uses a real PTY (pseudo-terminal) on the remote agent:

- **Browser** connects to the NOBA server via WebSocket
- **Server** bridges the connection to the agent's WebSocket
- **Agent** spawns a shell process via `pty.openpty()` (Linux) or `subprocess.Popen` (Windows)
- Keystrokes and output stream in real-time through the WebSocket chain

This means full interactive support — `vim`, `htop`, `top`, `ssh`, `sudo`, tab completion, command history, and ANSI colors all work.

## Role-Based Access

Terminal access enforces least privilege based on your NOBA role:

### Admin
Full shell access as the agent's service user. Unrestricted.

### Operator
Restricted shell for diagnostics only:

- **Linux**: Opens a session as the `noba-agent` user (or `nobody` if unavailable). Falls back to `bash --restricted` if no unprivileged user exists.
- **Windows**: PowerShell in **Constrained Language Mode** — blocks .NET object creation, COM access, `Add-Type`, and other potentially dangerous operations while keeping standard commands available.

### Viewer
No terminal access.

## Platform Support

### Linux / macOS
Full PTY with xterm-256color support. Terminal resize events are forwarded to the remote shell via `SIGWINCH`.

### Windows
PowerShell session via stdin/stdout pipes. Interactive commands work, though some TUI applications may have limited rendering compared to a native Windows Terminal.

## Agent Requirements

The remote terminal requires agent version **2.2.0** or later. Agents auto-update when the server has a newer version — the update is triggered automatically on the next heartbeat cycle (within 30 seconds).

To check agent versions, look at the agent detail modal's **Overview** tab.

## Troubleshooting

### Terminal shows "disconnected"
- Verify the agent is online (green badge in the agents list)
- Check that the agent is connected via WebSocket (commands delivered via WS are instant; queued commands wait for the next heartbeat)
- Try refreshing the page to re-establish the WebSocket connection

### No output after connecting
- The agent may be running an older version without PTY support. Check the agent version in the Overview tab — it needs to be 2.2.0+
- Use the Command Palette to send an "Update Agent" command, or wait for auto-update

### Session hangs
- If a command hangs, close the terminal tab and reopen it to start a fresh session
- The PTY session is automatically cleaned up when you close the modal or navigate away
