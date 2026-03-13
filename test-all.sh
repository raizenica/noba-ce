#!/bin/bash
# test-all.sh – Comprehensive functionality test for all scripts

set -u
set -o pipefail

cd "$(dirname "$0")" || exit 1

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0

# Create a dummy backup for backup-verifier.sh
DUMMY_BACKUP="/tmp/test-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DUMMY_BACKUP/Documents"
echo "dummy content" > "$DUMMY_BACKUP/Documents/test.txt"

# Create a test image for images-to-pdf.sh if not present
if [ ! -f "/tmp/test.png" ] && command -v convert &>/dev/null; then
    convert -size 100x100 xc:red /tmp/test.png
fi

for script in *.sh; do
    # Skip library and test scripts
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" ]] && continue

    echo -n "Testing $script ... "

    # Special handling for backup-verifier.sh
    if [[ "$script" == "backup-verifier.sh" ]]; then
        if ./"$script" --backup-dir "/tmp/test-backups" --num-files 1 --dry-run >/dev/null 2>&1; then
            echo -e "${GREEN}PASS${NC}"
            ((PASS++))
        else
            echo -e "${RED}FAIL (dry-run on dummy backup)${NC}"
            ((FAIL++))
        fi
        continue
    fi

    # Special handling for images-to-pdf.sh
    if [[ "$script" == "images-to-pdf.sh" ]]; then
        if [ ! -f "/tmp/test.png" ]; then
            echo -e "${YELLOW}SKIP (no test image)${NC}"
            ((SKIP++))
            continue
        fi
        if ./images-to-pdf.sh -o /tmp/test.pdf /tmp/test.png >/dev/null 2>&1; then
            echo -e "${GREEN}PASS${NC}"
            ((PASS++))
        else
            echo -e "${RED}FAIL (conversion)${NC}"
            ((FAIL++))
        fi
        continue
    fi

    # For other scripts, check --help
    if ! ./"$script" --help >/dev/null 2>&1; then
        echo -e "${RED}FAIL (--help)${NC}"
        ((FAIL++))
        continue
    fi

    # Check --version if present
    if grep -q "show_version" "$script"; then
        if ! ./"$script" --version >/dev/null 2>&1; then
            echo -e "${RED}FAIL (--version)${NC}"
            ((FAIL++))
            continue
        fi
    fi

    # Dry-run for scripts that support it (excluding those already handled)
    case "$script" in
        backup-to-nas.sh|disk-sentinel.sh|organize-downloads.sh|undo-organizer.sh)
            if ! ./"$script" --dry-run >/dev/null 2>&1; then
                echo -e "${RED}FAIL (--dry-run)${NC}"
                ((FAIL++))
                continue
            fi
            ;;
        checksum.sh)
            tmp=$(mktemp)
            echo "test" > "$tmp"
            if ! ./checksum.sh "$tmp" >/dev/null 2>&1; then
                echo -e "${RED}FAIL (checksum generation)${NC}"
                ((FAIL++))
                rm -f "$tmp"
                continue
            fi
            rm -f "$tmp"
            ;;
        noba-web.sh)
            # Just check help (already done)
            ;;
        *)
            # Already passed help
            ;;
    esac

    echo -e "${GREEN}PASS${NC}"
    ((PASS++))
done

# Cleanup
rm -rf "/tmp/test-backups"
rm -f "/tmp/test.png" "/tmp/test.pdf"

echo ""
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
exit $FAIL
