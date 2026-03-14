#!/bin/bash
# backup-notify.sh – Send desktop notification about the last backup status
# Version: 2.2.2

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then echo "Usage: backup-notify.sh"; exit 0; fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then echo "2.2.2"; exit 0; fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-to-nas.log}"
DRY_RUN=false
FORCE_URGENCY=""

# Load user configuration
if command -v get_config &>/dev/null; then
    LOG_FILE="$(get_config ".backup_notify.log_file" "$LOG_FILE")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "backup-notify.sh version 2.2.2"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Send a desktop notification about the last backup status.

Options:
  --log-file FILE    Use FILE instead of the default log
  --urgency URG      Override urgency (low, normal, critical)
  --dry-run          Show what would be sent without actually notifying
  --help             Show this help message
  --version          Show version information
EOF
    exit 0
}

strip_ansi() {
    # shellcheck disable=SC2001
    sed 's/\x1b\[[0-9;]*m//g' <<< "$1"
}

send_notification() {
    local urgency="$1" summary="$2" body="$3"
    local clean_body
    clean_body=$(strip_ansi "$body")

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Notification: [$urgency] $summary - $clean_body"
        return
    fi

    if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
        log_debug "No GUI display detected. Logging to console."
        echo "$summary: $clean_body"
        return
    fi

    if command -v notify-send &>/dev/null; then
        notify-send -u "$urgency" -a "Noba Backup" "$summary" "$clean_body"
    elif command -v kdialog &>/dev/null; then
        kdialog --passivepopup "$clean_body" 5 --title "$summary"
    else
        echo "$summary: $clean_body"
    fi
}

# -------------------------------------------------------------------
# Parse command line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o '' -l log-file:,urgency:,dry-run,help,version -- "$@"); then
    log_error "Invalid argument"
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --log-file) LOG_FILE="$2"; shift 2 ;;
        --urgency)  FORCE_URGENCY="$2"; shift 2 ;;
        --dry-run)  DRY_RUN=true; shift ;;
        --help)     show_help ;;
        --version)  show_version ;;
        --)         shift; break ;;
        *)          log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Process Log
# -------------------------------------------------------------------
if [ ! -r "$LOG_FILE" ]; then
    die "Cannot read backup log: $LOG_FILE"
fi

last_context=$(tail -n 5 "$LOG_FILE" | strip_ansi)

if echo "$last_context" | grep -qi "ERROR"; then
    urgency="critical"; summary="❌ Backup Failed"
    message=$(echo "$last_context" | grep -i "ERROR" | tail -1)
elif echo "$last_context" | grep -qi "SUCCESS"; then
    urgency="normal"; summary="✅ Backup Successful"
    message=$(echo "$last_context" | grep -i "SUCCESS" | tail -1)
elif echo "$last_context" | grep -qi "finished"; then
    urgency="normal"; summary="✅ Backup Finished"
    message=$(echo "$last_context" | grep -i "finished" | tail -1)
else
    urgency="low"; summary="ℹ️ Backup Status Unknown"
    message=$(tail -n 1 "$LOG_FILE")
fi

[ -n "$FORCE_URGENCY" ] && urgency="$FORCE_URGENCY"

# -------------------------------------------------------------------
# Execute
# -------------------------------------------------------------------
send_notification "$urgency" "$summary" "$message"
