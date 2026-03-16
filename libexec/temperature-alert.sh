#!/usr/bin/env bash
# temperature-alert.sh – Monitor CPU/GPU/NVMe temperatures and alert on threshold breach
# Version: 1.0.0
#
# Reads thresholds from config.yaml (.temperature section), falls back to safe
# built-in defaults. Sends a desktop notification and optional email on breach.
#
# Usage:
#   noba watch          (via systemd timer or manually)
#   temperature-alert.sh [--once] [--verbose] [--dry-run]
#
# Exit codes:
#   0  All temps within thresholds (or dry-run)
#   1  One or more thresholds breached
#   2  sensors not available / fatal error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults (overridden by config.yaml .temperature.*) ───────────────────────
WARN_TEMP=75       # °C — log a warning, no notification yet
CRIT_TEMP=90       # °C — desktop notification + optional email
EMAIL="${EMAIL:-}" # alert email (empty = skip email)
COOLDOWN=300       # seconds between repeat alerts for the same sensor
DRY_RUN=false
ONCE=false         # run once and exit (vs. looping — loop mode is for manual use)
export VERBOSE=false

COOLDOWN_DIR="${XDG_RUNTIME_DIR:-/tmp}/noba-temp-cooldown"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/noba/temperature-alert.log}"

# ── Help ──────────────────────────────────────────────────────────────────────
show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Monitor system temperatures and alert when thresholds are breached.

Options:
  -n, --dry-run     Parse and report temps, but send no notifications or emails
  -1, --once        Run a single check and exit (default when called directly)
  -v, --verbose     Show all sensor readings, not just warnings/breaches
      --help        Show this message and exit

Thresholds are read from ~/.config/noba/config.yaml:
  temperature:
    warn_temp:  75     # log warning (°C)
    crit_temp:  90     # notify + email (°C)
    email:      you@example.com
    cooldown:   300    # seconds between repeat alerts per sensor

Exit codes:
  0  All sensors within thresholds
  1  One or more thresholds breached
  2  Fatal error (sensors unavailable, etc.)
EOF
    exit 0
}

# ── Argument parsing ──────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt -o n1vh -l dry-run,once,verbose,help -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 2
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -n|--dry-run)  DRY_RUN=true;        shift ;;
        -1|--once)     ONCE=true;            shift ;;
        -v|--verbose)  export VERBOSE=true;  shift ;;
        -h|--help)     show_help ;;
        --)            shift; break ;;
        *)             log_error "Unknown argument: $1"; exit 2 ;;
    esac
done

# ── Load config ───────────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    WARN_TEMP=$(  get_config ".temperature.warn_temp"  "$WARN_TEMP")
    CRIT_TEMP=$(  get_config ".temperature.crit_temp"  "$CRIT_TEMP")
    EMAIL=$(      get_config ".temperature.email"      "$EMAIL")
    COOLDOWN=$(   get_config ".temperature.cooldown"   "$COOLDOWN")
fi

# ── Sanity checks ─────────────────────────────────────────────────────────────
command -v sensors &>/dev/null || die \
    "lm-sensors not found. Install with: sudo dnf install lm_sensors && sudo sensors-detect"

for v in WARN_TEMP CRIT_TEMP COOLDOWN; do
    [[ "${!v}" =~ ^[0-9]+$ ]] || die "$v must be a positive integer, got: ${!v}"
done

(( CRIT_TEMP > WARN_TEMP )) || die "crit_temp ($CRIT_TEMP) must be greater than warn_temp ($WARN_TEMP)."

# ── Logging ───────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
mkdir -p "$COOLDOWN_DIR"

# ── Cooldown helpers ──────────────────────────────────────────────────────────
# One file per sensor slug. Contains the epoch timestamp of the last alert.
_sensor_slug() {
    # Turn "Core 0 (Package)" into "core_0_package" — safe for filenames
    echo "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_' | sed 's/_\+/_/g;s/^_//;s/_$//'
}

_in_cooldown() {
    local slug="$1"
    local state_file="$COOLDOWN_DIR/$slug"
    [[ -f "$state_file" ]] || return 1          # no prior alert → not in cooldown
    local last_alert
    last_alert=$(cat "$state_file" 2>/dev/null || echo 0)
    local now
    now=$(date +%s)
    (( (now - last_alert) < COOLDOWN ))
}

_mark_alerted() {
    local slug="$1"
    date +%s > "$COOLDOWN_DIR/$slug"
}

_clear_cooldown() {
    local slug="$1"
    rm -f "$COOLDOWN_DIR/$slug"
}

