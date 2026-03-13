#!/bin/bash
# images-to-pdf.sh – Convert images to PDF (CLI and GUI modes)
# Version: 2.2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
DEFAULT_PAPER_SIZE="A4"
DEFAULT_ORIENTATION="portrait"
DEFAULT_QUALITY=92

OUTPUT_FILE=""
PAPER_SIZE="$DEFAULT_PAPER_SIZE"
ORIENTATION="$DEFAULT_ORIENTATION"
QUALITY="$DEFAULT_QUALITY"
METADATA=""
PROGRESS=false
VERBOSE=false
USE_GUI=false
GUI_TOOL=""

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    PAPER_SIZE="$(get_config ".images2pdf.default_paper_size" "$PAPER_SIZE")"
    ORIENTATION="$(get_config ".images2pdf.default_orientation" "$ORIENTATION")"
    QUALITY="$(get_config ".images2pdf.default_quality" "$QUALITY")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "images-to-pdf.sh version 2.2.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [options] image1 [image2 ...]

Convert one or more images to a single PDF.

Options:
  -o, --output FILE    Output PDF filename (required in CLI mode if more than one image)
  -s, --paper-size SZ  Paper size: A4, Letter, Legal, etc. (default: $DEFAULT_PAPER_SIZE)
  -r, --orientation    Orientation: portrait or landscape (default: $DEFAULT_ORIENTATION)
  -q, --quality PCT    JPEG compression quality (1-100, default: $DEFAULT_QUALITY)
  -m, --metadata STR   Add PDF metadata (e.g., "title=My PDF,author=Me")
  -p, --progress       Show progress for many images (requires ImageMagick 7)
  -v, --verbose        Enable verbose output
  --help               Show this help message
  --version            Show version information

If no arguments are given, launches a GUI file picker (requires kdialog or zenity).
EOF
    exit 0
}

