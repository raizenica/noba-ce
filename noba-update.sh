#!/bin/bash
# noba-update.sh – Pull latest scripts from git repository, optionally update system packages
# Improved version with safety checks and dry-run mode

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
DRY_RUN=false

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
    echo "noba-update.sh version 2.0 (enhanced)"
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
  --auto-yes        Auto‑confirm package updates and skip prompts (for non‑interactive use)
  --dry-run         Show what would be done without actually pulling or updating
  --help            Show this help message
  --version         Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o '' -l repo:,remote:,branch:,system,auto-yes,dry-run,help,version -- "$@"); then
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
        --dry-run)   DRY_RUN=true; shift ;;
        --help)      show_help ;;
        --version)   show_version ;;
        --)          shift; break ;;
        *)           break ;;
    esac
done

# -------------------------------------------------------------------
# Main update logic
# -------------------------------------------------------------------
check_deps git

log_info "Updating noba scripts from git..."
log_debug "Repository: $REPO_DIR, remote: $REMOTE, branch: $BRANCH"
if [ "$DRY_RUN" = true ]; then
    log_info "DRY RUN MODE – no changes will be applied"
fi

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

# Check for uncommitted changes
if ! git diff --quiet; then
    log_warn "You have uncommitted changes."
    if [ "$AUTO_YES" = false ] && [ "$DRY_RUN" = false ]; then
        read -rp "Pull anyway? (y/N) " answer
        if [[ ! "$answer" =~ ^[Yy]$ ]]; then
            log_info "Aborted by user."
            exit 0
        fi
    elif [ "$DRY_RUN" = true ]; then
        log_info "DRY RUN: would prompt about uncommitted changes."
    else
        log_info "Auto‑yes mode: proceeding with pull despite uncommitted changes."
    fi
fi

if [ "$DRY_RUN" = true ]; then
    log_info "DRY RUN: would fetch from $REMOTE/$BRANCH"
    log_info "DRY RUN: would pull with --ff-only"
else
    # Fetch and pull
    log_info "Fetching from $REMOTE/$BRANCH..."
    if ! git fetch "$REMOTE" "$BRANCH"; then
        log_error "Git fetch failed."
        exit 1
    fi

    log_info "Pulling changes (fast‑forward only)..."
    if ! git pull --ff-only "$REMOTE" "$BRANCH"; then
        log_error "Git pull failed (not fast‑forward). Manual merge may be needed."
        exit 1
    fi
fi

# -------------------------------------------------------------------
# System updates (if requested)
# -------------------------------------------------------------------
if [ "$UPDATE_SYSTEM" = true ]; then
    log_info "Checking for system updates..."

    # DNF updates
    if command -v dnf &>/dev/null; then
        log_info "Running dnf update..."
        if [ "$DRY_RUN" = true ]; then
            log_info "DRY RUN: would run 'sudo dnf update'"
        else
            if [ "$AUTO_YES" = true ]; then
                if sudo -n true 2>/dev/null; then
                    sudo dnf update -y
                else
                    log_warn "Passwordless sudo not available – you may be prompted."
                    sudo dnf update -y
                fi
            else
                sudo dnf update
            fi
        fi
    fi

    # Flatpak updates
    if command -v flatpak &>/dev/null; then
        log_info "Running flatpak update..."
        if [ "$DRY_RUN" = true ]; then
            log_info "DRY RUN: would run 'flatpak update'"
        else
            if [ "$AUTO_YES" = true ]; then
                flatpak update -y
            else
                flatpak update
            fi
        fi
    fi
fi

# -------------------------------------------------------------------
# Make all scripts executable (only if not dry-run)
# -------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    log_info "DRY RUN: would make all *.sh scripts executable."
else
    log_info "Making scripts executable..."
    find "$REPO_DIR" -maxdepth 1 -name "*.sh" -exec chmod +x {} \;
fi

log_info "Update completed successfully."

# Optional: run config-check to verify dependencies (only if not dry-run)
if [ "$DRY_RUN" = false ] && [ -x "$REPO_DIR/config-check.sh" ]; then
    log_info "Running config-check.sh to verify dependencies..."
    "$REPO_DIR/config-check.sh"
elif [ "$DRY_RUN" = true ] && [ -x "$REPO_DIR/config-check.sh" ]; then
    log_info "DRY RUN: would run config-check.sh"
else
    log_warn "config-check.sh not found – skipping dependency check."
fi
