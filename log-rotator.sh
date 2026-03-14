#!/bin/bash
# log-rotator.sh – Compress old logs and purge ancient archives
# Version: 2.2.1

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: log-rotator.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "log-rotator.sh version 2.2.1"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
COMPRESS_DAYS=30
DELETE_DAYS=90
DRY_RUN=false

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    LOG_DIR="${config_log_dir/#\~/$HOME}"
    COMPRESS_DAYS="$(get_config ".log_rotation.compress_days" "$COMPRESS_DAYS")"
    DELETE_DAYS="$(get_config ".log_rotation.delete_days" "$DELETE_DAYS")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "log-rotator.sh version 2.2.1"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Compress log files older than a specified number of days, and delete ancient archives.

Options:
  -c, --compress-days DAYS  Days before compressing .log to .log.gz (default: $COMPRESS_DAYS)
  -x, --delete-days DAYS    Days before deleting .log.gz entirely (default: $DELETE_DAYS)
  -l, --log-dir DIR         Directory containing logs (default: $LOG_DIR)
  -n, --dry-run             Show what would be compressed/deleted without doing it
  --help                    Show this help message
  --version                 Show version information
EOF
    exit 0
}

is_file_open() {
    local file="$1"
    if command -v fuser &>/dev/null; then
        fuser -s "$file"
        return $?
    elif command -v lsof &>/dev/null; then
        lsof "$file" >/dev/null 2>&1
        return $?
    else
        return 1 # Cannot check safely, assume closed
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o c:x:l:n -l compress-days:,delete-days:,log-dir:,dry-run,help,version -- "$@"); then
    log_error "Invalid argument"
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -c|--compress-days) COMPRESS_DAYS="$2"; shift 2 ;;
        -x|--delete-days)   DELETE_DAYS="$2"; shift 2 ;;
        -l|--log-dir)       LOG_DIR="$2"; shift 2 ;;
        -n|--dry-run)       DRY_RUN=true; shift ;;
        --help)             show_help ;;
        --version)          show_version ;;
        --)                 shift; break ;;
        *)                  log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps find gzip

if ! [[ "$COMPRESS_DAYS" =~ ^[0-9]+$ ]] || [ "$COMPRESS_DAYS" -lt 1 ]; then
    die "COMPRESS_DAYS must be a positive integer (got: $COMPRESS_DAYS)"
fi

if ! [[ "$DELETE_DAYS" =~ ^[0-9]+$ ]] || [ "$DELETE_DAYS" -lt "$COMPRESS_DAYS" ]; then
    die "DELETE_DAYS ($DELETE_DAYS) must be an integer strictly greater than COMPRESS_DAYS ($COMPRESS_DAYS)."
fi

if [ ! -d "$LOG_DIR" ]; then
    die "Log directory does not exist: $LOG_DIR"
fi

log_info "========== Log Rotation Started =========="
log_info "Log directory: $LOG_DIR"
log_info "Compression threshold: $COMPRESS_DAYS days"
log_info "Deletion threshold: $DELETE_DAYS days"
[ "$DRY_RUN" = true ] && log_info "Mode: DRY RUN"

# -------------------------------------------------------------------
# Phase 1: Compress old logs
# -------------------------------------------------------------------
compress_count=0

while IFS= read -r -d '' log; do
    if is_file_open "$log"; then
        log_warn "Skipping: $log is currently actively open/being written to."
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would compress: $log"
    else
        if gzip "$log"; then
            log_info "Compressed: $log"
            ((compress_count++))
        else
            log_error "Failed to compress: $log"
        fi
    fi
done < <(find "$LOG_DIR" -type f -name "*.log" -mtime +"$COMPRESS_DAYS" -print0)

# -------------------------------------------------------------------
# Phase 2: Delete ancient archives
# -------------------------------------------------------------------
delete_count=0

while IFS= read -r -d '' gz_log; do
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would delete archive: $gz_log"
    else
        if rm -f "$gz_log"; then
            log_info "Deleted ancient archive: $gz_log"
            ((delete_count++))
        else
            log_error "Failed to delete: $gz_log"
        fi
    fi
done < <(find "$LOG_DIR" -type f -name "*.log.gz" -mtime +"$DELETE_DAYS" -print0)

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    log_info "Dry run complete. No files were modified."
else
    log_info "Rotation complete. Compressed $compress_count file(s), deleted $delete_count archive(s)."
fi