detect_convert() {
    if command -v magick &>/dev/null; then
        echo "magick"
    elif command -v convert &>/dev/null; then
        echo "convert"
    else
        die "ImageMagick (convert/magick) not found. Please install it."
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if [ $# -eq 0 ]; then
    if command -v kdialog &>/dev/null; then
        USE_GUI=true
        GUI_TOOL="kdialog"
    elif command -v zenity &>/dev/null; then
        USE_GUI=true
        GUI_TOOL="zenity"
    else
        die "No input files provided, and no GUI tool (kdialog/zenity) available."
    fi
else
    if ! PARSED_ARGS=$(getopt -o o:s:r:q:m:pv -l output:,paper-size:,orientation:,quality:,metadata:,progress,verbose,help,version -- "$@"); then
        show_help
    fi
    eval set -- "$PARSED_ARGS"

    while true; do
        case "$1" in
            -o|--output)         OUTPUT_FILE="$2"; shift 2 ;;
            -s|--paper-size)     PAPER_SIZE="$2"; shift 2 ;;
            -r|--orientation)    ORIENTATION="$2"; shift 2 ;;
            -q|--quality)        QUALITY="$2"; shift 2 ;;
            -m|--metadata)       METADATA="$2"; shift 2 ;;
            -p|--progress)       PROGRESS=true; shift ;;
            -v|--verbose)        VERBOSE=true; shift ;;
            --help)              show_help ;;
            --version)           show_version ;;
            --)                  shift; break ;;
            *)                   break ;;
        esac
    done

    # Remaining arguments are image files
    IMAGES=("$@")
    if [ ${#IMAGES[@]} -eq 0 ]; then
        log_error "No image files specified."
        show_help
    fi

    # Set default output if not given
    if [ -z "$OUTPUT_FILE" ]; then
        if [ ${#IMAGES[@]} -eq 1 ]; then
            OUTPUT_FILE="${IMAGES[0]%.*}.pdf"
        else
            OUTPUT_FILE="combined.pdf"
        fi
        log_info "No output specified, using: $OUTPUT_FILE"
    fi
fi

# -------------------------------------------------------------------
# GUI mode (kdialog or zenity)
# -------------------------------------------------------------------
if [ "$USE_GUI" = true ]; then
    if [ "$GUI_TOOL" = "kdialog" ]; then
        IFS=$'\n' read -r -d '' -a IMAGES < <(kdialog --multiple --getopenfilename "$HOME" "Image Files (*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp)" 2>/dev/null || true)
        [ ${#IMAGES[@]} -eq 0 ] && exit 0

        OUTPUT_FILE=$(kdialog --getsavefilename "$HOME/images.pdf" "*.pdf" 2>/dev/null || true)
        [ -z "$OUTPUT_FILE" ] && exit 0
        [[ "$OUTPUT_FILE" != *.pdf ]] && OUTPUT_FILE="${OUTPUT_FILE}.pdf"

        PAPER_SIZE=$(kdialog --combobox "Select paper size:" "A4" "Letter" "Legal" --default "$DEFAULT_PAPER_SIZE" 2>/dev/null || true)
        [ -z "$PAPER_SIZE" ] && exit 0

        ORIENTATION=$(kdialog --combobox "Select orientation:" "portrait" "landscape" --default "$DEFAULT_ORIENTATION" 2>/dev/null || true)
        [ -z "$ORIENTATION" ] && exit 0

        QUALITY=$(kdialog --inputbox "JPEG quality (1-100):" "$DEFAULT_QUALITY" 2>/dev/null || true)

    elif [ "$GUI_TOOL" = "zenity" ]; then
        IFS='|' read -r -a IMAGES < <(zenity --file-selection --multiple --separator="|" --file-filter="Image Files | *.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp" 2>/dev/null || true)
        [ ${#IMAGES[@]} -eq 0 ] && exit 0

        OUTPUT_FILE=$(zenity --file-selection --save --confirm-overwrite --filename="$HOME/images.pdf" 2>/dev/null || true)
        [ -z "$OUTPUT_FILE" ] && exit 0
        [[ "$OUTPUT_FILE" != *.pdf ]] && OUTPUT_FILE="${OUTPUT_FILE}.pdf"

        PAPER_SIZE=$(zenity --list --radiolist --title="Paper Size" --column="Select" --column="Size" TRUE "A4" FALSE "Letter" FALSE "Legal" 2>/dev/null || true)
        [ -z "$PAPER_SIZE" ] && exit 0

        ORIENTATION=$(zenity --list --radiolist --title="Orientation" --column="Select" --column="Orientation" TRUE "portrait" FALSE "landscape" 2>/dev/null || true)
        [ -z "$ORIENTATION" ] && exit 0

        QUALITY=$(zenity --entry --title="Quality" --text="JPEG quality (1-100):" --entry-text="$DEFAULT_QUALITY" 2>/dev/null || true)
    fi
fi

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
CONVERT_CMD=$(detect_convert)

# Validate quality
if [ -n "$QUALITY" ] && { [ "$QUALITY" -lt 1 ] || [ "$QUALITY" -gt 100 ]; } 2>/dev/null; then
    die "Quality must be an integer between 1 and 100."
fi

output_dir=$(dirname "$OUTPUT_FILE")
if [ ! -d "$output_dir" ]; then
    die "Output directory '$output_dir' does not exist."
fi
if [ ! -w "$output_dir" ]; then
    die "Output directory '$output_dir' is not writable."
fi

if [ -e "$OUTPUT_FILE" ]; then
    if [ "$USE_GUI" = true ] && [ "$GUI_TOOL" = "kdialog" ]; then
        if ! kdialog --warningyesno "File '$OUTPUT_FILE' exists. Overwrite?"; then
            exit 0
        fi
    else
        log_warn "Output file '$OUTPUT_FILE' already exists. Will overwrite."
    fi
fi

# Check for PDF write support in ImageMagick (Policy Fixer)
if ! $CONVERT_CMD -list format 2>/dev/null | grep -i "PDF" | grep -q "rw"; then
    log_error "ImageMagick is blocking PDF creation due to security policies."
    echo -e "${YELLOW}To fix this, you must edit your ImageMagick policy.xml file to allow PDF read/write.${NC}"
    echo -e "You can usually do this by running:\n"
    echo -e "  sudo sed -i 's/rights=\"none\" pattern=\"PDF\"/rights=\"read|write\" pattern=\"PDF\"/' /etc/ImageMagick-6/policy.xml\n"
    echo -e "(Replace ImageMagick-6 with your actual version directory).\n"

    if [ "$USE_GUI" = true ]; then
        if [ "$GUI_TOOL" = "kdialog" ]; then
            kdialog --error "ImageMagick PDF creation blocked by policy.xml.\nPlease run the script in a terminal to see the fix."
        else
            zenity --error --text="ImageMagick PDF creation blocked by policy.xml.\nPlease run the script in a terminal to see the fix."
        fi
    fi
    exit 1
fi

# -------------------------------------------------------------------
# Build convert options
# -------------------------------------------------------------------
CONVERT_OPTS=()

# Page size and orientation
if [ "$ORIENTATION" = "landscape" ]; then
    case "$PAPER_SIZE" in
        A4|Letter|Legal) PAGE="${PAPER_SIZE}Landscape" ;;
        *) PAGE="$PAPER_SIZE" ;;
    esac
else
    PAGE="$PAPER_SIZE"
fi
CONVERT_OPTS+=("-page" "$PAGE")

# Quality
if [ -n "$QUALITY" ]; then
    CONVERT_OPTS+=("-quality" "$QUALITY")
fi

# Metadata
if [ -n "$METADATA" ]; then
    IFS=',' read -ra KV <<< "$METADATA"
    for pair in "${KV[@]}"; do
        key="${pair%%=*}"
        value="${pair#*=}"
        CONVERT_OPTS+=("-define" "pdf:${key}=${value}")
    done
fi

# Progress (ImageMagick 7+)
if [ "$PROGRESS" = true ]; then
    if $CONVERT_CMD -version | grep -q "Version: ImageMagick 7"; then
        CONVERT_OPTS+=("-progress")
    else
        log_warn "Progress option requires ImageMagick 7. Ignored."
    fi
fi

# Verbose
if [ "$VERBOSE" = true ]; then
    CONVERT_OPTS+=("-verbose")
    log_debug "$CONVERT_CMD ${IMAGES[*]} ${CONVERT_OPTS[*]} $OUTPUT_FILE"
fi

# -------------------------------------------------------------------
# Run conversion
# -------------------------------------------------------------------
log_info "Converting ${#IMAGES[@]} images to PDF: $OUTPUT_FILE"

if ! $CONVERT_CMD "${IMAGES[@]}" "${CONVERT_OPTS[@]}" "$OUTPUT_FILE"; then
    exit_code=$?
    if [ "$USE_GUI" = true ]; then
        if [ "$GUI_TOOL" = "kdialog" ]; then
            kdialog --error "❌ Conversion failed (exit code $exit_code). Check the files and try again."
        else
            zenity --error --text="❌ Conversion failed (exit code $exit_code). Check the files and try again."
        fi
    else
        log_error "Conversion failed (exit code $exit_code)."
    fi
    exit $exit_code
fi

if [ "$USE_GUI" = true ]; then
    if [ "$GUI_TOOL" = "kdialog" ]; then
        kdialog --msgbox "✅ PDF saved to:\n$OUTPUT_FILE"
    else
        zenity --info --text="✅ PDF saved to:\n$OUTPUT_FILE"
    fi
else
    log_success "PDF saved to: $OUTPUT_FILE"
fi
