#!/usr/bin/env bash
# Install NOBA Agent on a remote node
set -euo pipefail

INSTALL_DIR="/opt/noba-agent"
CONFIG="/etc/noba-agent.yaml"
SERVICE="noba-agent"

echo "=== NOBA Agent Installer ==="

# Prompt for config if not provided
NOBA_SERVER="${1:-}"
NOBA_KEY="${2:-}"

if [[ -z "$NOBA_SERVER" ]]; then
    read -rp "NOBA Server URL: " NOBA_SERVER
fi
if [[ -z "$NOBA_KEY" ]]; then
    read -rp "Agent API Key: " NOBA_KEY
fi

# Install
sudo mkdir -p "$INSTALL_DIR"
sudo cp agent.py "$INSTALL_DIR/agent.py"
sudo chmod +x "$INSTALL_DIR/agent.py"

# Config
sudo tee "$CONFIG" > /dev/null <<EOF
server: $NOBA_SERVER
api_key: $NOBA_KEY
interval: 30
hostname: $(hostname)
tags: $(hostname | grep -q 'nas' && echo 'storage' || echo 'compute')
EOF

# Systemd
sudo cp noba-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE"

echo "=== NOBA Agent installed and running ==="
systemctl status "$SERVICE" --no-pager | head -5
