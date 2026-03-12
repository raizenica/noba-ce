#!/bin/bash
# Download organizer – move files into categorized folders with CLI and config

set -u
set -o pipefail

# Defaults
CONFIG_FILE="$HOME/.config/download-organizer.cfg"
LOG_FILE="$HOME/.local/share/download-organizer.log"
UNDO_LOG="$HOME/.local/share/download-organizer-undo.log"
DRY_RUN=false
QUIET=false

# Function to show usage
usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -c, --config FILE   Use custom config file (default: ~/.config/download-organizer.cfg)
  -d, --dry-run       Show what would be moved without actually moving
  -q, --quiet         Suppress normal output (only errors)
  --help              Show this help

The config file should define CATEGORIES as a bash associative array.
See default config below.
EOF
    exit 0
}

# Parse command-line arguments
OPTIONS=$(getopt -o c:dq -l config:,dry-run,quiet,help -- "$@")
if [ $? -ne 0 ]; then
    usage
fi
eval set -- "$OPTIONS"

while true; do
    case "$1" in
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -q|--quiet)
            QUIET=true
            shift
            ;;
        --help)
            usage
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Internal error!"
            exit 1
            ;;
    esac
done

# Load config file if exists, otherwise use defaults
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
else
    # Default categories
    declare -A CATEGORIES=(
        ["Images"]="jpg jpeg png gif bmp svg webp tiff"
        ["Documents"]="pdf doc docx txt odt rtf md"
        ["Archives"]="zip tar gz bz2 xz 7z rar"
        ["Audio"]="mp3 wav flac ogg m4a"
        ["Video"]="mp4 mkv avi mov wmv"
        ["Code"]="sh py js html css c cpp h json yaml"
        ["Torrents"]="torrent"
        ["Installers"]="deb rpm appimage flatpakref"
        ["Others"]=""
    )
fi

# Override with environment variables? (optional)
DOWNLOAD_DIR="${DOWNLOAD_DIR:-$HOME/Downloads}"
MIN_AGE_MINUTES="${MIN_AGE_MINUTES:-5}"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$UNDO_LOG")"

log() {
    if [ "$QUIET" = false ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
        echo "$1"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
    fi
}

undo_log() {
    # Record move in undo log (src dest)
    echo "$1|$2" >> "$UNDO_LOG"
}

# Function to check if file is open
is_file_open() {
    lsof "$1" >/dev/null 2>&1
}

# Dry-run or real move with undo logging
move_file() {
    local src="$1"
    local dest="$2"
    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would move: $src → $dest"
    else
        mkdir -p "$(dirname "$dest")"
        mv "$src" "$dest"
        log "Moved: $src → $dest"
        undo_log "$src" "$dest"
    fi
}

# Main loop
log "=== Starting download organization ==="

find "$DOWNLOAD_DIR" -maxdepth 1 -type f -not -path '*/\.*' | while read -r file; do
    # Skip files newer than MIN_AGE_MINUTES
    if [ $(find "$file" -mmin -$MIN_AGE_MINUTES -print) ]; then
        log "Skipping $file (modified within last $MIN_AGE_MINUTES minutes)"
        continue
    fi

    # Skip open files
    if is_file_open "$file"; then
        log "Skipping $file (file is open)"
        continue
    fi

    # Get extension (lowercase)
    ext="${file##*.}"
    ext_lower=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
    filename=$(basename "$file")

    # Find category
    dest_folder="$DOWNLOAD_DIR/Others"
    for cat in "${!CATEGORIES[@]}"; do
        if [[ " ${CATEGORIES[$cat]} " =~ " $ext_lower " ]]; then
            dest_folder="$DOWNLOAD_DIR/$cat"
            break
        fi
    done

    # Skip if already in the correct folder
    if [[ "$(dirname "$file")" == "$dest_folder" ]]; then
        log "Skipping $file (already in correct folder)"
        continue
    fi

    # Handle duplicate filename
    dest_path="$dest_folder/$filename"
    if [ -e "$dest_path" ]; then
        base="${filename%.*}"
        new_filename="${base}_$(date +%Y%m%d_%H%M%S).$ext"
        dest_path="$dest_folder/$new_filename"
        log "Filename conflict, renaming to $new_filename"
    fi

    move_file "$file" "$dest_path"
done

log "=== Organization complete ==="

# If undo log is non-empty, suggest undo command
if [ -s "$UNDO_LOG" ] && [ "$DRY_RUN" = false ]; then
    echo "To undo this run, use: ~/.local/bin/undo-organizer.sh"
fi
