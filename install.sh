#!/bin/bash
# install.sh – Smart installer for Nobara Automation Suite

set -euo pipefail

# -------------------------------------------------------------------
# Default paths (can be overridden by environment)
# -------------------------------------------------------------------
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/noba}"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
SKIP_DEPS=false

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Install Nobara Automation Suite.

Options:
  -d, --dir DIR       Installation directory (default: $INSTALL_DIR)
  -c, --config DIR    Configuration directory (default: $CONFIG_DIR)
  -s, --systemd DIR   Systemd user unit directory (default: $SYSTEMD_USER_DIR)
  --skip-deps         Skip dependency installation (useful for testing)
  -n, --dry-run       Show what would be done without copying
  --help              Show this help
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dir)       INSTALL_DIR="$2"; shift 2 ;;
        -c|--config)    CONFIG_DIR="$2"; shift 2 ;;
        -s|--systemd)   SYSTEMD_USER_DIR="$2"; shift 2 ;;
        --skip-deps)    SKIP_DEPS=true; shift ;;
        -n|--dry-run)   DRY_RUN=true; shift ;;
        --help)         show_help ;;
        *)              echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# OS detection
# -------------------------------------------------------------------
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID="$ID"
        OS_VERSION_ID="${VERSION_ID%%.*}"  # major version only
        OS_NAME="$NAME"
    else
        OS_ID="unknown"
        OS_NAME="unknown"
    fi
    echo "Detected OS: $OS_NAME ($OS_ID)"
}

detect_os

# -------------------------------------------------------------------
# Dependency installation
# -------------------------------------------------------------------
install_deps() {
    if [ "$SKIP_DEPS" = true ]; then
        echo "Skipping dependency installation."
        return
    fi

    local deps=()
    case "$OS_ID" in
        fedora|nobara|rhel|centos)
            deps=(rsync msmtp ImageMagick yq jq dialog kdialog lm_sensors lsof speedtest-cli)
            if [ "$DRY_RUN" = true ]; then
                echo "DRY RUN: Would install: sudo dnf install ${deps[*]}"
            else
                echo "Installing dependencies via dnf..."
                sudo dnf install -y "${deps[@]}"
            fi
            ;;
        debian|ubuntu|linuxmint|pop)
            deps=(rsync msmtp imagemagick jq dialog kdialog lm-sensors lsof speedtest-cli)
            # yq may need manual install
            if [ "$DRY_RUN" = true ]; then
                echo "DRY RUN: Would install: sudo apt install -y ${deps[*]}"
                echo "DRY RUN: yq may need manual install (see https://github.com/mikefarah/yq)"
            else
                echo "Installing dependencies via apt..."
                sudo apt update
                sudo apt install -y "${deps[@]}"
                if ! command -v yq &>/dev/null; then
                    echo "yq not found. Installing via snap if available..."
                    if command -v snap &>/dev/null; then
                        sudo snap install yq
                    else
                        echo "WARNING: yq not installed. Please install manually from https://github.com/mikefarah/yq"
                    fi
                fi
            fi
            ;;
        arch|manjaro|endeavouros)
            deps=(rsync msmtp imagemagick yq jq dialog kdialog lm_sensors lsof speedtest-cli)
            if [ "$DRY_RUN" = true ]; then
                echo "DRY RUN: Would install: sudo pacman -S ${deps[*]}"
            else
                echo "Installing dependencies via pacman..."
                sudo pacman -Sy --noconfirm "${deps[@]}"
            fi
            ;;
        *)
            echo "WARNING: Unknown OS '$OS_ID'. Please install dependencies manually: rsync, msmtp, ImageMagick, yq, jq, dialog, kdialog, lm_sensors, lsof, speedtest-cli"
            ;;
    esac
}

install_deps

# -------------------------------------------------------------------
# Installation steps (same as before)
# -------------------------------------------------------------------
echo "Installing Nobara Automation Suite to $INSTALL_DIR"
echo "Configuration directory: $CONFIG_DIR"
echo "Systemd user units: $SYSTEMD_USER_DIR"

if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN – no files will be copied."
fi

# Create directories
if [ "$DRY_RUN" = false ]; then
    mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$SYSTEMD_USER_DIR"
fi

# Copy scripts
echo "Copying scripts..."
for script in "$SCRIPT_DIR"/*.sh; do
    name=$(basename "$script")
    if [ "$DRY_RUN" = true ]; then
        echo "  Would copy $name to $INSTALL_DIR/"
    else
        cp "$script" "$INSTALL_DIR/"
        chmod +x "$INSTALL_DIR/$name"
        echo "  Copied $name"
    fi
done

# Copy noba CLI (no extension)
if [ -f "$SCRIPT_DIR/noba" ]; then
    if [ "$DRY_RUN" = true ]; then
        echo "  Would copy noba to $INSTALL_DIR/"
    else
        cp "$SCRIPT_DIR/noba" "$INSTALL_DIR/"
        chmod +x "$INSTALL_DIR/noba"
        echo "  Copied noba"
    fi
fi

# Create default config if missing
if [ ! -f "$CONFIG_DIR/config.yaml" ] && [ "$DRY_RUN" = false ]; then
    cat > "$CONFIG_DIR/config.yaml" <<CONFIG
# Nobara unified configuration
email: "your@email.com"

backup:
  dest: "/mnt/vnnas/backups/raizen"
  sources:
    - "/home/raizen/Documents"
    - "/home/raizen/Pictures"

disk:
  threshold: 85
  targets:
    - "/"
    - "/home"
  cleanup_enabled: true

logs:
  dir: "$HOME/.local/share/noba"
CONFIG
    echo "Created default config at $CONFIG_DIR/config.yaml"
elif [ "$DRY_RUN" = false ]; then
    echo "Config file already exists, skipping."
fi

# Copy systemd user units if they exist
if [ -d "$SCRIPT_DIR/systemd" ]; then
    echo "Copying systemd user units..."
    for unit in "$SCRIPT_DIR"/systemd/*.{timer,service}; do
        if [ -f "$unit" ]; then
            name=$(basename "$unit")
            if [ "$DRY_RUN" = true ]; then
                echo "  Would copy $name to $SYSTEMD_USER_DIR/"
            else
                cp "$unit" "$SYSTEMD_USER_DIR/"
                echo "  Copied $name"
            fi
        fi
    done
else
    echo "No systemd units directory found; skipping."
fi

if [ "$DRY_RUN" = false ]; then
    echo "Reloading systemd user daemon..."
    systemctl --user daemon-reload
fi

echo
echo "Installation complete."
if [ "$DRY_RUN" = false ]; then
    echo "You can now enable timers, e.g.:"
    echo "  systemctl --user enable --now disk-sentinel.timer"
    echo "Edit configuration: $CONFIG_DIR/config.yaml"
fi
