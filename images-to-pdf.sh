#!/bin/bash
# Helper script for KDE service menu: Convert Images to PDF

# Ask where to save the PDF
output=$(kdialog --getsavefilename ~/ "Save PDF as" "images.pdf")

if [ -z "$output" ]; then
    exit 1  # User cancelled
fi

# Ensure .pdf extension
if [[ "$output" != *.pdf ]]; then
    output="${output}.pdf"
fi

# Use ImageMagick to combine images into PDF
convert "$@" "$output"

# Check success
if [ $? -eq 0 ]; then
    kdialog --msgbox "✅ PDF saved to:\n$output"
else
    kdialog --error "❌ Conversion failed. Check the files and try again."
fi