# ── Notification ──────────────────────────────────────────────────────────────
_send_alert() {
    local sensor="$1" temp="$2" threshold="$3" level="$4"  # level: warn | crit
    local title body icon

    if [[ "$level" == "crit" ]]; then
        title="🔥 CRITICAL: $sensor at ${temp}°C"
        icon="dialog-error"
    else
        title="⚠️  WARNING: $sensor at ${temp}°C"
        icon="dialog-warning"
    fi
    body="Threshold: ${threshold}°C  |  Host: $(hostname)  |  $(date '+%H:%M:%S')"

    log_warn "$title — $body"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would send notification: $title"
        return
    fi

    # Desktop notification (non-fatal if DISPLAY/WAYLAND_DISPLAY not set)
    if command -v notify-send &>/dev/null; then
        local urgency="normal"
        [[ "$level" == "crit" ]] && urgency="critical"
        notify-send --urgency="$urgency" --icon="$icon" \
            --app-name="Nobara Automation" \
            --expire-time=10000 \
            "$title" "$body" 2>/dev/null || true
    fi

    # Email for critical only (don't spam on warn)
    if [[ "$level" == "crit" && -n "$EMAIL" ]]; then
        local subject="🔥 Temp Alert: $sensor ${temp}°C on $(hostname)"
        local msg_body
        msg_body=$(cat <<EOF
CRITICAL TEMPERATURE ALERT
===========================
Sensor:    $sensor
Temp:      ${temp}°C
Threshold: ${threshold}°C
Host:      $(hostname)
Time:      $(date '+%Y-%m-%d %H:%M:%S')

Recent sensor output:
$(sensors 2>/dev/null || echo "(sensors unavailable)")
EOF
)
        if command -v mail &>/dev/null; then
            echo "$msg_body" | mail -s "$subject" "$EMAIL" 2>/dev/null || \
                log_warn "Failed to send email alert."
        else
            log_warn "mail not found — cannot send email alert to $EMAIL."
        fi
    fi
}

# ── Core check ────────────────────────────────────────────────────────────────
# Parse `sensors` output. We handle two common formats:
#
#   Core 0:        +52.0°C  (high = +80.0°C, crit = +100.0°C)
#   Tdie:          +61.5°C  (high = +95.0°C)
#   Composite:     +38.9°C  (low  =  -5.2°C, high = +79.8°C)
#
# We extract lines with a °C reading and pull the first numeric temperature.

run_check() {
    local breach_count=0
    local checked=0

    while IFS= read -r line; do
        # Match lines like:  SensorName:    +52.0°C  ...
        # Capture: sensor label and temperature value
        if [[ "$line" =~ ^([^:]+):[[:space:]]+\+?(-?[0-9]+\.[0-9]+).C ]]; then
            local sensor_label temp_float temp_int
            sensor_label=$(echo "${BASH_REMATCH[1]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            temp_float="${BASH_REMATCH[2]}"
            temp_int=$(printf '%.0f' "$temp_float")   # round to nearest int for comparison
            (( checked++ )) || true

            local slug
            slug=$(_sensor_slug "$sensor_label")

            if (( temp_int >= CRIT_TEMP )); then
                if ! _in_cooldown "${slug}_crit"; then
                    _send_alert "$sensor_label" "$temp_int" "$CRIT_TEMP" "crit"
                    _mark_alerted "${slug}_crit"
                    [[ "$DRY_RUN" != true ]] && _mark_alerted "${slug}_warn"
                else
                    log_verbose "CRIT suppressed (cooldown): $sensor_label ${temp_int}°C"
                fi
                (( breach_count++ )) || true

            elif (( temp_int >= WARN_TEMP )); then
                if ! _in_cooldown "${slug}_warn"; then
                    _send_alert "$sensor_label" "$temp_int" "$WARN_TEMP" "warn"
                    _mark_alerted "${slug}_warn"
                else
                    log_verbose "WARN suppressed (cooldown): $sensor_label ${temp_int}°C"
                fi
                (( breach_count++ )) || true

            else
                # Temp has returned to normal — clear any active cooldown
                _clear_cooldown "${slug}_warn" 2>/dev/null || true
                _clear_cooldown "${slug}_crit" 2>/dev/null || true
                log_verbose "OK: $sensor_label ${temp_int}°C  (warn=${WARN_TEMP} crit=${CRIT_TEMP})"
            fi
        fi
    done < <(sensors 2>/dev/null)

    if (( checked == 0 )); then
        log_warn "No temperature sensors found in sensors output."
        return 2
    fi

    log_verbose "Checked $checked sensor reading(s). Breaches: $breach_count."
    return $(( breach_count > 0 ? 1 : 0 ))
}

# ── Main ──────────────────────────────────────────────────────────────────────
log_verbose "temperature-alert starting (warn=${WARN_TEMP}°C crit=${CRIT_TEMP}°C cooldown=${COOLDOWN}s)"

run_check
EXIT_CODE=$?

if (( EXIT_CODE == 0 )); then
    log_verbose "All temperatures normal."
elif (( EXIT_CODE == 1 )); then
    # Already logged per-sensor above; just append to log file
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Breach(es) detected — see above" >> "$LOG_FILE"
fi

exit $EXIT_CODE
