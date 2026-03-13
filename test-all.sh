#!/bin/bash
# test-all.sh – Comprehensive functionality test for all scripts

set -euo pipefail
trap 'echo "Error at line $LINENO (last command: $BASH_COMMAND)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
TIMEOUT_SECONDS=5
SKIP_SLOW=false
DRY_RUN=false
VERBOSE=false

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "test-all.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Run functional tests on all noba scripts.

Options:
  -t, --timeout SECS   Set timeout per test (default: $TIMEOUT_SECONDS)
  -s, --skip-slow      Skip long-running or interactive scripts
  -n, --dry-run        Only list scripts to be tested
  -v, --verbose        Show more output (test commands)
  --help               Show this help message
  --version            Show version information
EOF
    exit 0
}

# Run a command with timeout, capturing output if verbose
run_test() {
    local script="$1"
    shift
    local cmd=("$@")
    local output_file
    output_file=$(mktemp)

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would test: $script ${cmd[*]}"
        rm -f "$output_file"
        return 0
    fi

    if command -v timeout &>/dev/null; then
        if timeout "$TIMEOUT_SECONDS" "${cmd[@]}" > "$output_file" 2>&1; then
            rm -f "$output_file"
            return 0
        else
            local exit_code=$?
            if [ "$VERBOSE" = true ]; then
                cat "$output_file"
            fi
            rm -f "$output_file"
            return $exit_code
        fi
    else
        # Fallback if timeout not available
        if "${cmd[@]}" > "$output_file" 2>&1; then
            rm -f "$output_file"
            return 0
        else
            local exit_code=$?
            if [ "$VERBOSE" = true ]; then
                cat "$output_file"
            fi
            rm -f "$output_file"
            return $exit_code
        fi
    fi
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o t:snv -l timeout:,skip-slow,dry-run,verbose,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -t|--timeout)    TIMEOUT_SECONDS="$2"; shift 2 ;;
        -s|--skip-slow)  SKIP_SLOW=true; shift ;;
        -n|--dry-run)    DRY_RUN=true; shift ;;
        -v|--verbose)    VERBOSE=true; shift ;;
        --help)          show_help ;;
        --version)       show_version ;;
        --)              shift; break ;;
        *)               break ;;
    esac
done

# -------------------------------------------------------------------
# Prepare test environment
# -------------------------------------------------------------------
cd "$SCRIPT_DIR" || { log_error "Cannot cd to $SCRIPT_DIR"; exit 1; }

echo "DEBUG: Files found: " *.sh >&2

# Create dummy backup for backup-verifier.sh
DUMMY_BACKUP="/tmp/test-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DUMMY_BACKUP/Documents"
echo "dummy content" > "$DUMMY_BACKUP/Documents/test.txt"

# Create test image for images-to-pdf.sh
TEST_IMAGE="/tmp/test.png"
if [ ! -f "$TEST_IMAGE" ]; then
    if command -v magick &>/dev/null; then
        magick -size 100x100 xc:red "$TEST_IMAGE" 2>/dev/null || true
    elif command -v convert &>/dev/null; then
        convert -size 100x100 xc:red "$TEST_IMAGE" 2>/dev/null || true
    fi
fi

# Create a file with spaces and special characters for organizer tests
TEST_SPECIAL="/tmp/Download/test file with spaces and !@#$.txt"
mkdir -p /tmp/Download
echo "content" > "$TEST_SPECIAL"

# Create a large number of small files for checksum test
LARGE_DIR="/tmp/checksum-large"
mkdir -p "$LARGE_DIR"
for i in {1..100}; do
    echo "test$i" > "$LARGE_DIR/file$i.txt"
done

