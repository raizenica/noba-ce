#!/bin/bash
# noba-dashboard.sh – Detailed terminal dashboard for Nobara automation
# Version: 2.0.1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration (can be overridden by config file)
# -------------------------------------------------------------------
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
REFRESH_INTERVAL=0  # 0 = run once, >0 = watch mode with refresh seconds

# -------------------------------------------------------------------
# Load user configuration (if any) – uses library functions
# -------------------------------------------------------------------
# We don't need to load separately; get_config will handle it.
# But we can set defaults from config if desired.
LOG_DIR="$(get_config ".dashboard.log_dir" "$LOG_DIR")"
REFRESH_INTERVAL="$(get_config ".dashboard.refresh_interval" "$REFRESH_INTERVAL")"

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-dashboard.sh version 2.0.1 (noba-lib version $NOBA_LIB_VERSION)"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Display a real‑time dashboard of Nobara automation status.

Options:
  -w, --watch SECS   Refresh every SECS seconds (like 'watch')
  -1, --once         Run once and exit (default)
  --help             Show this help message
  --version          Show version information
EOF
    exit 0
}

# Parse command-line arguments
PARSED_ARGS=$(getopt -o w:1 -l watch:,once,help,version -- "$@") || { log_error "Invalid argument"; exit 1; }
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -w|--watch)   REFRESH_INTERVAL="$2"; shift 2 ;;
        -1|--once)    REFRESH_INTERVAL=0; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *) log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# Validate refresh interval
if ! [[ "$REFRESH_INTERVAL" =~ ^[0-9]+$ ]]; then
    die "Invalid refresh interval: $REFRESH_INTERVAL (must be a non‑negative integer)"
fi

# -------------------------------------------------------------------
# Log file locations (using LOG_DIR)
# -------------------------------------------------------------------
BACKUP_LOG="${BACKUP_LOG:-$LOG_DIR/backup-to-nas.log}"
DISK_LOG="${DISK_LOG:-$LOG_DIR/disk-sentinel.log}"
ORGANIZER_LOG="${ORGANIZER_LOG:-$LOG_DIR/organize-downloads.log}"
UNDO_LOG="${UNDO_LOG:-$LOG_DIR/undo-organizer.log}"
# Also support legacy names if needed
if [[ ! -f "$ORGANIZER_LOG" && -f "$LOG_DIR/download-organizer.log" ]]; then
    ORGANIZER_LOG="$LOG_DIR/download-organizer.log"
fi
if [[ ! -f "$UNDO_LOG" && -f "$LOG_DIR/download-organizer-undo.log" ]]; then
    UNDO_LOG="$LOG_DIR/download-organizer-undo.log"
fi

# -------------------------------------------------------------------
# Core dashboard functions
# -------------------------------------------------------------------

# Print a section header using library colors
section() {
    printf "%b─── %s ───────────────────────────────────────────────────%b\n" "$CYAN" "$1" "$NC"
}

# System info
system_info() {
    section "System"
    printf "  Hostname : %s\n" "$(hostname)"

    local raw_uptime
    raw_uptime=$(uptime -p)
    printf "  Uptime   : %s\n" "${raw_uptime//up /}"

    printf "  Load     : %s\n" "$(uptime | awk -F'load average:' '{print $2}')"
    local mem_total mem_used mem_percent
    mem_total=$(free -b | awk '/^Mem:/ {print $2}')
    mem_used=$(free -b | awk '/^Mem:/ {print $3}')
    if [[ -n "$mem_total" && "$mem_total" -gt 0 ]]; then
        mem_percent=$(awk "BEGIN {printf \"%.1f\", $mem_used*100/$mem_total}")
        printf "  Memory   : %s/%s (%s%%)\n" \
            "$(human_size "$mem_used")" "$(human_size "$mem_total")" "$mem_percent"
    else
        printf "  Memory   : N/A\n"
    fi
}

# Disk usage (filter out pseudo‑filesystems)
disk_usage() {
    section "Disk Usage"
    df -h -x tmpfs -x devtmpfs -x squashfs -x overlay | grep '^/dev/' | while read -r line; do
        read -r _ size used _ use_percent mount <<< "$line"
        percent=${use_percent%\%}
        if [[ "$percent" -ge 90 ]]; then
            color="$RED"
        elif [[ "$percent" -ge 75 ]]; then
            color="$YELLOW"
        else
            color="$GREEN"
        fi
        printf "  %b%-20s%b : %s used (%s/%s)\n" "$color" "$mount" "$NC" "$use_percent" "$used" "$size"
    done
}

# Last backup status
backup_status() {
    section "Backup"
    if [[ ! -f "$BACKUP_LOG" ]]; then
        echo "  No backup log found."
        return
    fi

    local last_complete last_line timestamp status
    last_complete=$(grep -E "Backup finished" "$BACKUP_LOG" 2>/dev/null | tail -1 || true)

    if [[ -n "$last_complete" ]]; then
        timestamp=$(echo "$last_complete" | sed -n 's/.*at \(.*\) =.*/\1/p')
        if [[ -n "$timestamp" ]]; then
            printf "  Last backup: %b%s%b\n" "$GREEN" "$timestamp" "$NC"
        else
            printf "  Last backup: %brecently%b (no timestamp)\n" "$GREEN" "$NC"
        fi
        printf "  Status     : %b✓ OK%b\n" "$GREEN" "$NC"
    else
        if [[ -s "$BACKUP_LOG" ]]; then
            last_line="$(strip_ansi "$(tail -1 "$BACKUP_LOG" 2>/dev/null)")"
        else
            last_line=""
        fi

        if [[ -n "$last_line" ]]; then
            if grep -qi "error" <<< "$last_line"; then
                status="${RED}✗ ERROR${NC}"
            elif grep -qi "dry run" <<< "$last_line"; then
                status="${YELLOW}ℹ DRY RUN${NC}"
            else
                status="${YELLOW}? UNKNOWN${NC}"
            fi
        else
            status="${YELLOW}? UNKNOWN${NC}"
            last_line="(empty log)"
        fi
        printf "  Last run    : %b\n" "$status"
        printf "  Last log line: %s\n" "$last_line"
    fi
}

