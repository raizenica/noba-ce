#!/usr/bin/env bash
# noba-update.sh – Pull latest scripts from git, deploy, and optionally update system
# Version: 3.0.0

set -euo pipefail

VERSION="3.0.0"

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then
    exit 1
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: noba-update.sh [OPTIONS]"
    exit 0
fi

if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "noba-update.sh version $VERSION"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
# The repo now lives in ~/.local/bin, while this script runs from libexec
REPO_DIR="$HOME/.local/bin"
REMOTE="origin"
BRANCH="main"
UPDATE_SYSTEM=false
AUTO_YES=false
DRY_RUN=false

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config >/dev/null 2>&1; then
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
    echo "noba-update.sh version $VERSION"
    exit 0
}

show_help() {

cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Pull the latest version of all noba scripts from git, deploy them, and update the system.

Options:
  --repo DIR        Repository directory (default: $REPO_DIR)
  --remote NAME     Git remote name (default: $REMOTE)
  --branch NAME     Git branch name (default: $BRANCH)
  --system          Also run system updates (dnf and flatpak)
  --auto-yes        Auto-confirm package updates (non-interactive)
  --dry-run         Show what would be done without performing changes
  --help            Show this help message
  --version         Show version information
EOF

exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o '' \
    -l repo:,remote:,branch:,system,auto-yes,dry-run,help,version \
    -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 1
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
        *)           log_error "Internal argument parser error."; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------
check_deps git

if [[ ! -d "$REPO_DIR" ]]; then
    die "Repository directory '$REPO_DIR' does not exist."
fi

cd "$REPO_DIR" || die "Cannot access '$REPO_DIR'"

log_info "Starting Nobara suite update..."

# -------------------------------------------------------------------
# Git update logic
# -------------------------------------------------------------------
UPDATED_GIT=false

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then

    # Check for local modifications
    if ! git diff --quiet || ! git diff --cached --quiet; then
        log_warn "Uncommitted changes detected in repository."
        if [[ "$AUTO_YES" != true && "$DRY_RUN" != true ]]; then
            if ! confirm "Pull changes and risk overwriting local edits?" "n"; then
                die "Update aborted by user."
            fi
        fi
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would fetch and pull $REMOTE/$BRANCH in $REPO_DIR"
    else
        log_info "Fetching updates from $REMOTE..."
        git fetch "$REMOTE" "$BRANCH"

        # Check if we are actually behind the remote before pulling
        LOCAL_REV=$(git rev-parse HEAD)
        REMOTE_REV=$(git rev-parse "$REMOTE/$BRANCH")

        if [[ "$LOCAL_REV" != "$REMOTE_REV" ]]; then
            log_info "Pulling latest changes..."
            if ! git pull --ff-only "$REMOTE" "$BRANCH"; then
                log_warn "Fast-forward pull failed. Manual merge may be required."
            else
                UPDATED_GIT=true
            fi
        else
            log_info "Noba suite is already up to date."
        fi
    fi

else
    log_warn "$REPO_DIR is not a git repository. Skipping git update."
fi

# -------------------------------------------------------------------
# Deployment & Systemd Reload
# -------------------------------------------------------------------
if [[ "$DRY_RUN" == true ]]; then
    log_info "[DRY RUN] Would run ./install.sh to deploy updates to libexec"
    log_info "[DRY RUN] Would run systemctl --user daemon-reload"
elif [[ "$UPDATED_GIT" == true ]]; then
    log_info "Deploying updated scripts to execution directory..."

    # Ensure install script is executable
    [[ -f "install.sh" ]] && chmod +x install.sh

    if [[ -x "./install.sh" ]]; then
        ./install.sh >/dev/null
        log_success "Deployment successful."

        log_info "Reloading systemd user daemon..."
        systemctl --user daemon-reload
        # Optional: Restart the web dashboard so it instantly picks up new backend changes
        systemctl --user try-restart noba-web.service 2>/dev/null || true
    else
        log_error "Could not find executable ./install.sh in $REPO_DIR"
    fi
fi

# -------------------------------------------------------------------
# System updates
# -------------------------------------------------------------------
if [[ "$UPDATE_SYSTEM" == true ]]; then

    if command -v dnf >/dev/null 2>&1; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY RUN] Would run: sudo dnf update"
        else
            log_info "Running DNF system update..."
            if [[ "$AUTO_YES" == true ]]; then
                sudo -n dnf update -y || log_warn "DNF update failed or sudo password required."
            else
                sudo dnf update || log_warn "DNF update failed."
            fi
        fi
    fi

    if command -v flatpak >/dev/null 2>&1; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY RUN] Would run: flatpak update"
        else
            log_info "Running Flatpak update..."
            if [[ "$AUTO_YES" == true ]]; then
                flatpak update -y || log_warn "Flatpak update failed."
            else
                flatpak update || log_warn "Flatpak update failed."
            fi
        fi
    fi
fi

if [[ "$DRY_RUN" == true ]]; then
    log_info "Dry run complete."
else
    log_success "Update sequence finished."
fi
