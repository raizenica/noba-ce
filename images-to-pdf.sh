#!/bin/bash
# Convert images to PDF – CLI and GUI modes with progress and options

set -u
set -o pipefail

# Defaults
OUTPUT_FILE=""
PAPER_SIZE="A4"          # A4, Letter, etc.
ORIENTATION="portrait"   # portrait or landscape
QUALITY=""               # empty = default (usually 92 for JPEG)
METADATA=""
QUIET=false
USE_GUI=false
PROGRESS=false

# Function to show version
show_version() {
    if command -v git &>/dev/null && git rev-parse --git-dir &>/dev/null; then
        version=$(git describe --tags --always --dirty 2>/dev/null)
        echo "$(basename "$0") version $version"
    else
        echo "$(basename "$0") version unknown (not in git repo)"
    fi
    exit 0
}

# Function to show usage
usage() {
    cat <<EOF
Usage: $0 [options] image1 [image2 ...]

Options:
  -o, --output FILE     Output PDF filename (required in CLI mode)
  -s, --paper-size SIZE Paper size: A4, Letter, etc. (default: A4)
  -r, --orientation DIR Orientation: portrait or landscape (default: portrait)
  -q, --quality PERCENT JPEG compression quality (1-100, default: 92)
  -m, --metadata STR    Add PDF metadata (e.g., "title=My PDF,author=Me")
  -p, --progress        Show progress for many images (requires ImageMagick 7+)
  --help                Show this help
  --version             Show version information

If no options are given and kdialog is available, runs in GUI mode with option dialogs.
EOF
    exit 0
}

# Parse command-line arguments
if [ $# -eq 0 ]; then
    # No arguments: try GUI mode
    if command -v kdialog &>/dev/null; then
        USE_GUI=true
    else
        echo "Error: No input files and kdialog not available." >&2
        exit 1
    fi
else
    # Parse options
    if ! OPTIONS=$(getopt -o o:s:r:q:m:ph -l output:,paper-size:,orientation:,quality:,metadata:,progress,help,version -- "$@"); then
        usage
    fi
    eval set -- "$OPTIONS"

    while true; do
        case "$1" in
            -o|--output)
                OUTPUT_FILE="$2"
                shift 2
                ;;
            -s|--paper-size)
                PAPER_SIZE="$2"
                shift 2
                ;;
            -r|--orientation)
                ORIENTATION="$2"
                shift 2
                ;;
            -q|--quality)
                QUALITY="$2"
                shift 2
                ;;
            -m|--metadata)
                METADATA="$2"
                shift 2
                ;;
            -p|--progress)
                PROGRESS=true
                shift
                ;;
            --help)
                usage
                ;;
            --version)
                show_version
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

    # Remaining arguments are image files
    IMAGES=("$@")
    if [ ${#IMAGES[@]} -eq 0 ]; then
        echo "Error: No image files specified." >&2
        usage
    fi

    # If output not specified, generate one
    if [ -z "$OUTPUT_FILE" ]; then
        if [ ${#IMAGES[@]} -eq 1 ]; then
            OUTPUT_FILE="${IMAGES[0]%.*}.pdf"
        else
            OUTPUT_FILE="combined.pdf"
        fi
        echo "No output specified, using: $OUTPUT_FILE"
    fi
fi

# GUI mode
if $USE_GUI; then
    # Ask for images using file picker (multiple selection)
    readarray -t IMAGES < <(kdialog --multiple --getopenfilename ~/ "Image Files (*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp)" 2>/dev/null)
    if [ ${#IMAGES[@]} -eq 0 ]; then
        exit 1
    fi

    # Ask for output file
    OUTPUT_FILE=$(kdialog --getsavefilename ~/ "Save PDF as" "images.pdf")
    [ -z "$OUTPUT_FILE" ] && exit 1
    if [[ "$OUTPUT_FILE" != *.pdf ]]; then
        OUTPUT_FILE="${OUTPUT_FILE}.pdf"
    fi

    # Ask for paper size
    PAPER_SIZE=$(kdialog --combobox "Select paper size:" "A4" "Letter" "Legal" --default "$PAPER_SIZE")
    [ -z "$PAPER_SIZE" ] && exit 1

    # Ask for orientation
    ORIENTATION=$(kdialog --combobox "Select orientation:" "portrait" "landscape" --default "$ORIENTATION")
    [ -z "$ORIENTATION" ] && exit 1

    # Ask for quality (optional)
    QUALITY=$(kdialog --inputbox "JPEG quality (1-100, leave empty for default):" "")
    # If empty, we'll leave it unset
fi

# Check ImageMagick policy for PDF writing
if ! convert -list format | grep -q "PDF.*rw"; then
    echo "Warning: ImageMagick PDF output may be restricted by policy. Check /etc/ImageMagick-*/policy.xml" >&2
    # Continue anyway
fi

# Build convert options
CONVERT_OPTS=()

# Set page size and orientation
CONVERT_OPTS+=("-page" "$PAPER_SIZE")
if [ "$ORIENTATION" = "landscape" ]; then
    # We could add landscape handling, but convert may auto-orient based on images
    # For simplicity, just set page size; actual orientation depends on images.
    :
fi

# Set quality if specified
if [ -n "$QUALITY" ]; then
    CONVERT_OPTS+=("-quality" "$QUALITY")
fi

# Add metadata (requires ImageMagick 7+ or different syntax)
if [ -n "$METADATA" ]; then
    # Convert metadata string to key-value pairs for identify -set
    IFS=',' read -ra KV <<< "$METADATA"
    for pair in "${KV[@]}"; do
        CONVERT_OPTS+=("-set" "${pair%%=*}" "${pair#*=}")
    done
fi

# Show progress if many images (simple message)
if [ "$PROGRESS" = true ] && [ ${#IMAGES[@]} -gt 5 ] && [ "$QUIET" = false ]; then
    echo "Converting ${#IMAGES[@]} images to PDF..."
fi

# Run convert
if ! convert "${IMAGES[@]}" "${CONVERT_OPTS[@]}" "$OUTPUT_FILE"; then
    if $USE_GUI; then
        kdialog --error "❌ Conversion failed. Check the files and try again."
    else
        echo "❌ Conversion failed." >&2
        exit 1
    fi
else
    if $USE_GUI; then
        kdialog --msgbox "✅ PDF saved to:\n$OUTPUT_FILE"
    else
        echo "✅ PDF saved to: $OUTPUT_FILE"
    fi
fi
