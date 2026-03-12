#!/bin/bash
# Helper script for KDE service menu: Generate Checksum

# Ask user for checksum type using KDE dialog
type=$(kdialog --combobox "Select checksum type:" "MD5" "SHA1" "SHA256" --default "SHA256")

# If user cancelled, exit
if [ -z "$type" ]; then
    exit 1
fi

# Map choice to command
case $type in
    MD5)    cmd="md5sum" ;;
    SHA1)   cmd="sha1sum" ;;
    SHA256) cmd="sha256sum" ;;
esac

# Process each selected file
for file in "$@"; do
    if [ -f "$file" ]; then
        $cmd "$file" >> "${file}.${type}.txt"
    fi
done

# Notify completion
kdialog --msgbox "✅ ${type} checksums saved to .txt files"