# Create an invalid YAML config for testing
INVALID_YAML="/tmp/invalid_config.yaml"
cat > "$INVALID_YAML" <<EOF
backup:
  dest: "/mnt/nas"
  sources: [ "bad indentation"
    - missing dash
disk: [unclosed
EOF

# -------------------------------------------------------------------
# Test counters
# -------------------------------------------------------------------
PASS=0
FAIL=0
SKIP=0

# -------------------------------------------------------------------
# Test each script (existing loop)
# -------------------------------------------------------------------
log_info "Starting tests (timeout: ${TIMEOUT_SECONDS}s, skip slow: $SKIP_SLOW)"

for script in *.sh; do
    echo "DEBUG: Now processing: $script" >&2
    # Skip library and self
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" ]] && continue

    # Optionally skip slow scripts
    if [ "$SKIP_SLOW" = true ]; then
        case "$script" in
            temperature-alert.sh|service-watch.sh|noba-web.sh)
                log_debug "Skipping slow script: $script"
                SKIP=$((SKIP+1))
                continue
                ;;
        esac
    fi

    echo -n "Testing $script ... "

    # -------------------------------------------------------------------
    # Special case: long-running daemon-like scripts – only test --help and --version
    # -------------------------------------------------------------------
    case "$script" in
        temperature-alert.sh|service-watch.sh|battery-watch.sh|noba-web.sh)
            if run_test "$script" "$script" --help; then
                if grep -q "show_version" "$script" && ! run_test "$script" "$script" --version; then
                    echo -e "${RED}FAIL (--version)${NC}"
                    FAIL=$((FAIL+1))
                else
                    echo -e "${GREEN}PASS${NC}"
                    PASS=$((PASS+1))
                fi
            else
                echo -e "${RED}FAIL (--help)${NC}"
                FAIL=$((FAIL+1))
            fi
            continue
            ;;
    esac
    # Special case: noba-dashboard.sh – just run it (no arguments needed)
    if [[ "$script" == "noba-dashboard.sh" ]]; then
        echo "DEBUG: Running dashboard test" >&2
        if run_test "$script" "$script"; then
            echo -e "${GREEN}PASS${NC}"
            PASS=$((PASS+1))
        else
            rc=$?
            echo -e "${RED}FAIL (execution, exit code $rc)${NC}"
            FAIL=$((FAIL+1))
        fi
        continue
    fi
    # -------------------------------------------------------------------
    # Special case: backup-verifier.sh needs a dummy backup dir
    # -------------------------------------------------------------------
    if [[ "$script" == "backup-verifier.sh" ]]; then
        if run_test "$script" "$script" --backup-dir "/tmp/test-backups" --num-files 1 --dry-run; then
            echo -e "${GREEN}PASS${NC}"
            PASS=$((PASS+1))
        else
            echo -e "${RED}FAIL (dry-run on dummy backup)${NC}"
            FAIL=$((FAIL+1))
        fi
        continue
    fi

    # -------------------------------------------------------------------
    # Special case: images-to-pdf.sh needs a test image
    # -------------------------------------------------------------------
    if [[ "$script" == "images-to-pdf.sh" ]]; then
        if [ ! -f "$TEST_IMAGE" ]; then
            echo -e "${YELLOW}SKIP (no test image)${NC}"
            SKIP=$((SKIP+1))
            continue
        fi
        if run_test "$script" "$script" -o /tmp/test.pdf "$TEST_IMAGE"; then
            echo -e "${GREEN}PASS${NC}"
            PASS=$((PASS+1))
        else
            echo -e "${RED}FAIL (conversion)${NC}"
            FAIL=$((FAIL+1))
        fi
        continue
    fi

    # -------------------------------------------------------------------
    # Special case: run-hogwarts-trainer.sh – just check help
    # -------------------------------------------------------------------
    if [[ "$script" == "run-hogwarts-trainer.sh" ]]; then
        if run_test "$script" "$script" --help; then
            echo -e "${GREEN}PASS${NC}"
            PASS=$((PASS+1))
        else
            echo -e "${RED}FAIL (--help)${NC}"
            FAIL=$((FAIL+1))
        fi
        continue
    fi

    # -------------------------------------------------------------------
    # General test: check --help
    # -------------------------------------------------------------------
    if ! run_test "$script" "$script" --help; then
        echo -e "${RED}FAIL (--help)${NC}"
        FAIL=$((FAIL+1))
        continue
    fi

    # Check --version if present
    if grep -q "show_version" "$script"; then
        if ! run_test "$script" "$script" --version; then
            echo -e "${RED}FAIL (--version)${NC}"
            FAIL=$((FAIL+1))
            continue
        fi
    fi

    # -------------------------------------------------------------------
    # Additional dry‑run tests for scripts that support it
    # -------------------------------------------------------------------
    case "$script" in
        backup-to-nas.sh|disk-sentinel.sh|organize-downloads.sh|undo-organizer.sh|log-rotator.sh)
            if ! run_test "$script" "$script" --dry-run; then
                echo -e "${RED}FAIL (--dry-run)${NC}"
                FAIL=$((FAIL+1))
                continue
            fi
            ;;
        checksum.sh)
            tmp=$(mktemp)
            echo "test" > "$tmp"
            if ! run_test "$script" "$script" "$tmp"; then
                echo -e "${RED}FAIL (checksum generation)${NC}"
                FAIL=$((FAIL+1))
                rm -f "$tmp"
                continue
            fi
            rm -f "$tmp"
            ;;
        # Scripts that only need help test (already passed)
        cloud-backup.sh|config-check.sh|motd-generator.sh|noba-completion.sh|noba-cron-setup.sh|noba-daily-digest.sh|noba-dashboard.sh|noba-setup.sh|noba-tui.sh|noba-update.sh|system-report.sh)
            ;;
        *)
            # Already passed help
            ;;
    esac

    echo -e "${GREEN}PASS${NC}"
    PASS=$((PASS+1))
done

