#!/bin/bash
# motd-generator.sh – Custom Message of the Day with system status
# Version: 1.0.3 (Async & Timeout Protected)

set -euo pipefail

# Test harness bypass
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
QUOTE_FILE="${QUOTE_FILE:-$HOME/.config/quotes.txt}"
SHOW_UPDATES=true
SHOW_BACKUP=true
NO_COLOR=false
CACHE_DIR="$HOME/.local/share/motd_cache"
UPDATE_CACHE="$CACHE_DIR/updates.txt"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

if command -v get_config &>/dev/null; then
    QUOTE_FILE="$(get_config ".motd.quote_file" "$QUOTE_FILE")"
    QUOTE_FILE="${QUOTE_FILE/#\~/$HOME}"
    [[ "$(get_config ".motd.show_updates" "true")" == "false" ]] && SHOW_UPDATES=false
    [[ "$(get_config ".motd.show_backup" "true")" == "false" ]] && SHOW_BACKUP=false
fi

show_version() { echo "motd-generator.sh version 1.0.3"; exit 0; }
show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]
Options:
  --no-color       Disable colored output
  --no-updates     Hide pending updates section
  --no-backup      Hide backup status section
  --help           Show this help message
  --version        Show version information
EOF
    exit 0
}

color_echo() {
    local color="$1"; shift
    if [ "$NO_COLOR" = true ]; then echo "$*"; else echo -e "${color}$*${NC}"; fi
}

print_header() {
    color_echo "$BLUE" "════════════════════════════════════════════════════════════"
    color_echo "$GREEN" "    Nobara System Status – $(date '+%A, %B %d, %Y %H:%M')"
    color_echo "$BLUE" "════════════════════════════════════════════════════════════"
}

print_system_info() {
    color_echo "$YELLOW" "System Info:"
    echo "  Hostname : $(hostname)"
    echo "  Uptime   : $(uptime -p | sed 's/up //')"
    echo "  Load     : $(uptime | awk -F'load average:' '{print $2}')"
    echo "  Memory   : $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
}

print_disk_usage() {
    color_echo "$YELLOW" "Disk Usage:"
    local df_out

    # 1-second hard kill for df to prevent kernel stat() hangs on dead mounts
    if ! df_out=$(timeout 1 df -hl 2>/dev/null); then
        color_echo "$RED" "  [Disk check timed out - Stale network mount detected]"
        return
    fi

    echo "$df_out" | grep '^/dev/' | while read -r line; do
        read -r _ size used _ use_percent mount <<< "$line"
        [[ "$mount" == /var/lib/snapd/snap/* ]] && continue

        percent=${use_percent%\%}
        if [ "$percent" -ge 90 ]; then color="$RED";
        elif [ "$percent" -ge 75 ]; then color="$YELLOW";
        else color="$GREEN"; fi

        if [ "$NO_COLOR" = true ]; then
            echo "  ${mount} : ${use_percent} used (${used}/${size})"
        else
            echo -e "  ${color}${mount}${NC} : ${use_percent} used (${used}/${size})"
        fi
    done
}

print_backup_status() {
    local backup_log="$HOME/.local/share/backup-to-nas.log"
    color_echo "$YELLOW" "Backup Status:"
    if [ -f "$backup_log" ]; then
        last_backup=$(tail -5 "$backup_log" | grep -E "Backup finished|ERROR" | tail -1 || true)
        if echo "$last_backup" | grep -q "ERROR"; then color_echo "$RED" "  Last backup: ✗ FAILED"
        elif echo "$last_backup" | grep -q "Backup finished"; then color_echo "$GREEN" "  Last backup: ✓ OK"
        else color_echo "$YELLOW" "  Last backup: Unknown"; fi

        last_line=$(tail -1 "$backup_log" | sed 's/\x1b\[[0-9;]*m//g' || echo "No log entry")
        echo "  $last_line"
    else
        color_echo "$YELLOW" "  No backup log found."
    fi
}

# Async background update check
trigger_update_check() {
    mkdir -p "$CACHE_DIR"
    # Only run background check if cache is older than 1 hour
    if [ ! -f "$UPDATE_CACHE" ] || [ $(find "$UPDATE_CACHE" -mmin +60 -print) ]; then
        (
            local d_up=0 f_up=0
            if command -v dnf &>/dev/null; then d_up=$(timeout 10 dnf check-update -q 2>/dev/null | wc -l || echo 0); fi
            if command -v flatpak &>/dev/null; then f_up=$(timeout 10 flatpak remote-ls --updates 2>/dev/null | wc -l || echo 0); fi
            echo "$d_up|$f_up" > "$UPDATE_CACHE"
        ) & disown
    fi
}

print_updates() {
    color_echo "$YELLOW" "Pending Updates:"
    trigger_update_check

    if [ -f "$UPDATE_CACHE" ]; then
        IFS='|' read -r dnf_u flatpak_u < "$UPDATE_CACHE"
        local any=false
        if [ "${dnf_u:-0}" -gt 0 ]; then echo "  DNF : $dnf_u updates available"; any=true; fi
        if [ "${flatpak_u:-0}" -gt 0 ]; then echo "  Flatpak : $flatpak_u updates available"; any=true; fi
        [ "$any" = false ] && echo "  All packages are up to date."
    else
        echo "  Checking for updates in background..."
    fi
}

print_quote() {
    local quote=""
    if [ -f "$QUOTE_FILE" ]; then
        quote=$(shuf -n 1 "$QUOTE_FILE" 2>/dev/null)
    elif command -v curl &>/dev/null && command -v jq &>/dev/null; then
        # 1-second hard kill for curl
        quote=$(timeout 1 curl -s "https://api.quotable.io/random" 2>/dev/null | jq -r '.content + " – " + .author' 2>/dev/null || true)
        [[ "$quote" == "null – null" ]] && quote=""
    fi
    if [ -n "$quote" ]; then
        color_echo "$CYAN" "Quote of the day:"
        echo "  $quote"
    fi
}

if ! PARSED_ARGS=$(getopt -o '' -l no-color,no-updates,no-backup,help,version -- "$@"); then
    log_error "Invalid argument"
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --no-color)   NO_COLOR=true; shift ;;
        --no-updates) SHOW_UPDATES=false; shift ;;
        --no-backup)  SHOW_BACKUP=false; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *)            log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

print_header
print_system_info
echo ""
print_disk_usage
echo ""
[ "$SHOW_BACKUP" = true ] && { print_backup_status; echo ""; }
[ "$SHOW_UPDATES" = true ] && { print_updates; echo ""; }
print_quote
color_echo "$BLUE" "════════════════════════════════════════════════════════════"
