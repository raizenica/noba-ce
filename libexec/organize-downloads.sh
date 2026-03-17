#!/bin/bash
# organize-downloads.sh – Move files from Downloads into categorized folders
# Version: 1.1.0

set -euo pipefail

# -------------------------------------------------------------------
# Configuration & Defaults
# -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

DOWNLOAD_DIR="${HOME}/Downloads"
LOG_DIR="${HOME}/.local/share"
UNDO_LOG="$LOG_DIR/download-organizer-undo.log"
DRY_RUN=false
MOVED_COUNT=0

declare -A CATEGORY_COUNTS=()

# Extension Map
declare -A EXT_MAP=(
    ["jpg"]="Images" ["jpeg"]="Images" ["png"]="Images" ["gif"]="Images" ["svg"]="Images" ["webp"]="Images"
    ["mp4"]="Video" ["mkv"]="Video" ["avi"]="Video" ["mov"]="Video" ["webm"]="Video"
    ["mp3"]="Audio" ["wav"]="Audio" ["flac"]="Audio" ["m4a"]="Audio"
    ["pdf"]="Documents" ["doc"]="Documents" ["docx"]="Documents" ["txt"]="Documents" ["md"]="Documents"
    ["zip"]="Archives" ["tar"]="Archives" ["gz"]="Archives" ["rar"]="Archives" ["7z"]="Archives"
    ["iso"]="DiskImages"
    ["exe"]="Executables" ["AppImage"]="Executables" ["rpm"]="Executables" ["deb"]="Executables"
)

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    DOWNLOAD_DIR="$(get_config ".downloads.dir" "$DOWNLOAD_DIR")"
    DOWNLOAD_DIR="${DOWNLOAD_DIR/#\~/$HOME}"

    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    LOG_DIR="${config_log_dir/#\~/$HOME}"
    UNDO_LOG="$LOG_DIR/download-organizer-undo.log"
fi

# -------------------------------------------------------------------
# Argument Parsing
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --help)
            echo "Usage: organize-downloads.sh [--dry-run]"
            exit 0 ;;
        *) log_error "Unknown flag: $1"; exit 1 ;;
    esac
done

if [[ ! -d "$DOWNLOAD_DIR" ]]; then
    log_error "Download directory does not exist: $DOWNLOAD_DIR"
    exit 1
fi

# -------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------
log_info "Organizing downloads in: $DOWNLOAD_DIR"
[[ "$DRY_RUN" == true ]] && log_info "[DRY RUN MODE] No files will actually be moved."

mkdir -p "$LOG_DIR"
_UNDO_TMP="${UNDO_LOG}.tmp"
> "$_UNDO_TMP"

while IFS= read -r -d '' file; do
    filename=$(basename "$file")

    # Skip directories
    [[ -d "$file" ]] && continue

    # Get extension
    ext="${filename##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    # Find category, default to 'Other'
    category="${EXT_MAP[$ext]:-Other}"

    dest_folder="$DOWNLOAD_DIR/$category"

    # Skip if already in correct folder
    if [[ "$(dirname "$file")" == "$dest_folder" ]]; then
        continue
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would move: $filename -> $category/"
    else
        mkdir -p "$dest_folder"

        # Handle collisions securely
        dest_file="$dest_folder/$filename"
        if [[ -e "$dest_file" ]]; then
            dest_file="$dest_folder/${filename%.*}_$(date +%s).${ext}"
        fi

        if mv "$file" "$dest_file"; then
            echo "${dest_file}|${file}" >> "$_UNDO_TMP"
            log_verbose "Moved: $filename -> $category/"
        else
            log_error "Failed to move: $filename"
        fi
    fi

    CATEGORY_COUNTS["$category"]=$(( ${CATEGORY_COUNTS["$category"]:-0} + 1 ))
    (( MOVED_COUNT++ )) || true

done < <(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -not -name '.*' -print0)

# -------------------------------------------------------------------
# Wrap up
# -------------------------------------------------------------------
if [[ "$DRY_RUN" != true && -s "$_UNDO_TMP" ]]; then
    cat "$_UNDO_TMP" >> "$UNDO_LOG"
fi
rm -f "$_UNDO_TMP"

log_info "=========================================="
log_info "  Finished Organizing"
log_info "  Total moved: $MOVED_COUNT file(s)"
for cat in "${!CATEGORY_COUNTS[@]}"; do
    log_info "    - $cat: ${CATEGORY_COUNTS[$cat]}"
done
log_info "=========================================="