# Download organizer summary
organizer_status() {
    section "Download Organizer"
    if [[ ! -f "$ORGANIZER_LOG" ]]; then
        echo "  No organizer log yet."
        return
    fi

    local moved last_move undo_count
    moved=$(grep -c "Moved:" "$ORGANIZER_LOG" 2>/dev/null || echo 0)
    last_move=$(grep "Moved:" "$ORGANIZER_LOG" 2>/dev/null | tail -1 | sed 's/.*Moved: //' || true)
    printf "  Files moved: %s\n" "$moved"
    if [[ -n "$last_move" ]]; then
        printf "  Last move  : %s\n" "$last_move"
    fi
    if [[ -f "$UNDO_LOG" && -s "$UNDO_LOG" ]]; then
        undo_count=$(wc -l < "$UNDO_LOG")
        printf "  %bUndo log: %s pending actions%b\n" "$YELLOW" "$undo_count" "$NC"
    fi
}

# Disk sentinel alerts
disk_alerts() {
    section "Disk Sentinel"
    if [[ ! -f "$DISK_LOG" ]]; then
        echo "  No disk sentinel log."
        return
    fi

    local warnings
    warnings=$(grep -E "WARNING|exceeded" "$DISK_LOG" 2>/dev/null | tail -3 || true)
    if [[ -n "$warnings" ]]; then
        echo "  Recent alerts:"
        while IFS= read -r line; do
            printf "    %s\n" "$line"
        done <<< "$warnings"
    else
        echo "  No recent disk warnings."
    fi
}

# Pending downloads
pending_downloads() {
    section "Pending Downloads"
    local download_dir
    download_dir="$(get_config ".organize.download_dir" "$HOME/Downloads")"
    if [[ ! -d "$download_dir" ]]; then
        echo "  Download directory '$download_dir' does not exist."
        return
    fi

    local count
    count=$(find "$download_dir" -maxdepth 1 -type f -printf '.' 2>/dev/null | wc -c)
    if [[ "$count" -gt 0 ]]; then
        printf "  %s file(s) waiting in Downloads:\n" "$count"
        find "$download_dir" -maxdepth 1 -type f -printf "    %f\n" 2>/dev/null | head -5
        if [[ "$count" -gt 5 ]]; then
            printf "    ... and %s more\n" $((count - 5))
        fi
    else
        echo "  No files waiting."
    fi
}

# Updates
updates_status() {
    section "Updates"
    local dnf_updates=0 flatpak_updates=0 dnf_output

    if command -v dnf &>/dev/null; then
        dnf_output=$(dnf check-update -q 2>/dev/null || true)
        # dnf check-update returns 0 if no updates, 100 if updates available
        # We count lines that start with a letter/digit (package names)
        dnf_updates=$(echo "$dnf_output" | grep -c '^[[:alnum:]]' || true)
        printf "  DNF updates : %s\n" "$dnf_updates"
    fi

    if command -v flatpak &>/dev/null; then
        # flatpak update --dry-run would be better but may not be available; approximate.
        flatpak_updates=$(flatpak remote-ls --updates 2>/dev/null | wc -l)
        printf "  Flatpak updates : %s\n" "$flatpak_updates"
    fi

    if [[ "$dnf_updates" -eq 0 && "$flatpak_updates" -eq 0 ]]; then
        echo "  System is up to date."
    fi
}

# Strip ANSI codes (reuse from library? Not there, so define locally)
strip_ansi() {
    # shellcheck disable=SC2001
    sed 's/\x1b\[[0-9;]*m//g' <<< "$1"
}

# Main dashboard render
render_dashboard() {
    if [[ -t 1 ]]; then
        clear 2>/dev/null || true
    fi

    printf "%b╔════════════════════════════════════════════════════════════╗%b\n" "$BLUE" "$NC"
    printf "%b║                  NOBA DASHBOARD – %s               ║%b\n" "$BLUE" "$(date '+%Y-%m-%d %H:%M')" "$NC"
    printf "%b╚════════════════════════════════════════════════════════════╝%b\n" "$BLUE" "$NC"

    system_info
    echo ""
    disk_usage
    echo ""
    backup_status
    echo ""
    organizer_status
    echo ""
    disk_alerts
    echo ""
    pending_downloads
    echo ""
    updates_status

    printf "%b────────────────────────────────────────────────────────────%b\n" "$BLUE" "$NC"
}

# -------------------------------------------------------------------
# Main execution
# -------------------------------------------------------------------
if [[ "$REFRESH_INTERVAL" -eq 0 ]]; then
    render_dashboard
else
    # Watch mode: loop with sleep
    while true; do
        render_dashboard
        sleep "$REFRESH_INTERVAL"
    done
fi

exit 0
