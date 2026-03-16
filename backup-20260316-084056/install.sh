#!/bin/bash
# install.sh – Smart installer for Nobara Automation Suite
# Version: 1.0.0

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: install.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "install.sh version 1.0.0"; exit 0
fi

# ── Defaults ───────────────────────────────────────────────────────────────────
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="${BIN_DIR:-$PREFIX/bin}"
LIBEXEC_DIR="${LIBEXEC_DIR:-$PREFIX/libexec/noba}"
SHARE_DIR="${SHARE_DIR:-$PREFIX/share/noba-web}"
MAN_DIR="${MAN_DIR:-$PREFIX/share/man/man1}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/noba}"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
SKIP_DEPS=false
UNINSTALL=false
NO_COMPLETION=false
NO_SYSTEMD=false
USER_EMAIL="${EMAIL:-}"

MANIFEST_FILE="${MANIFEST_FILE:-$HOME/.local/share/noba-install.manifest}"

# Read version from VERSION file
if [[ -f "$SCRIPT_DIR/VERSION" ]]; then
    NOBA_VERSION=$(cat "$SCRIPT_DIR/VERSION")
else
    NOBA_VERSION="unknown"
fi

# ── Whitelist of suite scripts ─────────────────────────────────────────────────
SUITE_SCRIPTS=(
    backup-to-nas.sh
    backup-verifier.sh
    backup-notify.sh
    checksum.sh
    cloud-backup.sh
    config-check.sh
    disk-sentinel.sh
    images-to-pdf.sh
    organize-downloads.sh
)
OPTIONAL_SCRIPTS=(
    noba-tui.sh
    noba-dashboard.sh
    motd-generator.sh
    run-hogwarts-trainer.sh
    noba-update.sh
    noba-completion.sh
)

# ── Functions ──────────────────────────────────────────────────────────────────
say()     { printf '  %s\n' "$@"; }
say_ok()  { printf '  \033[0;32m✓\033[0m %s\n' "$@"; }
say_warn(){ printf '  \033[0;33m⚠\033[0m %s\n' "$@"; }
say_err() { printf '  \033[0;31m✗\033[0m %s\n' "$@" >&2; }
header()  { printf '\n\033[1m%s\033[0m\n' "$@"; }
dry()     { [[ "$DRY_RUN" == true ]] && printf '  [DRY RUN] %s\n' "$@"; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install the Nobara Automation Suite.

Options:
  -d, --dir DIR          Bin directory for wrapper (default: $BIN_DIR)
      --prefix DIR       Base installation prefix (default: $PREFIX)
  -c, --config DIR       Configuration directory (default: $CONFIG_DIR)
  -s, --systemd DIR      Systemd user unit directory (default: $SYSTEMD_USER_DIR)
      --email ADDR       Pre-fill email address in generated config
      --skip-deps        Skip dependency installation
      --no-completion    Skip shell completion setup
      --no-systemd       Skip systemd unit installation and reload
  -u, --uninstall        Remove a previously installed suite (reads manifest)
  -n, --dry-run          Show what would be done without making changes
  -h, --help             Show this message
  -v, --version          Show version information