# -------------------------------------------------------------------
# Extra edge‑case tests
# -------------------------------------------------------------------
log_info "Running extra edge‑case tests..."

# Helper function for edge test reporting
edge_test() {
    local name="$1"
    local result=$2
    echo -n "Edge test: $name ... "
    if [ $result -eq 0 ]; then
        echo -e "${GREEN}PASS${NC}"
        PASS=$((PASS+1))
    else
        echo -e "${RED}FAIL (exit $result)${NC}"
        FAIL=$((FAIL+1))
    fi
}

# 1. Test invalid option for each script (should fail)
for script in *.sh; do
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" ]] && continue
    # Skip scripts that don't use getopt (like noba, which is a wrapper)
    if [[ "$script" == "noba" ]]; then
        continue
    fi
    # Run with --invalid-option and expect failure
    run_test "$script" "$script" --invalid-option
    edge_test "$script --invalid-option" $?
done

# 2. Test missing required arguments
# backup-to-nas.sh requires --source and --dest
run_test "backup-to-nas.sh" "backup-to-nas.sh" --dest /tmp
edge_test "backup-to-nas.sh (missing --source)" $?

run_test "backup-to-nas.sh" "backup-to-nas.sh" --source /tmp
edge_test "backup-to-nas.sh (missing --dest)" $?

# organize-downloads.sh has no required args, but we can test with non-existent dir
run_test "organize-downloads.sh" "organize-downloads.sh" --download-dir /does/not/exist
edge_test "organize-downloads.sh (non-existent dir)" $?

# 3. Test checksum.sh with large number of files (performance smoke test)
run_test "checksum.sh" "checksum.sh" "$LARGE_DIR"/*
edge_test "checksum.sh (100 files)" $?

# 4. Test organize-downloads.sh with file containing spaces and special chars
# Copy the special file to Downloads (or a temp dir)
TEST_DOWNLOAD_DIR="/tmp/test-downloads"
mkdir -p "$TEST_DOWNLOAD_DIR"
cp "$TEST_SPECIAL" "$TEST_DOWNLOAD_DIR/"
run_test "organize-downloads.sh" "organize-downloads.sh" --download-dir "$TEST_DOWNLOAD_DIR" --dry-run
edge_test "organize-downloads.sh (special chars)" $?
rm -rf "$TEST_DOWNLOAD_DIR"

# 5. Test images-to-pdf.sh with non-image file
TMP_TEXT=$(mktemp)
echo "not an image" > "$TMP_TEXT"
run_test "images-to-pdf.sh" "images-to-pdf.sh" -o /tmp/out.pdf "$TMP_TEXT"
edge_test "images-to-pdf.sh (invalid input)" $?
rm -f "$TMP_TEXT" /tmp/out.pdf

# 6. Test config-check.sh with invalid YAML
# Temporarily set NOBA_CONFIG to point to invalid YAML
export NOBA_CONFIG="$INVALID_YAML"
run_test "config-check.sh" "config-check.sh"
edge_test "config-check.sh (invalid YAML)" $?
unset NOBA_CONFIG

# 7. Test noba CLI commands
run_test "noba" "noba" list
edge_test "noba list" $?
run_test "noba" "noba" doctor --dry-run
edge_test "noba doctor --dry-run" $?
run_test "noba" "noba" run backup --dry-run
edge_test "noba run backup --dry-run" $?
# noba config (without --edit) should show config or fail if missing; we have config, so it should succeed
run_test "noba" "noba" config
edge_test "noba config" $?

# 8. Test scripts that require sudo (if possible without password)
if sudo -n true 2>/dev/null; then
    # We can run a sudo-requiring script with --help or --dry-run, but they usually don't need sudo for that.
    # For now, we skip because our scripts don't have direct sudo tests.
    log_info "Sudo available – could add more tests here."
fi

# 9. Test that dry-run on non-existent destination exits 0 for backup-to-nas.sh
run_test "backup-to-nas.sh" "backup-to-nas.sh" --source /tmp --dest /does/not/exist --dry-run
edge_test "backup-to-nas.sh (dry-run with missing dest)" $?

# 10. Test log-rotator.sh with non-existent directory
run_test "log-rotator.sh" "log-rotator.sh" --log-dir /does/not/exist --dry-run
edge_test "log-rotator.sh (non-existent dir)" $?

# -------------------------------------------------------------------
# Cleanup
# -------------------------------------------------------------------
rm -rf "/tmp/test-backups"
rm -f "/tmp/test.png" "/tmp/test.pdf"
rm -rf "/tmp/Download"
rm -rf "$LARGE_DIR"
rm -f "$INVALID_YAML"

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
echo ""
log_info "Results: $PASS passed, $FAIL failed, $SKIP skipped"

if [ "$FAIL" -gt 0 ]; then
    exit 1
else
    exit 0
fi
