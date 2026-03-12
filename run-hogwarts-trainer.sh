#!/bin/bash
# Launch Hogwarts Legacy trainer with auto-detected Proton path

set -u
set -o pipefail

# Configuration
GAME_APPID="990080"  # Steam App ID for Hogwarts Legacy
GAME_NAME="Hogwarts Legacy"
TRAINER_EXE="Hogwarts Legacy v1.0-v1614419 Plus 33 Trainer.exe"
GAME_DIR=""          # Will be auto-detected if empty

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

# Check for --version flag
if [ "$1" = "--version" ]; then
    show_version
fi

# Function to find game directory
find_game_dir() {
    local common_paths=(
        "$HOME/.steam/steam/steamapps/common"
        "$HOME/.local/share/Steam/steamapps/common"
        "$HOME/Games/SteamLibrary/steamapps/common"
        "/media/SSD/SteamLibrary/steamapps/common"
        "/mnt/games/SteamLibrary/steamapps/common"
    )
    for base in "${common_paths[@]}"; do
        candidate="$base/$GAME_NAME"
        if [ -d "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

# Function to find Proton path for given appid
find_proton_path() {
    local appid="$1"
    local compatdata_paths=(
        "$HOME/.steam/steam/steamapps/compatdata/$appid"
        "$HOME/.local/share/Steam/steamapps/compatdata/$appid"
        "$HOME/Games/SteamLibrary/steamapps/compatdata/$appid"
        "/media/SSD/SteamLibrary/steamapps/compatdata/$appid"
        "/mnt/games/SteamLibrary/steamapps/compatdata/$appid"
    )
    local compat
    for compat in "${compatdata_paths[@]}"; do
        if [ -d "$compat/pfx" ]; then
            local library_root
            library_root=$(dirname "$(dirname "$compat")")
            local proton_found
            proton_found=$(find "$library_root/common" -maxdepth 2 -type f -path "*/files/bin/wine" 2>/dev/null | head -1)
            if [ -n "$proton_found" ]; then
                echo "$(dirname "$proton_found")/wine"
                return 0
            fi
        fi
    done
    if command -v wine &>/dev/null; then
        echo "wine"
        return 0
    fi
    return 1
}

# If game directory not set, try to auto-detect
if [ -z "$GAME_DIR" ]; then
    GAME_DIR=$(find_game_dir)
    if [ -z "$GAME_DIR" ]; then
        echo "ERROR: Could not find $GAME_NAME installation directory." >&2
        echo "Please set GAME_DIR manually in the script." >&2
        exit 1
    fi
    echo "Auto-detected game directory: $GAME_DIR"
fi

# Find Proton wine binary
PROTON_WINE=$(find_proton_path "$GAME_APPID")
if [ -z "$PROTON_WINE" ]; then
    echo "ERROR: Could not find Proton wine binary for app $GAME_APPID." >&2
    exit 1
fi
echo "Using Proton wine: $PROTON_WINE"

# Set Wine prefix path (the compatdata pfx directory)
WINEPREFIX=""
for compat in "$HOME/.steam/steam/steamapps/compatdata/$GAME_APPID" \
              "$HOME/.local/share/Steam/steamapps/compatdata/$GAME_APPID" \
              "$HOME/Games/SteamLibrary/steamapps/compatdata/$GAME_APPID" \
              "/media/SSD/SteamLibrary/steamapps/compatdata/$GAME_APPID" \
              "/mnt/games/SteamLibrary/steamapps/compatdata/$GAME_APPID"; do
    if [ -d "$compat/pfx" ]; then
        WINEPREFIX="$compat/pfx"
        break
    fi
done

if [ -z "$WINEPREFIX" ]; then
    echo "ERROR: Could not find Wine prefix for app $GAME_APPID." >&2
    exit 1
fi
export WINEPREFIX
export WINEARCH=win64

# Change to game directory
cd "$GAME_DIR" || { echo "ERROR: Could not cd to $GAME_DIR" >&2; exit 1; }

# Check if trainer exists
if [ ! -f "$TRAINER_EXE" ]; then
    echo "ERROR: Trainer executable '$TRAINER_EXE' not found in $GAME_DIR." >&2
    exit 1
fi

# Launch trainer
echo "Launching trainer with Proton wine..."
"$PROTON_WINE" "$TRAINER_EXE"
