#!/bin/bash
# Undo last download organizer run

UNDO_LOG="$HOME/.local/share/download-organizer-undo.log"

if [ ! -f "$UNDO_LOG" ] || [ ! -s "$UNDO_LOG" ]; then
    echo "No undo log found."
    exit 1
fi

echo "This will undo the last organize-downloads run. Files will be moved back to their original locations."
read -p "Are you sure? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 0
fi

# Process undo log in reverse order
tac "$UNDO_LOG" | while IFS='|' read -r src dest; do
    if [ -f "$dest" ]; then
        mkdir -p "$(dirname "$src")"
        mv "$dest" "$src"
        echo "Restored: $dest → $src"
    else
        echo "Warning: $dest not found, skipping"
    fi
done

# Clear undo log
: > "$UNDO_LOG"
echo "Undo complete."
