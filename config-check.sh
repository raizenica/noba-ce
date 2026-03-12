#!/bin/bash
# config-check.sh – Validate ~/.config/automation.conf and check dependencies

set -u
set -o pipefail

CONFIG_FILE="${CONFIG_FILE:-$HOME/.config/automation.conf}"
VERBOSE=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $0 [options]

Check configuration and dependencies for Nobara automation scripts.

Options:
  -v, --verbose   Show detailed information
  --help          Show this help
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Function to check command availability
check_cmd() {
    if command -v "$1" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $1"
        return 0
    else
        echo -e "  ${RED}✗${NC} $1 (not found)"
        return 1
    fi
}

# Start
echo -e "${GREEN}=== Configuration & Dependency Check ===${NC}"

# 1. Check config file
echo -e "\n${YELLOW}Config file:${NC} $CONFIG_FILE"
if [ -f "$CONFIG_FILE" ]; then
    echo -e "  ${GREEN}✓ File exists${NC}"
    if [ -r "$CONFIG_FILE" ]; then
        echo -e "  ${GREEN}✓ File is readable${NC}"
        # Source it safely to check variables
        # We'll just grep for common variables
        echo "  Variables defined:"
        grep -E '^[A-Za-z_]+=' "$CONFIG_FILE" | sed 's/^/    /' || echo "    (none)"
    else
        echo -e "  ${RED}✗ File not readable${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠ File not found (using defaults)${NC}"
fi

# 2. Check dependencies for each script
echo -e "\n${YELLOW}Dependency checks:${NC}"

# Common dependencies
echo "  Common tools:"
check_cmd rsync
check_cmd msmtp
check_cmd findmnt
check_cmd flock
check_cmd jq
check_cmd yq
check_cmd convert   # ImageMagick
check_cmd md5sum
check_cmd sha256sum
check_cmd kdialog   # optional
check_cmd notify-send

# Script-specific checks
echo -e "\n  Script-specific:"
# backup-to-nas.sh
echo "    backup-to-nas.sh:"
check_cmd rsync
check_cmd msmtp
check_cmd findmnt
check_cmd flock

# backup-verifier.sh
echo "    backup-verifier.sh:"
check_cmd find
check_cmd shuf
check_cmd md5sum

# checksum.sh
echo "    checksum.sh:"
check_cmd find
check_cmd jq
check_cmd yq
check_cmd wl-copy || check_cmd xclip

# disk-sentinel.sh
echo "    disk-sentinel.sh:"
check_cmd df
check_cmd du
check_cmd msmtp
if ! sudo -n true 2>/dev/null; then
    echo -e "  ${YELLOW}⚠ sudo may require password (cleanup might fail)${NC}"
fi

# images-to-pdf.sh
echo "    images-to-pdf.sh:"
check_cmd convert

# organize-downloads.sh
echo "    organize-downloads.sh:"
check_cmd find
check_cmd mv

# run-hogwarts-trainer.sh
echo "    run-hogwarts-trainer.sh:"
check_cmd find

# motd-generator.sh
echo "    motd-generator.sh:"
check_cmd curl
check_cmd jq

# noba-dashboard.sh
echo "    noba-dashboard.sh:"
check_cmd find

# backup-notify.sh
echo "    backup-notify.sh:"
check_cmd notify-send

# 3. Check log directories
echo -e "\n${YELLOW}Log directories:${NC}"
for log in "$HOME/.local/share/backup-to-nas.log" \
           "$HOME/.local/share/backup-verifier.log" \
           "$HOME/.local/share/disk-sentinel.log" \
           "$HOME/.local/share/download-organizer.log" \
           "$HOME/.local/share/download-organizer-undo.log"; do
    dir=$(dirname "$log")
    if [ -d "$dir" ]; then
        echo -e "  ${GREEN}✓${NC} $dir exists"
    else
        echo -e "  ${YELLOW}⚠ $dir does not exist (will be created by scripts)${NC}"
    fi
done

# 4. Check for common configuration issues
echo -e "\n${YELLOW}Configuration suggestions:${NC}"
if [ -f "$CONFIG_FILE" ]; then
    if grep -q "EMAIL=" "$CONFIG_FILE" && ! grep -q "EMAIL=.*@" "$CONFIG_FILE"; then
        echo -e "  ${YELLOW}⚠ EMAIL may not be a valid address${NC}"
    fi
    if grep -q "BACKUP_DEST=" "$CONFIG_FILE" && ! grep -q "BACKUP_DEST=.*/" "$CONFIG_FILE"; then
        echo -e "  ${YELLOW}⚠ BACKUP_DEST may not be a valid path${NC}"
    fi
else
    echo -e "  ${YELLOW}ℹ Using default settings${NC}"
fi

echo -e "\n${GREEN}Check complete.${NC}"
