#!/bin/bash
# Convert images to PDF – CLI and GUI modes

set -u
set -o pipefail

# Defaults
OUTPUT_FILE=""
PAPER_SIZE="A4"
ORIENTATION="portrait"
QUALITY=""
METADATA=""
QUIET=false

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
  -h, --help            Show this help

If no options are given and kdialog is available, runs in GUI mode.
EOF
    exit 0
}

# Determine mode: GUI if no arguments start with '-'
if [ $# -eq 0 ]; then
    # No arguments at all – GUI mode (but no files? maybe error)
    GUI_MODE=true
    CLI_MODE=false
    IMAGES=()
elif [[ "$1" != -* ]]; then
    # First argument is not an option – assume GUI mode with files
    GUI_MODE=true
    CLI_MODE=false
    IMAGES=("$@")
else
    # Options present – CLI mode
    GUI_MODE=false
    CLI_MODE=true

    # Parse options with getopt
    OPTIONS=$(getopt -o o:s:r:q:m:h -l output:,paper-size:,orientation:,quality:,metadata:,help -- "$@")
    if [ $? -ne 0 ]; then
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
            -h|--help)
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

    # Remaining arguments are image files
    IMAGES=("$@")
fi

# GUI mode handling
if $GUI_MODE; then
    if ! command -v kdialog &>/dev/null; then
        echo "Error: kdialog not available for GUI mode." >&2
        exit 1
    fi
    if [ ${#IMAGES[@]} -eq 0 ]; then
        kdialog --error "No image files selected."
        exit 1
    fi

    # Ask for output file
    OUTPUT_FILE=$(kdialog --getsavefilename ~/ "Save PDF as" "images.pdf")
    [ -z "$OUTPUT_FILE" ] && exit 1

    # Ensure .pdf extension
    if [[ "$OUTPUT_FILE" != *.pdf ]]; then
        OUTPUT_FILE="${OUTPUT_FILE}.pdf"
    fi

    # Optionally ask for paper size, orientation, quality (could add)
    # For simplicity, we keep defaults
fi

# CLI mode: check if output is provided
if $CLI_MODE && [ -z "$OUTPUT_FILE" ]; then
    echo "Error: --output is required in CLI mode." >&2
    usage
fi

# Check if we have images
if [ ${#IMAGES[@]} -eq 0 ]; then
    echo "Error: No image files specified." >&2
    exit 1
fi

# Check ImageMagick policy for PDF writing
if ! convert -list format | grep -q "PDF.*rw"; then
    echo "Warning: ImageMagick PDF output may be restricted by policy. Check /etc/ImageMagick-*/policy.xml" >&2
    # Continue anyway
fi

# Build convert options
CONVERT_OPTS=()

# Set orientation
if [ "$ORIENTATION" = "landscape" ]; then
    # For landscape, we might want to set page size to landscape variant? 
    # But -rotate can be used. For simplicity, we'll add -rotate if needed.
    CONVERT_OPTS+=("-rotate" "90")
fi

# Set page size
CONVERT_OPTS+=("-page" "$PAPER_SIZE")

# Set quality if specified
if [ -n "$QUALITY" ]; then
    CONVERT_OPTS+=("-quality" "$QUALITY")
fi

# Add metadata (ImageMagick 7+ syntax; for older, may need -set option)
if [ -n "$METADATA" ]; then
    # Example: "title=My PDF,author=Me"
    IFS=',' read -ra KV <<< "$METADATA"
    for pair in "${KV[@]}"; do
        key="${pair%%=*}"
        value="${pair#*=}"
        CONVERT_OPTS+=("-set" "$key" "$value")
    done
fi

# Show progress if more than 5 images
if [ ${#IMAGES[@]} -gt 5 ] && [ "$QUIET" = false ]; then
    echo "Converting ${#IMAGES[@]} images to PDF..."
fi

# Run convert
convert "${IMAGES[@]}" "${CONVERT_OPTS[@]}" "$OUTPUT_FILE"

# Check success
if [ $? -eq 0 ]; then
    if $GUI_MODE; then
        kdialog --msgbox "✅ PDF saved to:\n$OUTPUT_FILE"
    else
        echo "✅ PDF saved to: $OUTPUT_FILE"
    fi
else
    if $GUI_MODE; then
        kdialog --error "❌ Conversion failed. Check the files and try again."
    else
        echo "❌ Conversion failed." >&2
        exit 1
    fi
fi
