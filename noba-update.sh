#!/bin/bash
# noba-update.sh – Pull latest scripts from git repository, optionally update system packages

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
REPO_DIR="${REPO_DIR:-$HOME/.local/bin}"
REMOTE="origin"
BRANCH="main"
UPDATE_SYSTEM=false
AUTO_YES=false

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config || true
if [ "$CONFIG_LOADED" = true ]; then
    REPO_DIR="$(get_config ".update.repo_dir" "$REPO_DIR")"
    REMOTE="$(get_config ".update.remote" "$REMOTE")"
    BRANCH="$(get_config ".update.branch" "$BRANCH")"
    UPDATE_SYSTEM="$(get_config ".update.system.enabled" "$UPDATE_SYSTEM")"
    AUTO_YES="$(get_config ".update.system.auto_confirm" "$AUTO_YES")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-update.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Pull the latest version of all noba scripts from the git repository.
Optionally also run system package updates (dnf, flatpak).

Options:
  --repo DIR        Repository directory (default: $REPO_DIR)
  --remote NAME     Git remote name (default: $REMOTE)
  --branch NAME     Git branch name (default: $BRANCH)
  --system          Also run system updates (dnf and flatpak)
  --auto-yes        Auto‑confirm package updates (for non‑interactive use)
  --help            Show this help message
  --version         Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o '' -l repo:,remote:,branch:,system,auto-yes,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --repo)      REPO_DIR="$2"; shift 2 ;;
        --remote)    REMOTE="$2"; shift 2 ;;
        --branch)    BRANCH="$2"; shift 2 ;;
        --system)    UPDATE_SYSTEM=true; shift ;;
        --auto-yes)  AUTO_YES=true; shift ;;
        --help)      show_help ;;
        --version)   show_version ;;
        --)          shift; break ;;
        *)           break ;;
    esac
done

# -------------------------------------------------------------------
# Main update logic
# -------------------------------------------------------------------
log_info "Updating noba scripts from git..."
log_debug "Repository: $REPO_DIR, remote: $REMOTE, branch: $BRANCH"

if [ ! -d "$REPO_DIR" ]; then
    log_error "Repository directory $REPO_DIR does not exist."
    exit 1
fi

cd "$REPO_DIR" || { log_error "Cannot cd to $REPO_DIR"; exit 1; }

# Check if it's a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    log_error "$REPO_DIR is not a git repository."
    exit 1
fi

# Fetch and pull
log_info "Fetching from $REMOTE/$BRANCH..."
if ! git fetch "$REMOTE" "$BRANCH"; then
    log_error "Git fetch failed."
    exit 1
fi

log_info "Pulling changes..."
if ! git pull "$REMOTE" "$BRANCH"; then
    log_error "Git pull failed."
    exit 1
fi

# -------------------------------------------------------------------
# System updates (if requested)
# -------------------------------------------------------------------
if [ "$UPDATE_SYSTEM" = true ]; then
    log_info "Checking for system updates..."

    # DNF updates
    if command -v dnf &>/dev/null; then
        log_info "Running dnf update..."
        if [ "$AUTO_YES" = true ]; then
            sudo dnf update -y
        else
            sudo dnf update
        fi
    fi

    # Flatpak updates
    if command -v flatpak &>/dev/null; then
        log_info "Running flatpak update..."
        if [ "$AUTO_YES" = true ]; then
            flatpak update -y
        else
            flatpak update
        fi
    fi
fi

# -------------------------------------------------------------------
# Make all scripts executable
# -------------------------------------------------------------------
log_info "Making scripts executable..."
find "$REPO_DIR" -maxdepth 1 -name "*.sh" -exec chmod +x {} \;

log_info "Update completed successfully."

# Optional: run config-check to verify dependencies
if [ -x "$REPO_DIR/config-check.sh" ]; then
    log_info "Running config-check.sh to verify dependencies..."
    "$REPO_DIR/config-check.sh"
else
    log_warn "config-check.sh not found – skipping dependency check."
fi
