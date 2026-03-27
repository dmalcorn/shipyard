#!/bin/bash
#
# build-loop - Automated Epic Development Orchestration for PetCompass (Django)
#
# Automates the cycle:
#    SM:CS -> TEA:AT -> DEV:DS -> TEA:TA -> TEA:RV -> DEV:CR -> CI -> Commit
#
# Each story runs in a fresh Claude session to keep context clean.
#
# Usage: ./looper/build-loop.sh <epic-number>
# Example: ./looper/build-loop.sh 0
#
# Stop: Ctrl+C (graceful shutdown)
#
# Prerequisites:
#   - Claude Code CLI installed
#   - Docker services running (backend, admin, postgres, redis)
#
# Security: Uses scoped --allowedTools instead of --dangerously-skip-permissions
# Each phase only gets the minimum tools required for its specific task.
#

set -e
set -o pipefail  # Ensure pipeline exit status reflects failed commands (not just tee)

# =============================================================================
# Configuration
# =============================================================================
EPIC_INPUT="${1:-}"  # Raw input (may be comma-separated)
EPIC_NUMBER=""       # Set per-epic in the loop
MAX_ITERATIONS_PER_PHASE=5
MAX_CI_ATTEMPTS=4

# Timeout settings for Claude CLI calls (prevents infinite hangs)
CLAUDE_TIMEOUT_SHORT="15m"   # For quick phases (SM, TEA)
CLAUDE_TIMEOUT_LONG="45m"    # For complex phases (DEV:DS, CI fix)
CLAUDE_TIMEOUT_MEDIUM="25m"  # For medium phases (TEA:RV, DEV:CR)

# Diagnostic settings for freeze investigation
FREEZE_DIAGNOSTICS_ENABLED=true
FREEZE_DIAGNOSTIC_LOG=""  # Set per-epic by setup_epic_paths()

# Track current Claude process for cleanup on Ctrl+C
CURRENT_CLAUDE_PGID=""

# Timezone for timestamps (Mountain Time - Denver)
export TZ="America/Denver"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="$PROJECT_ROOT/_bmad-output"
LOOPER_DIR="$PROJECT_ROOT/looper"

# These are set dynamically per-epic by setup_epic_paths()
LOG_FILE=""
STORY_LOG_FILE=""
STATE_FILE=""
CODE_REVIEW_LOG=""

# =============================================================================
# Setup epic-specific paths (called for each epic in the loop)
# =============================================================================
setup_epic_paths() {
    local epic="$1"
    EPIC_NUMBER="$epic"
    LOG_FILE="$LOOPER_DIR/epic${EPIC_NUMBER}-build-loop.log"
    STORY_LOG_FILE=""  # Set dynamically when story starts
    STATE_FILE="$LOOPER_DIR/epic${EPIC_NUMBER}-build-loop-state.json"
    CODE_REVIEW_LOG="$LOOPER_DIR/epic${EPIC_NUMBER}-code-review-build-issues.log"
    FREEZE_DIAGNOSTIC_LOG="$LOOPER_DIR/epic${EPIC_NUMBER}-freeze-diagnostics.log"
}

# =============================================================================
# SCOPED PERMISSIONS - Each phase gets only the tools it needs
# =============================================================================
# Tool reference:
#   Read, Edit, Write, Glob, Grep - File operations (safe)
#   Bash(prefix *) - Shell commands matching prefix only
#   Task, TodoWrite - Agent orchestration tools
# =============================================================================

# Phase 1: SM Create Story - needs file ops + Skill for /sm
TOOLS_SM="Read,Edit,Write,Glob,Grep,Task,TodoWrite,Skill"

# Phase 2-5: TEA Agent - needs file ops + test commands + Skill for /tea
TOOLS_TEA="Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(pytest *),Bash(make *),Skill"

# Phase 5b: TEA RV Fix - needs python for pytest variants + file ops
TOOLS_TEA_FIX="Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pytest *),Bash(make *),Skill"

# Phase 3: DEV Story - needs file ops + Django/git commands + Skill for /dev
TOOLS_DEV_STORY="Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pip *),Bash(pytest *),Bash(make *),Bash(git *),Skill"

# Phase 6: DEV Code Review - needs file ops + test commands + Skill for /dev
TOOLS_CODE_REVIEW="Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(pytest *),Bash(make *),Skill"

# CI Fix: needs file ops + Django commands + process management (Vite restart in WSL2)
TOOLS_CI_FIX="Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pip *),Bash(pytest *),Bash(make *),Bash(ruff *),Bash(mypy *),Bash(bandit *),Bash(pkill *),Bash(kill *),Bash(lsof *),Bash(npx *),Skill"

# =============================================================================
# Colors for output
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# =============================================================================
# Database Connection Reset
# =============================================================================
# Terminates stale PostgreSQL connections to prevent "too many clients" errors.
# Called before every Claude invocation since any phase may run tests.
# Uses docker exec to bypass connection limits when pool is exhausted.
# =============================================================================
reset_db_connections() {
    local DB_CONTAINER="${DB_CONTAINER:-petcompass_db}"
    local DB_USER="${DB_USER:-petcompass}"

    echo -e "${CYAN}[DB] Resetting idle database connections...${NC}" >&2

    # Attempt to reset connections via docker exec
    # This bypasses max_connections limit since it's a local socket connection
    local reset_result
    reset_result=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -t -c "
        SELECT count(*) FROM (
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE pid <> pg_backend_pid()
            AND datname IS NOT NULL
            AND state = 'idle'
        ) AS terminated;
    " 2>/dev/null | tr -dc '0-9' || echo "0")

    echo -e "${CYAN}[DB] Terminated ${reset_result:-0} idle connections${NC}" >&2

    # Pause to let connections fully close
    sleep 1
}

# =============================================================================
# API health check before Claude invocation
# =============================================================================
# Checks if Anthropic API is responsive before making a Claude call
# This helps avoid wasted timeout waits when API is temporarily unavailable
check_api_health() {
    local max_retries=3
    local retry_delay=30
    local attempt=1

    while [[ $attempt -le $max_retries ]]; do
        # Try to reach Anthropic's API (using a lightweight endpoint check)
        # We use api.anthropic.com with a short timeout
        # Note: Don't use -f flag as it suppresses output on HTTP errors
        local http_code
        http_code=$(timeout 15 curl -s -o /dev/null -w "%{http_code}" "https://api.anthropic.com/" 2>/dev/null)
        if echo "$http_code" | grep -qE "^[234]"; then
            # Got a response (2xx, 3xx, or 4xx means API is reachable)
            echo -e "${GREEN}[API] Health check passed${NC}" >&2
            return 0
        fi

        if [[ $attempt -lt $max_retries ]]; then
            echo -e "${YELLOW}[API] Health check failed (attempt $attempt/$max_retries), waiting ${retry_delay}s...${NC}" >&2
            if [[ "$FREEZE_DIAGNOSTICS_ENABLED" == "true" && -n "$FREEZE_DIAGNOSTIC_LOG" ]]; then
                echo "[API] Health check failed at $(date '+%Y-%m-%d %H:%M:%S') (attempt $attempt)" >> "$FREEZE_DIAGNOSTIC_LOG"
            fi
            sleep $retry_delay
            # Increase delay for subsequent retries
            retry_delay=$((retry_delay + 30))
        fi
        ((attempt++))
    done

    echo -e "${RED}[API] Health check failed after $max_retries attempts - API may be unavailable${NC}" >&2
    if [[ "$FREEZE_DIAGNOSTICS_ENABLED" == "true" && -n "$FREEZE_DIAGNOSTIC_LOG" ]]; then
        echo "[API] Health check FAILED after $max_retries attempts at $(date '+%Y-%m-%d %H:%M:%S')" >> "$FREEZE_DIAGNOSTIC_LOG"
    fi
    return 1
}

# =============================================================================
# Claude CLI wrapper with timeout and retry
# =============================================================================
# Wraps claude calls with timeout to prevent infinite hangs
# Args:
#   $1 - timeout duration (e.g., "30m" for 30 minutes)
#   $2 - allowed tools string
#   $3 - prompt text
#   $4 - phase name (optional, for diagnostics)
# Returns: Claude output or error message
# Exit code: 0 on success, 1 on timeout, 2 on other error
invoke_claude_with_timeout() {
    local timeout_duration="$1"
    local allowed_tools="$2"
    local prompt="$3"
    local phase_name="${4:-unknown}"
    local result=""
    local exit_code=0
    local watchdog_pid=""
    local start_time=$(date +%s)
    local invocation_id="$(date +%Y%m%d-%H%M%S)-$$"

    # Reset database connections before invoking Claude
    # This prevents "too many clients" errors from connection accumulation
    reset_db_connections

    # Check API health before invoking Claude
    # This avoids wasted timeout waits when API is temporarily unavailable
    if ! check_api_health; then
        log "WARN" "API health check failed for $phase_name - proceeding anyway but expect possible timeout"
    fi

    # Convert timeout duration to seconds for watchdog calculation
    local timeout_seconds=0
    if [[ "$timeout_duration" =~ ^([0-9]+)m$ ]]; then
        timeout_seconds=$((${BASH_REMATCH[1]} * 60))
    elif [[ "$timeout_duration" =~ ^([0-9]+)s$ ]]; then
        timeout_seconds=${BASH_REMATCH[1]}
    elif [[ "$timeout_duration" =~ ^([0-9]+)$ ]]; then
        timeout_seconds=$timeout_duration
    fi

    # Start diagnostic watchdog if enabled
    # Store parent PID for process tree analysis
    local script_pid=$$

    if [[ "$FREEZE_DIAGNOSTICS_ENABLED" == "true" && -n "$FREEZE_DIAGNOSTIC_LOG" && $timeout_seconds -gt 60 ]]; then
        # Watchdog captures diagnostics at 50%, 75%, 90%, and 95% of timeout
        (
            # Ensure PATH includes standard locations
            export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

            local diag_log="$FREEZE_DIAGNOSTIC_LOG"
            local check_intervals=()

            # Calculate check points (in seconds from start)
            # 10% = 3.5 min for 35m timeout - catches active state before potential freeze
            # 25% = 8.75 min - secondary early check (after typical successful completion)
            check_intervals+=($((timeout_seconds * 10 / 100)))   # 10% (~3.5 min)
            check_intervals+=($((timeout_seconds * 25 / 100)))   # 25% (~8.75 min)
            check_intervals+=($((timeout_seconds * 50 / 100)))   # 50%
            check_intervals+=($((timeout_seconds * 75 / 100)))   # 75%
            check_intervals+=($((timeout_seconds * 90 / 100)))   # 90%
            check_intervals+=($((timeout_seconds * 95 / 100)))   # 95%

            local last_check=0
            for check_time in "${check_intervals[@]}"; do
                local sleep_duration=$((check_time - last_check))
                sleep $sleep_duration 2>/dev/null || exit 0
                last_check=$check_time

                local elapsed=$(($(date +%s) - start_time))
                local pct=$((elapsed * 100 / timeout_seconds))

                {
                    echo ""
                    echo "============================================================"
                    echo "FREEZE DIAGNOSTIC: $invocation_id"
                    echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
                    echo "Phase: $phase_name"
                    echo "Elapsed: ${elapsed}s / ${timeout_seconds}s (${pct}%)"
                    echo "Script PID: $script_pid"
                    echo "============================================================"

                    # Use /proc directly since ps may not be available
                    echo ""
                    echo "--- Process Tree (via /proc) ---"
                    # Walk from script_pid down through children
                    show_proc_tree() {
                        local pid=$1
                        local indent="${2:-}"
                        if [[ -d "/proc/$pid" ]]; then
                            local comm=$(cat /proc/$pid/comm 2>/dev/null || echo "?")
                            local state=$(cat /proc/$pid/stat 2>/dev/null | awk '{print $3}' || echo "?")
                            echo "${indent}PID $pid: $comm (state: $state)"
                            # Find children of this pid
                            for child_dir in /proc/[0-9]*; do
                                local child_pid=$(basename "$child_dir")
                                local child_ppid=$(cat /proc/$child_pid/stat 2>/dev/null | awk '{print $4}')
                                if [[ "$child_ppid" == "$pid" ]]; then
                                    show_proc_tree "$child_pid" "  $indent"
                                fi
                            done 2>/dev/null
                        fi
                    }
                    show_proc_tree $script_pid ""

                    echo ""
                    echo "--- All Processes (via /proc, showing claude/node/timeout) ---"
                    for pid_dir in /proc/[0-9]*; do
                        pid=$(basename "$pid_dir")
                        if [[ -f "/proc/$pid/comm" ]]; then
                            comm=$(cat /proc/$pid/comm 2>/dev/null)
                            if [[ "$comm" =~ ^(claude|node|timeout|deno)$ ]]; then
                                cmdline=$(cat /proc/$pid/cmdline 2>/dev/null | tr '\0' ' ' | head -c 200)
                                state=$(cat /proc/$pid/stat 2>/dev/null | awk '{print $3}')
                                ppid=$(cat /proc/$pid/stat 2>/dev/null | awk '{print $4}')
                                echo "  PID $pid ($comm) state=$state ppid=$ppid"
                                echo "    cmd: ${cmdline:0:150}"
                            fi
                        fi
                    done 2>/dev/null | head -20 || echo "(none found)"

                    echo ""
                    echo "--- Network Connections ---"
                    # Try /proc/net/tcp for connection info
                    if [[ -r /proc/net/tcp ]]; then
                        established=$(cat /proc/net/tcp 2>/dev/null | awk '$4=="01"' | wc -l)
                        echo "ESTABLISHED connections: $established"
                        cat /proc/net/tcp 2>/dev/null | awk '$4=="01" {print "  " $2 " -> " $3}' | head -5
                    else
                        echo "(cannot read /proc/net/tcp)"
                    fi

                    echo ""
                    echo "--- Open File Descriptors (script $script_pid children) ---"
                    for child_dir in /proc/[0-9]*; do
                        child_pid=$(basename "$child_dir")
                        child_ppid=$(cat /proc/$child_pid/stat 2>/dev/null | awk '{print $4}')
                        if [[ "$child_ppid" == "$script_pid" && -d "/proc/$child_pid/fd" ]]; then
                            comm=$(cat /proc/$child_pid/comm 2>/dev/null || echo "?")
                            fd_count=$(ls /proc/$child_pid/fd 2>/dev/null | wc -l)
                            echo "  Child PID $child_pid ($comm): $fd_count open fds"
                            ls -la /proc/$child_pid/fd 2>/dev/null | grep -E 'pipe|socket' | head -3
                        fi
                    done 2>/dev/null

                    echo ""
                    echo "--- System Load ---"
                    cat /proc/loadavg 2>/dev/null || echo "(unavailable)"

                    echo ""
                    echo "--- Memory ---"
                    cat /proc/meminfo 2>/dev/null | head -3 || echo "(unavailable)"

                    echo ""
                    echo "--- Zombie Processes ---"
                    zombies_found=0
                    for pid_dir in /proc/[0-9]*; do
                        pid=$(basename "$pid_dir")
                        state=$(cat /proc/$pid/stat 2>/dev/null | awk '{print $3}')
                        if [[ "$state" == "Z" ]]; then
                            comm=$(cat /proc/$pid/comm 2>/dev/null || echo "?")
                            echo "  ZOMBIE: PID $pid ($comm)"
                            zombies_found=1
                        fi
                    done 2>/dev/null
                    [[ $zombies_found -eq 0 ]] && echo "(none)"

                    echo "============================================================"
                    echo ""
                } >> "$diag_log" 2>/dev/null
            done
        ) &
        watchdog_pid=$!
    fi

    # Log invocation start
    if [[ "$FREEZE_DIAGNOSTICS_ENABLED" == "true" && -n "$FREEZE_DIAGNOSTIC_LOG" ]]; then
        {
            echo ""
            echo ">>> INVOCATION START: $invocation_id"
            echo "    Time: $(date '+%Y-%m-%d %H:%M:%S')"
            echo "    Phase: $phase_name"
            echo "    Timeout: $timeout_duration ($timeout_seconds seconds)"
            echo "    Tools: $allowed_tools"
        } >> "$FREEZE_DIAGNOSTIC_LOG" 2>/dev/null
    fi

    # Use setsid to run claude in its own process group (session)
    # This allows us to kill the entire process tree on timeout, not just claude
    local output_file=$(mktemp)
    local pgid_file=$(mktemp)
    local prompt_file=$(mktemp)

    # Write prompt to temp file to avoid shell escaping issues
    printf '%s' "$prompt" > "$prompt_file"

    # Start claude in its own session using setsid
    # setsid creates a new session, making the process its own process group leader
    setsid bash -c '
        echo $$ > "'"$pgid_file"'"
        exec claude --print --allowedTools "'"$allowed_tools"'" -- "$(cat "'"$prompt_file"'")"
    ' </dev/null >"$output_file" 2>&1 &
    local bg_pid=$!

    # Small delay to ensure PGID file is written
    sleep 0.1
    local claude_pgid=$(cat "$pgid_file" 2>/dev/null || echo "$bg_pid")
    CURRENT_CLAUDE_PGID="$claude_pgid"  # Track for cleanup on Ctrl+C

    # Wait for the process with timeout
    # We use a background wait + sleep approach for portability
    local wait_exit_code=0
    (
        # Wait for the background process to complete
        wait $bg_pid 2>/dev/null
    ) &
    local waiter_pid=$!

    # Use timeout to wait for the waiter process
    # --foreground keeps timeout in the terminal's process group so Ctrl+C works
    if timeout --foreground "$timeout_duration" tail --pid=$bg_pid -f /dev/null 2>/dev/null; then
        # Process completed within timeout
        wait $bg_pid 2>/dev/null
        exit_code=$?
        result=$(cat "$output_file")
    else
        # Timeout occurred - kill entire process group
        # First try SIGTERM to allow graceful shutdown
        kill -TERM -"$claude_pgid" 2>/dev/null || true
        sleep 2
        # Then SIGKILL to ensure cleanup
        kill -KILL -"$claude_pgid" 2>/dev/null || true
        # Also kill the specific PID in case setsid didn't work
        kill -KILL $bg_pid 2>/dev/null || true

        exit_code=124  # Standard timeout exit code
        result="TIMEOUT: Claude CLI did not respond within $timeout_duration"
    fi

    # Clean up waiter if still running
    kill $waiter_pid 2>/dev/null || true
    wait $waiter_pid 2>/dev/null || true

    # Clean up temp files and clear process tracking
    rm -f "$output_file" "$pgid_file" "$prompt_file"
    CURRENT_CLAUDE_PGID=""

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Kill watchdog if still running
    if [[ -n "$watchdog_pid" ]]; then
        kill $watchdog_pid 2>/dev/null
        wait $watchdog_pid 2>/dev/null
    fi

    # Log invocation end
    if [[ "$FREEZE_DIAGNOSTICS_ENABLED" == "true" && -n "$FREEZE_DIAGNOSTIC_LOG" ]]; then
        local status_msg="SUCCESS"
        if [[ $exit_code -eq 124 ]]; then
            status_msg="TIMEOUT"
        elif [[ $exit_code -ne 0 ]]; then
            status_msg="ERROR (exit code: $exit_code)"
        fi
        {
            echo "<<< INVOCATION END: $invocation_id"
            echo "    Time: $(date '+%Y-%m-%d %H:%M:%S')"
            echo "    Duration: ${duration}s"
            echo "    Status: $status_msg"
            echo ""
        } >> "$FREEZE_DIAGNOSTIC_LOG" 2>/dev/null
    fi

    # timeout exit code 124 means the command timed out
    if [[ $exit_code -eq 124 ]]; then
        echo "TIMEOUT: Claude CLI did not respond within $timeout_duration"
        return 1
    elif [[ $exit_code -ne 0 ]]; then
        echo "$result"
        return 2
    fi

    echo "$result"
    return 0
}

# =============================================================================
# Logging function (writes to epic summary log AND story log if set)
# =============================================================================
log() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    case "$level" in
        "INFO")    echo -e "${CYAN}${timestamp} [${level}] ${message}${NC}" ;;
        "WARN")    echo -e "${YELLOW}${timestamp} [${level}] ${message}${NC}" ;;
        "ERROR")   echo -e "${RED}${timestamp} [${level}] ${message}${NC}" ;;
        "SUCCESS") echo -e "${GREEN}${timestamp} [${level}] ${message}${NC}" ;;
        *)         echo -e "${timestamp} [${level}] ${message}" ;;
    esac

    # Always write to epic summary log (if LOG_FILE is set)
    if [[ -n "$LOG_FILE" ]]; then
        echo "${timestamp} [${level}] ${message}" >> "$LOG_FILE"
    fi

    # Also write to story log if set
    if [[ -n "$STORY_LOG_FILE" ]]; then
        echo "${timestamp} [${level}] ${message}" >> "$STORY_LOG_FILE"
    fi
}

# =============================================================================
# Story logging function (writes to per-story detailed log)
# =============================================================================
log_story() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    if [[ -n "$STORY_LOG_FILE" ]]; then
        echo "${timestamp} [${level}] ${message}" >> "$STORY_LOG_FILE"
    fi
}

# =============================================================================
# Initialize story log file
# =============================================================================
init_story_log() {
    local story_id="$1"
    local is_resume="${2:-false}"
    STORY_LOG_FILE="$LOOPER_DIR/story-${story_id}.log"

    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # If resuming and log file exists, append resume marker instead of overwriting
    if [[ "$is_resume" == "true" && -f "$STORY_LOG_FILE" ]]; then
        cat >> "$STORY_LOG_FILE" << EOF

================================================================================
RESUMED: $timestamp
Epic: $EPIC_NUMBER
================================================================================

EOF
        log "INFO" "Story log resumed: $STORY_LOG_FILE"
    else
        # New story or log doesn't exist - create fresh
        cat > "$STORY_LOG_FILE" << EOF
================================================================================
STORY LOG: $story_id
Started: $timestamp
Epic: $EPIC_NUMBER
================================================================================

EOF
        log "INFO" "Story log initialized: $STORY_LOG_FILE"
    fi
}

# =============================================================================
# Prompt logging function (writes to story log)
# =============================================================================
log_prompt() {
    local phase="$1"
    local story_id="$2"
    local attempt="$3"
    local prompt="$4"

    local hash=$(echo -n "$prompt" | sha256sum | cut -c1-8)
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Write to story log (detailed)
    if [[ -n "$STORY_LOG_FILE" ]]; then
        cat >> "$STORY_LOG_FILE" << EOF

================================================================================
PROMPT: $phase | Story: $story_id | Attempt: $attempt
Time: $timestamp
Hash: $hash
================================================================================
$prompt
================================================================================

EOF
    fi
}

# =============================================================================
# Output preview function (writes preview to story log, shows on terminal)
# =============================================================================
log_output_preview() {
    local phase="$1"
    local output="$2"
    local lines="${3:-5}"

    local preview=$(echo "$output" | head -n "$lines")

    # Write to story log
    if [[ -n "$STORY_LOG_FILE" ]]; then
        cat >> "$STORY_LOG_FILE" << EOF

--- OUTPUT PREVIEW: $phase (first $lines lines) ---
$preview
--- END PREVIEW ---

EOF
    fi

    # Show on terminal
    echo ""
    echo -e "${CYAN}--- OUTPUT PREVIEW: $phase (first $lines lines) ---${NC}"
    echo "$preview"
    echo -e "${CYAN}--- END PREVIEW ---${NC}"
    echo ""
}

# =============================================================================
# Duration formatting function
# =============================================================================
format_duration() {
    local seconds="$1"
    if [[ $seconds -ge 60 ]]; then
        local mins=$((seconds / 60))
        local secs=$((seconds % 60))
        echo "${mins}m ${secs}s"
    else
        echo "${seconds}s"
    fi
}

# Format seconds to mm:ss or h:mm:ss for table display
format_table_time() {
    local seconds="$1"
    if [[ -z "$seconds" || "$seconds" -eq 0 ]]; then
        echo "   -  "
        return
    fi

    local hours=$((seconds / 3600))
    local mins=$(((seconds % 3600) / 60))
    local secs=$((seconds % 60))

    if [[ $hours -gt 0 ]]; then
        printf "%d:%02d:%02d" "$hours" "$mins" "$secs"
    else
        printf "%3d:%02d" "$mins" "$secs"
    fi
}

# =============================================================================
# Epic Summary Table
# =============================================================================
print_epic_summary() {
    if [[ ! -f "$STATE_FILE" ]]; then
        log "WARN" "No state file found - cannot generate summary"
        return
    fi

    local durations
    durations=$(jq -c '.durations // {}' "$STATE_FILE" 2>/dev/null)
    if [[ -z "$durations" || "$durations" == "{}" || "$durations" == "null" ]]; then
        log "WARN" "No duration data found - cannot generate summary"
        return
    fi

    # Get list of stories (sorted)
    local stories
    stories=$(echo "$durations" | jq -r 'keys[]' 2>/dev/null | sort -t'-' -k1,1n -k2,2n)
    if [[ -z "$stories" ]]; then
        return
    fi

    local story_count
    story_count=$(echo "$stories" | wc -l | tr -d ' ')

    # Phase names and display labels
    local -a phases=("sm-cs" "tea-at" "dev-ds" "tea-ta" "tea-rv" "dev-cr" "ci" "commit")
    local -a phase_labels=("SM:CS" "TEA:AT" "DEV:DS" "TEA:TA" "TEA:RV" "DEV:CR" "CI" "Commit")

    # Calculate column width based on story IDs (extract just story number, e.g., "10-1")
    local col_width=8

    # Build arrays for story short names
    local -a story_ids=()
    local -a story_short=()
    while IFS= read -r story; do
        story_ids+=("$story")
        # Extract just the story number part (e.g., "10-1" from "10-1-some-description")
        local short
        short=$(echo "$story" | grep -oE '^[0-9]+-[0-9]+')
        story_short+=("$short")
    done <<< "$stories"

    echo ""
    echo "================================================================================"
    echo "                        EPIC $EPIC_NUMBER COMPLETION SUMMARY"
    echo "================================================================================"
    echo ""
    echo "Phase Durations (mm:ss)"

    # Calculate dynamic widths
    local phase_col_width=14
    local data_col_width=8
    local total_col_width=9
    local avg_col_width=9

    # Build header row
    local header="│ Phase        "
    for short in "${story_short[@]}"; do
        header+="│$(printf "%${data_col_width}s" "$short")"
    done
    header+="│$(printf "%${total_col_width}s" "TOTAL")│$(printf "%${avg_col_width}s" "AVG")│"

    # Calculate total width for separator lines
    local data_section_width=$(( (data_col_width + 1) * story_count ))
    local total_width=$(( phase_col_width + data_section_width + total_col_width + 1 + avg_col_width + 2 ))

    # Top border
    local top_border="┌"
    top_border+="$(printf '─%.0s' $(seq 1 $((phase_col_width - 1))))┬"
    for ((i=0; i<story_count; i++)); do
        top_border+="$(printf '─%.0s' $(seq 1 $data_col_width))┬"
    done
    top_border+="$(printf '─%.0s' $(seq 1 $total_col_width))┬"
    top_border+="$(printf '─%.0s' $(seq 1 $avg_col_width))┐"
    echo "$top_border"

    # Header row
    echo "$header"

    # Header separator
    local header_sep="├"
    header_sep+="$(printf '─%.0s' $(seq 1 $((phase_col_width - 1))))┼"
    for ((i=0; i<story_count; i++)); do
        header_sep+="$(printf '─%.0s' $(seq 1 $data_col_width))┼"
    done
    header_sep+="$(printf '─%.0s' $(seq 1 $total_col_width))┼"
    header_sep+="$(printf '─%.0s' $(seq 1 $avg_col_width))┤"
    echo "$header_sep"

    # Initialize story totals array
    local -a story_totals=()
    for ((i=0; i<story_count; i++)); do
        story_totals+=("0")
    done

    local grand_total=0

    # Data rows (one per phase)
    for p in "${!phases[@]}"; do
        local phase="${phases[$p]}"
        local label="${phase_labels[$p]}"
        local row="│ $(printf "%-12s" "$label")"
        local phase_total=0
        local phase_count=0

        for s in "${!story_ids[@]}"; do
            local story="${story_ids[$s]}"
            local secs
            secs=$(echo "$durations" | jq -r ".\"$story\".\"$phase\" // 0" 2>/dev/null)
            [[ "$secs" == "null" ]] && secs=0

            if [[ "$secs" -gt 0 ]]; then
                local formatted
                formatted=$(format_table_time "$secs")
                row+="│$(printf "%${data_col_width}s" "$formatted")"
                phase_total=$((phase_total + secs))
                story_totals[$s]=$((story_totals[$s] + secs))
                ((phase_count++))
            else
                row+="│$(printf "%${data_col_width}s" "-")"
            fi
        done

        grand_total=$((grand_total + phase_total))

        # Phase total
        local phase_total_fmt
        phase_total_fmt=$(format_table_time "$phase_total")
        row+="│$(printf "%${total_col_width}s" "$phase_total_fmt")"

        # Phase average
        local phase_avg=0
        if [[ $phase_count -gt 0 ]]; then
            phase_avg=$((phase_total / phase_count))
        fi
        local phase_avg_fmt
        phase_avg_fmt=$(format_table_time "$phase_avg")
        row+="│$(printf "%${avg_col_width}s" "$phase_avg_fmt")│"

        echo "$row"
    done

    # Separator before totals
    local total_sep="├"
    total_sep+="$(printf '─%.0s' $(seq 1 $((phase_col_width - 1))))┼"
    for ((i=0; i<story_count; i++)); do
        total_sep+="$(printf '─%.0s' $(seq 1 $data_col_width))┼"
    done
    total_sep+="$(printf '─%.0s' $(seq 1 $total_col_width))┼"
    total_sep+="$(printf '─%.0s' $(seq 1 $avg_col_width))┤"
    echo "$total_sep"

    # Story totals row
    local totals_row="│ $(printf "%-12s" "STORY TOTAL")"
    for s in "${!story_totals[@]}"; do
        local story_total="${story_totals[$s]}"
        local story_total_fmt
        story_total_fmt=$(format_table_time "$story_total")
        totals_row+="│$(printf "%${data_col_width}s" "$story_total_fmt")"
    done

    # Grand total
    local grand_total_fmt
    grand_total_fmt=$(format_table_time "$grand_total")
    totals_row+="│$(printf "%${total_col_width}s" "$grand_total_fmt")"

    # Average per story
    local avg_per_story=0
    if [[ $story_count -gt 0 ]]; then
        avg_per_story=$((grand_total / story_count))
    fi
    local avg_per_story_fmt
    avg_per_story_fmt=$(format_table_time "$avg_per_story")
    totals_row+="│$(printf "%${avg_col_width}s" "$avg_per_story_fmt")│"
    echo "$totals_row"

    # Bottom border
    local bottom_border="└"
    bottom_border+="$(printf '─%.0s' $(seq 1 $((phase_col_width - 1))))┴"
    for ((i=0; i<story_count; i++)); do
        bottom_border+="$(printf '─%.0s' $(seq 1 $data_col_width))┴"
    done
    bottom_border+="$(printf '─%.0s' $(seq 1 $total_col_width))┴"
    bottom_border+="$(printf '─%.0s' $(seq 1 $avg_col_width))┘"
    echo "$bottom_border"

    # Summary line
    local hours=$((grand_total / 3600))
    local mins=$(((grand_total % 3600) / 60))
    local secs=$((grand_total % 60))
    local duration_str
    if [[ $hours -gt 0 ]]; then
        duration_str="${hours}h ${mins}m ${secs}s"
    else
        duration_str="${mins}m ${secs}s"
    fi

    local avg_mins=$((avg_per_story / 60))
    local avg_secs=$((avg_per_story % 60))
    local avg_str="${avg_mins}m ${avg_secs}s"

    echo ""
    echo "Stories: $story_count completed | Epic Duration: $duration_str | Avg per Story: $avg_str"
    echo "================================================================================"
}

# =============================================================================
# Update a key's status to 'done' in sprint-status.yaml
# =============================================================================
set_sprint_status_done() {
    local key="$1"
    local sprint_file="$2"

    if [[ ! -f "$sprint_file" ]]; then
        log "ERROR" "Sprint status file not found: $sprint_file"
        return 1
    fi

    if ! grep -q "^[[:space:]]*${key}:" "$sprint_file" 2>/dev/null; then
        log "ERROR" "Key '$key' not found in sprint-status.yaml"
        return 1
    fi

    sed -i "s/^\([[:space:]]*${key}:\)[[:space:]]*[^[:space:]]*/\1 done/" "$sprint_file"
    return 0
}

# =============================================================================
# Create a git commit for a completed story (LOCAL ONLY)
# Retries automatically if pre-commit hooks modify files
# Checks for common issues BEFORE attempting commit
# =============================================================================
git_commit_story() {
    local story_id="$1"
    local max_retries=3
    local retry_count=0

    cd "$PROJECT_ROOT"

    # =============================================================================
    # Pre-commit checks: Catch common issues before they fail the commit
    # =============================================================================

    # Check 1: Django migrations consistency - auto-create if missing
    log "INFO" "Checking Django migrations consistency..."
    local migration_check
    migration_check=$(cd "$PROJECT_ROOT/backend" && python manage.py makemigrations --check --dry-run 2>&1) || {
        log "WARN" "Django migrations check failed - auto-creating missing migrations..."
        (cd "$PROJECT_ROOT/backend" && python manage.py makemigrations 2>&1) | tee -a "$LOG_FILE"
        log "INFO" "Migrations created - will be included in commit"
    }

    # Check 2: Basic ruff check (faster than full CI)
    log "INFO" "Running pre-commit ruff check..."
    local ruff_check
    if command -v ruff &> /dev/null; then
        ruff_check=$(ruff check "$PROJECT_ROOT/backend" --select=E,F --ignore=E501 --quiet 2>&1) || {
            local error_count=$(echo "$ruff_check" | wc -l)
            if [[ $error_count -gt 0 ]]; then
                log "WARN" "Ruff found $error_count issues - attempting auto-fix..."
                ruff check "$PROJECT_ROOT/backend" --select=E,F --ignore=E501 --fix --quiet 2>&1 || true
            fi
        }
    fi

    # =============================================================================
    # Git commit with retry logic for pre-commit hook modifications
    # =============================================================================
    while [[ $retry_count -lt $max_retries ]]; do
        git add .

        local has_changes=$(git status --porcelain)
        if [[ -z "$has_changes" ]]; then
            log "INFO" "No changes to commit"
            return 0
        fi

        local commit_msg="story ${story_id} complete"
        local commit_output
        local exit_code=0

        commit_output=$(git commit -m "$commit_msg" 2>&1) || exit_code=$?

        # Only show full output on first attempt or final failure
        if [[ $retry_count -eq 0 ]]; then
            echo "$commit_output" | tee -a "$LOG_FILE"
        else
            echo "$commit_output" >> "$LOG_FILE"
        fi

        if [[ $exit_code -eq 0 ]]; then
            if [[ $retry_count -gt 0 ]]; then
                log "SUCCESS" "Commit succeeded after pre-commit auto-fixes (attempt $((retry_count + 1))): $commit_msg"
            else
                log "SUCCESS" "Created commit: $commit_msg"
            fi
            return 0
        fi

        # Check if pre-commit hooks modified files (common patterns)
        if echo "$commit_output" | grep -qE "(files were modified by this hook|reformatted|Fixing )"; then
            ((retry_count++))
            log "INFO" "Pre-commit hooks modified files, re-staging and retrying (attempt $retry_count of $max_retries)..."
            sleep 1
            continue
        fi

        # Check for specific hook failures and attempt auto-fix
        if echo "$commit_output" | grep -qE "Check Django migrations.*Failed|Verify migration field definitions.*Failed"; then
            log "WARN" "Pre-commit hook: Django migrations check failed - auto-creating..."
            (cd "$PROJECT_ROOT/backend" && python manage.py makemigrations 2>&1) | tee -a "$LOG_FILE"
            log "INFO" "Migrations created - retrying commit"
            ((retry_count++))
            sleep 1
            continue
        fi

        if echo "$commit_output" | grep -qE "ruff.*Failed"; then
            log "ERROR" "Pre-commit hook: ruff linting failed"
            log "INFO" "Run: ruff check backend --fix"
            return 1
        fi

        # Some other error occurred - fail immediately
        log "ERROR" "Failed to create commit (non-recoverable error)"
        log "INFO" "Commit output for debugging:"
        echo "$commit_output" | tail -30
        return 1
    done

    log "ERROR" "Failed to create commit after $max_retries retries"
    log "INFO" "Git status:"
    git status --short | head -20
    return 1
}

# =============================================================================
# Graceful shutdown handler
# =============================================================================
shutdown() {
    echo ""
    log "INFO" "Shutting down Build Loop..."

    # Kill Claude process group if running
    if [[ -n "$CURRENT_CLAUDE_PGID" ]]; then
        log "INFO" "Terminating Claude process group ($CURRENT_CLAUDE_PGID)..."
        kill -TERM -"$CURRENT_CLAUDE_PGID" 2>/dev/null || true
        sleep 1
        kill -KILL -"$CURRENT_CLAUDE_PGID" 2>/dev/null || true
    fi

    log "INFO" "State saved to: $STATE_FILE"
    log "INFO" "Log saved to: $LOG_FILE"
    exit 0
}

trap shutdown SIGINT SIGTERM

# =============================================================================
# State Management Functions
# =============================================================================

save_state() {
    local story_number="$1"
    local story_id="$2"
    local phase="$3"
    local attempt="$4"
    local phase_completed="${5:-false}"
    local duration_seconds="${6:-}"

    local completed_phases="[]"
    local durations="{}"

    if [[ -f "$STATE_FILE" ]]; then
        local existing_story_id=$(jq -r '.story_id // ""' "$STATE_FILE" 2>/dev/null || echo "")
        if [[ "$existing_story_id" == "$story_id" ]]; then
            completed_phases=$(jq -c '.completed_phases // []' "$STATE_FILE" 2>/dev/null || echo "[]")
        fi
        # Always preserve all durations across stories
        durations=$(jq -c '.durations // {}' "$STATE_FILE" 2>/dev/null || echo "{}")
    fi

    if [[ "$phase_completed" == "true" ]]; then
        completed_phases=$(echo "$completed_phases" | jq -c ". + [\"$phase\"] | unique")
    fi

    # Add duration for this phase if provided
    if [[ -n "$duration_seconds" && "$duration_seconds" -gt 0 ]]; then
        durations=$(echo "$durations" | jq -c ".\"$story_id\".\"$phase\" = $duration_seconds")
    fi

    cat > "$STATE_FILE" << EOF
{
    "epic": $EPIC_NUMBER,
    "current_story": $story_number,
    "story_id": "$story_id",
    "phase": "$phase",
    "ci_attempt": $attempt,
    "completed_phases": $completed_phases,
    "durations": $durations,
    "timestamp": "$(date -Iseconds)"
}
EOF
}

complete_phase() {
    local story_number="$1"
    local story_id="$2"
    local phase="$3"
    local duration_seconds="${4:-0}"
    save_state "$story_number" "$story_id" "$phase" 0 "true" "$duration_seconds"
}

test_phase_completed() {
    local story_id="$1"
    local phase="$2"

    if [[ ! -f "$STATE_FILE" ]]; then
        return 1
    fi

    local saved_story_id=$(jq -r '.story_id // ""' "$STATE_FILE" 2>/dev/null || echo "")
    if [[ "$saved_story_id" != "$story_id" ]]; then
        return 1
    fi

    jq -e ".completed_phases // [] | index(\"$phase\") != null" "$STATE_FILE" > /dev/null 2>&1
}

test_story_fully_completed() {
    local story_id="$1"

    if [[ ! -f "$STATE_FILE" ]]; then
        return 1
    fi

    local saved_story_id=$(jq -r '.story_id // ""' "$STATE_FILE" 2>/dev/null || echo "")
    if [[ "$saved_story_id" != "$story_id" ]]; then
        return 1
    fi

    local required_phases=("sm-cs" "tea-at" "dev-ds" "tea-ta" "tea-rv" "dev-cr" "ci" "commit")
    for phase in "${required_phases[@]}"; do
        if ! jq -e ".completed_phases // [] | index(\"$phase\") != null" "$STATE_FILE" > /dev/null 2>&1; then
            return 1
        fi
    done
    return 0
}

# =============================================================================
# Output Validation Functions
# =============================================================================

validate_agent_output() {
    local output="$1"
    local phase="$2"
    VALIDATION_REASON=""

    local menu_indicators=(
        "What would you like to do?"
        "[MH] Redisplay Menu Help"
        "[CH] Chat with the Agent"
        "[DS] Execute Dev Story"
        "[CR] Perform a thorough clean context code review"
        "[DA] Dismiss Agent"
    )

    for indicator in "${menu_indicators[@]}"; do
        if echo "$output" | grep -qF "$indicator"; then
            local has_work=false

            if [[ "$phase" == "dev-ds" ]]; then
                if echo "$output" | grep -qE "(IMPLEMENTATION COMPLETE|Files Created|Files Modified|Tests Added|Story.*complete|All.*tasks.*completed)"; then
                    has_work=true
                fi
            elif [[ "$phase" == "dev-cr" ]]; then
                if echo "$output" | grep -qEi "(ISSUES DISCOVERED|FIXES APPLIED|Review Complete|issues.*fixed|CODE REVIEW FINDINGS)"; then
                    has_work=true
                fi
            fi

            if [[ "$has_work" == false ]]; then
                VALIDATION_REASON="Agent showed interactive menu instead of executing workflow. Found: '$indicator'"
                return 1
            fi
        fi
    done

    return 0
}

# =============================================================================
# Story Detection Functions
# =============================================================================

get_next_story_id() {
    local sprint_file="$OUTPUT_DIR/implementation-artifacts/sprint-status.yaml"

    if [[ ! -f "$sprint_file" ]]; then
        echo ""
        return
    fi

    grep -E "^\s+${EPIC_NUMBER}-[0-9]+-[^:]+:\s*(backlog|ready-for-dev|in-progress|review)\s*$" "$sprint_file" | head -1 | sed -E 's/^\s+([^:]+):.*/\1/' || echo ""
}

test_story_file_exists() {
    local story_id="$1"
    local story_file="$OUTPUT_DIR/implementation-artifacts/${story_id}.md"
    [[ -f "$story_file" ]]
}

test_stories_remaining() {
    local sprint_file="$OUTPUT_DIR/implementation-artifacts/sprint-status.yaml"

    if [[ ! -f "$sprint_file" ]]; then
        log "WARN" "Sprint status file not found: $sprint_file"
        return 1
    fi

    local pending=$(grep -E "^\s+${EPIC_NUMBER}-[0-9]+-[^:]+:\s*(backlog|ready-for-dev|in-progress|review)\s*$" "$sprint_file" || true)

    if [[ -n "$pending" ]]; then
        local count=$(echo "$pending" | wc -l | tr -d ' ')
        log "INFO" "Found $count remaining stories in Epic $EPIC_NUMBER"
        return 0
    fi

    log "INFO" "No remaining stories in Epic $EPIC_NUMBER"
    return 1
}

get_remaining_stories() {
    local sprint_file="$OUTPUT_DIR/implementation-artifacts/sprint-status.yaml"

    if [[ ! -f "$sprint_file" ]]; then
        return
    fi

    grep -E "^\s+${EPIC_NUMBER}-[0-9]+-[^:]+:\s*(backlog|ready-for-dev|in-progress|review)\s*$" "$sprint_file" | sed 's/^\s*//' || true
}

confirm_story_status_done() {
    local story_id="$1"
    local sprint_file="$OUTPUT_DIR/implementation-artifacts/sprint-status.yaml"

    if grep -q "${story_id}:[[:space:]]*done" "$sprint_file" 2>/dev/null; then
        log "SUCCESS" "Story $story_id correctly marked as done in sprint-status.yaml"
        return 0
    fi

    local current_status=$(grep -oP "${story_id}:\s*\K\S+" "$sprint_file" 2>/dev/null || echo "unknown")
    log "INFO" "Story $story_id status is '$current_status' - updating to 'done'"

    if set_sprint_status_done "$story_id" "$sprint_file"; then
        log "SUCCESS" "Story $story_id now marked as done in sprint-status.yaml"
        return 0
    fi

    log "ERROR" "Failed to update sprint-status.yaml for story $story_id"
    return 1
}

# =============================================================================
# Phased Story Development
# =============================================================================
invoke_story_phased_development() {
    local story_number="$1"
    local resume_story_id="${2:-}"
    local resume_from_phase="${3:-0}"

    local story_id="$resume_story_id"
    if [[ -z "$story_id" ]]; then
        story_id=$(get_next_story_id)
    fi

    if [[ -z "$story_id" ]]; then
        log "ERROR" "Could not determine story ID"
        return 1
    fi

    # Extract story number for make ci-story (e.g., "0-4" from "0-4-web-admin-shell-with-splash-page")
    local story_num_only=$(echo "$story_id" | sed -E 's/^([0-9]+-[0-9]+).*/\1/')

    log "INFO" "Starting phased development for story #$story_number ($story_id)"

    local start_phase=1
    local is_resume="false"
    if [[ $resume_from_phase -gt 0 ]]; then
        start_phase=$resume_from_phase
        is_resume="true"
        log "INFO" "Resuming from Phase $start_phase (from saved state)"
    fi

    # Initialize per-story log file (pass resume flag to preserve existing logs)
    init_story_log "$story_id" "$is_resume"

    # =============================================================================
    # Phase 1: SM Agent - Create Story (CS)
    # =============================================================================
    if [[ $start_phase -le 1 ]]; then
        local phase1_start=$(date +%s)
        log "INFO" "[Phase 1] SM Agent: CS-Create Story for story $story_id..."
        log "INFO" "  Allowed tools: $TOOLS_SM"
        save_state "$story_number" "$story_id" "sm-cs" 0

        local prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-bmm-sm'

Step 2: Execute command: CS for story $story_id

Step 3: After completing the create story implementation, end your response with this AGENT IDENTIFICATION block:

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
Loaded files:
  - [exact path to each file you read during activation]

=== END IDENTIFICATION ===

Mode:  Automated, no menus, no questions, always Fix issues automatically, no waiting for user input."

        # Timeout retry loop for Phase 1
        local phase1_timeout_retries=0
        local max_phase1_timeout_retries=1
        local phase1_success=false

        while [[ "$phase1_success" != "true" ]]; do
            log_prompt "Phase 1 (SM:CS)" "$story_id" "$((phase1_timeout_retries + 1))" "$prompt"
            local result=""
            result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_SHORT" "$TOOLS_SM" "$prompt" "Phase1-SM:CS")
            local exit_code=$?

            log_output_preview "Phase 1 (SM:CS)" "$result"
            echo "Phase 1 full output (attempt $((phase1_timeout_retries + 1))):" >> "$STORY_LOG_FILE"
            echo "$result" >> "$STORY_LOG_FILE"

            # Handle timeout with retry
            if [[ $exit_code -eq 1 ]]; then
                ((phase1_timeout_retries++))
                log "WARN" "Phase 1 timed out after $CLAUDE_TIMEOUT_SHORT (timeout retry $phase1_timeout_retries of $max_phase1_timeout_retries)"
                echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$STORY_LOG_FILE"

                if [[ $phase1_timeout_retries -le $max_phase1_timeout_retries ]]; then
                    log "INFO" "Retrying Phase 1 due to timeout (freeze recovery)..."
                    sleep 30
                    continue
                else
                    log "ERROR" "Phase 1 timed out twice - something is wrong, stopping script"
                    exit 1
                fi
            elif [[ $exit_code -ne 0 ]]; then
                log "ERROR" "SM:CS failed (exit code: $exit_code)"
                return 1
            fi

            phase1_success=true
        done

        local phase1_seconds=$(($(date +%s) - phase1_start))
        local phase1_duration=$(format_duration $phase1_seconds)
        log "SUCCESS" "SM:CS-Create Story complete ($phase1_duration)"

        if [[ -z "$story_id" ]]; then
            story_id=$(get_next_story_id)
        fi

        complete_phase "$story_number" "$story_id" "sm-cs" "$phase1_seconds"
        sleep 5  # Delay between phases to allow Claude state reset
    fi

    # =============================================================================
    # Phase 2: TEA Agent - Accept Test (AT)
    # =============================================================================
    if [[ $start_phase -le 2 ]]; then
        local phase2_start=$(date +%s)
        log "INFO" "[Phase 2] TEA Agent: AT-Accept Test Driven Dev for story $story_id..."
        log "INFO" "  Allowed tools: $TOOLS_TEA"
        save_state "$story_number" "$story_id" "tea-at" 0

        local prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-tea-tea'

Step 2: Execute command: AT for story $story_id

Step 3: After completing the accept test workflow, end your response with this AGENT IDENTIFICATION block:

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
Loaded files:
  - [exact path to each file you read during activation]
=== END IDENTIFICATION ===

Mode:  Automated, no menus, no questions, always Fix issues automatically, no waiting for user input."

        # Timeout retry loop for Phase 2
        local phase2_timeout_retries=0
        local max_phase2_timeout_retries=1
        local phase2_success=false

        while [[ "$phase2_success" != "true" ]]; do
            log_prompt "Phase 2 (TEA:AT)" "$story_id" "$((phase2_timeout_retries + 1))" "$prompt"
            local result=""
            result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_SHORT" "$TOOLS_TEA" "$prompt" "Phase2-TEA:AT")
            local exit_code=$?

            log_output_preview "Phase 2 (TEA:AT)" "$result"
            echo "Phase 2 full output (attempt $((phase2_timeout_retries + 1))):" >> "$STORY_LOG_FILE"
            echo "$result" >> "$STORY_LOG_FILE"

            # Handle timeout with retry
            if [[ $exit_code -eq 1 ]]; then
                ((phase2_timeout_retries++))
                log "WARN" "Phase 2 timed out after $CLAUDE_TIMEOUT_SHORT (timeout retry $phase2_timeout_retries of $max_phase2_timeout_retries)"
                echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$STORY_LOG_FILE"

                if [[ $phase2_timeout_retries -le $max_phase2_timeout_retries ]]; then
                    log "INFO" "Retrying Phase 2 due to timeout (freeze recovery)..."
                    sleep 30
                    continue
                else
                    log "ERROR" "Phase 2 timed out twice - something is wrong, stopping script"
                    exit 1
                fi
            elif [[ $exit_code -ne 0 ]]; then
                log "ERROR" "TEA:AT failed (exit code: $exit_code)"
                return 1
            fi

            phase2_success=true
        done

        local phase2_seconds=$(($(date +%s) - phase2_start))
        local phase2_duration=$(format_duration $phase2_seconds)
        log "SUCCESS" "TEA:AT-Acceptance Test Driven Dev complete ($phase2_duration)"
        complete_phase "$story_number" "$story_id" "tea-at" "$phase2_seconds"
        sleep 5  # Delay between phases to allow Claude state reset
    fi

    # =============================================================================
    # Phase 3: DEV Agent - Dev Story (DS)
    # =============================================================================
    if [[ $start_phase -le 3 ]]; then
        local phase3_start=$(date +%s)
        log "INFO" "[Phase 3] DEV Agent: DS-Dev Story for story $story_id..."
        log "INFO" "  Allowed tools: $TOOLS_DEV_STORY"
        save_state "$story_number" "$story_id" "dev-ds" 0

        local prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-bmm-dev'

Step 2: Execute command: DS for story $story_id

Step 3: After completing the dev story workflow, end your response with this AGENT IDENTIFICATION block:

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
Loaded files:
  - [exact path to each file you read during activation]
=== END IDENTIFICATION ===

Mode:  Automated, no menus, no questions, always Fix issues automatically, no waiting for user input."

        local phase3_attempt=0
        local phase3_max_attempts=2
        local phase3_passed=false
        # Track timeout retries separately from validation retries
        local phase3_timeout_retries=0
        local max_phase3_timeout_retries=1

        while [[ $phase3_attempt -lt $phase3_max_attempts && "$phase3_passed" != "true" ]]; do
            ((phase3_attempt++))

            if [[ $phase3_attempt -gt 1 ]]; then
                log "WARN" "[Phase 3] Retrying DEV:DS (attempt $phase3_attempt of $phase3_max_attempts)..."
            fi

            log_prompt "Phase 3 (DEV:DS)" "$story_id" "$phase3_attempt" "$prompt"
            local result=""
            result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_LONG" "$TOOLS_DEV_STORY" "$prompt" "Phase3-DEV:DS")
            local exit_code=$?

            log_output_preview "Phase 3 (DEV:DS)" "$result"
            echo "Phase 3 full output (attempt $phase3_attempt):" >> "$STORY_LOG_FILE"
            echo "$result" >> "$STORY_LOG_FILE"

            # Handle timeout with retry
            if [[ $exit_code -eq 1 ]]; then
                ((phase3_timeout_retries++))
                log "WARN" "Phase 3 timed out after $CLAUDE_TIMEOUT_LONG (timeout retry $phase3_timeout_retries of $max_phase3_timeout_retries)"
                echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$STORY_LOG_FILE"

                if [[ $phase3_timeout_retries -le $max_phase3_timeout_retries ]]; then
                    log "INFO" "Retrying Phase 3 due to timeout (freeze recovery)..."
                    sleep 30
                    # Don't count timeout as a validation attempt
                    ((phase3_attempt--))
                    continue
                else
                    log "ERROR" "Phase 3 timed out twice - something is wrong, stopping script"
                    exit 1
                fi
            elif [[ $exit_code -ne 0 ]]; then
                log "ERROR" "DEV:DS failed (exit code: $exit_code)"
                return 1
            fi

            if validate_agent_output "$result" "dev-ds"; then
                phase3_passed=true
            else
                log "WARN" "DEV:DS validation failed: $VALIDATION_REASON"
                if [[ $phase3_attempt -lt $phase3_max_attempts ]]; then
                    sleep 5
                else
                    log "ERROR" "DEV:DS validation failed after $phase3_max_attempts attempts"
                    return 1
                fi
            fi
        done

        local phase3_seconds=$(($(date +%s) - phase3_start))
        local phase3_duration=$(format_duration $phase3_seconds)
        log "SUCCESS" "DEV:DS-Develop Story complete ($phase3_duration)"
        complete_phase "$story_number" "$story_id" "dev-ds" "$phase3_seconds"
        sleep 5  # Delay between phases to allow Claude state reset
    fi

    # =============================================================================
    # Phase 4: TEA Agent - Test Automation (TA)
    # =============================================================================
    if [[ $start_phase -le 4 ]]; then
        local phase4_start=$(date +%s)
        log "INFO" "[Phase 4] TEA Agent: TA-Test Automation for story $story_id..."
        log "INFO" "  Allowed tools: $TOOLS_TEA"
        save_state "$story_number" "$story_id" "tea-ta" 0

        local prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-tea-tea'

Step 2: Execute command: TA for story $story_id

Step 3: After completing the test automation workflow, end your response with this AGENT IDENTIFICATION block:

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
Loaded files:
  - [exact path to each file you read during activation]
=== END IDENTIFICATION ===

Mode:  Automated, no menus, no questions, always Fix issues automatically, no waiting for user input."

        # Timeout retry loop for Phase 4
        local phase4_timeout_retries=0
        local max_phase4_timeout_retries=1
        local phase4_success=false

        while [[ "$phase4_success" != "true" ]]; do
            log_prompt "Phase 4 (TEA:TA)" "$story_id" "$((phase4_timeout_retries + 1))" "$prompt"
            local result=""
            result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_MEDIUM" "$TOOLS_TEA" "$prompt" "Phase4-TEA:TA")
            local exit_code=$?

            log_output_preview "Phase 4 (TEA:TA)" "$result"
            echo "Phase 4 full output (attempt $((phase4_timeout_retries + 1))):" >> "$STORY_LOG_FILE"
            echo "$result" >> "$STORY_LOG_FILE"

            # Handle timeout with retry
            if [[ $exit_code -eq 1 ]]; then
                ((phase4_timeout_retries++))
                log "WARN" "Phase 4 timed out after $CLAUDE_TIMEOUT_SHORT (timeout retry $phase4_timeout_retries of $max_phase4_timeout_retries)"
                echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$STORY_LOG_FILE"

                if [[ $phase4_timeout_retries -le $max_phase4_timeout_retries ]]; then
                    log "INFO" "Retrying Phase 4 due to timeout (freeze recovery)..."
                    sleep 30
                    continue
                else
                    log "ERROR" "Phase 4 timed out twice - something is wrong, stopping script"
                    exit 1
                fi
            elif [[ $exit_code -ne 0 ]]; then
                log "ERROR" "TEA:TA failed (exit code: $exit_code)"
                return 1
            fi

            phase4_success=true
        done

        local phase4_seconds=$(($(date +%s) - phase4_start))
        local phase4_duration=$(format_duration $phase4_seconds)
        log "SUCCESS" "TEA:TA-Test Automation complete ($phase4_duration)"
        complete_phase "$story_number" "$story_id" "tea-ta" "$phase4_seconds"
        sleep 5  # Delay between phases to allow Claude state reset
    fi

    # =============================================================================
    # Phase 5: TEA Agent - Review (RV)
    # =============================================================================
    if [[ $start_phase -le 5 ]]; then
        local phase5_start=$(date +%s)
        log "INFO" "[Phase 5] TEA Agent: RV-Review tests for story $story_id..."
        log "INFO" "  Allowed tools: $TOOLS_TEA"
        save_state "$story_number" "$story_id" "tea-rv" 0

        local prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-tea-tea'

Step 2: Execute command: RV for story $story_id

Step 3: After completing the review test workflow, end your response with this AGENT IDENTIFICATION block:

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
Loaded files:
  - [exact path to each file you read during activation]
=== END IDENTIFICATION ===

Mode:  Automated, no menus, no questions, no waiting for user input."

        # Timeout retry loop for Phase 5
        local phase5_timeout_retries=0
        local max_phase5_timeout_retries=1
        local phase5_success=false
        local result=""

        while [[ "$phase5_success" != "true" ]]; do
            log_prompt "Phase 5 (TEA:RV)" "$story_id" "$((phase5_timeout_retries + 1))" "$prompt"
            result=""
            result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_MEDIUM" "$TOOLS_TEA" "$prompt" "Phase5-TEA:RV")
            local exit_code=$?

            log_output_preview "Phase 5 (TEA:RV)" "$result"
            echo "Phase 5 full output (attempt $((phase5_timeout_retries + 1))):" >> "$STORY_LOG_FILE"
            echo "$result" >> "$STORY_LOG_FILE"

            # Handle timeout with retry
            if [[ $exit_code -eq 1 ]]; then
                ((phase5_timeout_retries++))
                log "WARN" "Phase 5 timed out after $CLAUDE_TIMEOUT_MEDIUM (timeout retry $phase5_timeout_retries of $max_phase5_timeout_retries)"
                echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$STORY_LOG_FILE"

                if [[ $phase5_timeout_retries -le $max_phase5_timeout_retries ]]; then
                    log "INFO" "Retrying Phase 5 due to timeout (freeze recovery)..."
                    sleep 30
                    continue
                else
                    log "ERROR" "Phase 5 timed out twice - something is wrong, stopping script"
                    exit 1
                fi
            elif [[ $exit_code -ne 0 ]]; then
                log "ERROR" "TEA:RV failed (exit code: $exit_code)"
                return 1
            fi

            phase5_success=true
        done

        # Check if review file contains fixable issues and apply fixes
        # TEA agent is inconsistent with both naming AND directory placement
        # Strategy: 1) Extract path from TEA output, 2) Search multiple directories
        local review_file=""

        # Method 1: Try to extract file path from TEA's output
        # TEA typically outputs lines like "Saved to: /path/file.md" or "Review written to /path/file.md"
        # or just mentions the file path in context
        local extracted_path=$(echo "$result" | grep -oE "${OUTPUT_DIR}[^[:space:]\"'\`]*review[^[:space:]\"'\`]*\.md" | tail -1)
        if [[ -n "$extracted_path" && -f "$extracted_path" ]]; then
            review_file="$extracted_path"
            log "INFO" "Found review file from TEA output: $review_file"
        fi

        # Method 2: Search in test-reviews subdirectory (most common location)
        if [[ -z "$review_file" ]]; then
            local review_dir="$OUTPUT_DIR/test-artifacts/test-reviews"
            if [[ -d "$review_dir" ]]; then
                # Find files containing story number (review is implied by directory)
                review_file=$(ls -t "$review_dir"/*"${story_num_only}"*.md 2>/dev/null | head -1)
            fi
        fi

        # Method 3: Search in parent test-artifacts directory (TEA sometimes puts files here)
        # Files may be: test-review-story-3-11.md OR story-3-11-test-review.md
        if [[ -z "$review_file" ]]; then
            local parent_dir="$OUTPUT_DIR/test-artifacts"
            if [[ -d "$parent_dir" ]]; then
                # Try pattern: *review*{num}*.md (like test-review-story-3-11.md)
                review_file=$(ls -t "$parent_dir"/*review*"${story_num_only}"*.md 2>/dev/null | head -1)
                # Try pattern: *{num}*review*.md (like story-3-11-test-review.md)
                if [[ -z "$review_file" ]]; then
                    review_file=$(ls -t "$parent_dir"/*"${story_num_only}"*review*.md 2>/dev/null | head -1)
                fi
            fi
        fi

        # Method 4: Broad find search across _bmad-output (last resort, recently modified)
        if [[ -z "$review_file" ]]; then
            # Use find with multiple name patterns
            review_file=$(find "$OUTPUT_DIR" -type f \( -name "*review*${story_num_only}*.md" -o -name "*${story_num_only}*review*.md" \) -mmin -60 2>/dev/null | head -1)
        fi

        if [[ -n "$review_file" && -f "$review_file" ]]; then
            log "INFO" "Using review file: $review_file"
            # Check for P1/P2 issues that should be fixed (not just documented)
            # Key patterns: "Severity**: P1", "Severity**: P2", "Should Fix", "Must Fix", "Approve with Comments"
            local has_fixable_issues=false
            if grep -qE "(Severity.*P1|Severity.*P2|\*\*Must Fix\*\*|Should Fix.*P[12]|Recommendation.*Approve with Comments)" "$review_file" 2>/dev/null; then
                # Also check for specific actionable patterns (not just informational warnings)
                if grep -qE "(Unused.*import|Unused.*variable|file.*exceed|Missing.*marker|weak.*assertion|skip.*instead)" "$review_file" 2>/dev/null; then
                    has_fixable_issues=true
                fi
            fi

            if [[ "$has_fixable_issues" == "true" ]]; then
                log "INFO" "[Phase 5b] TEA:RV found issues - running fix pass..."
                log "INFO" "  Pausing 5s before fix pass (prevents skill invocation issues)..."
                sleep 5
                log "INFO" "  Allowed tools: $TOOLS_TEA_FIX"

                local fix_prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-tea-tea'

Read the test review file: $review_file

Apply fixes for ALL 'Must Fix' (Critical/P1) and 'Should Fix' (P2) issues listed in the review.

Common fixes needed:
- Unused imports/variables: Remove them
- Missing priority markers: Add @pytest.mark.p0/p1/p2 decorators
- Weak assertions (early return on empty): Replace with pytest.skip() or explicit assert
- Test file too long: Consider noting but don't split unless critical

For each fix applied, output:
=== FIX APPLIED ===
File: [filepath]
Issue: [brief description]
Fix: [what was changed]
=== END FIX ===

After all fixes are complete, run: pytest --collect-only -q to verify tests still load.

End your response with this AGENT IDENTIFICATION block:

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
Loaded files:
  - [exact path to each file you read during activation]
=== END IDENTIFICATION ===

Mode: Automated, no menus, apply fixes directly, no waiting for user input."

                # Timeout retry loop for Phase 5b
                local phase5b_timeout_retries=0
                local max_phase5b_timeout_retries=1
                local phase5b_success=false

                while [[ "$phase5b_success" != "true" ]]; do
                    log_prompt "Phase 5b (TEA:RV-FIX)" "$story_id" "$((phase5b_timeout_retries + 1))" "$fix_prompt"
                    local fix_result=""
                    fix_result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_MEDIUM" "$TOOLS_TEA_FIX" "$fix_prompt" "Phase5b-TEA:RV-FIX")
                    local fix_exit_code=$?

                    log_output_preview "Phase 5b (TEA:RV-FIX)" "$fix_result"
                    echo "Phase 5b (fix pass) full output (attempt $((phase5b_timeout_retries + 1))):" >> "$STORY_LOG_FILE"
                    echo "$fix_result" >> "$STORY_LOG_FILE"

                    # Handle timeout with retry
                    if [[ $fix_exit_code -eq 1 ]]; then
                        ((phase5b_timeout_retries++))
                        log "WARN" "Phase 5b timed out after $CLAUDE_TIMEOUT_MEDIUM (timeout retry $phase5b_timeout_retries of $max_phase5b_timeout_retries)"
                        echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$STORY_LOG_FILE"

                        if [[ $phase5b_timeout_retries -le $max_phase5b_timeout_retries ]]; then
                            log "INFO" "Retrying Phase 5b due to timeout (freeze recovery)..."
                            sleep 30
                            continue
                        else
                            log "ERROR" "Phase 5b timed out twice - something is wrong, stopping script"
                            exit 1
                        fi
                    elif [[ $fix_exit_code -ne 0 ]]; then
                        log "WARN" "TEA:RV fix pass had issues (exit code: $fix_exit_code) - continuing anyway"
                    else
                        log "SUCCESS" "TEA:RV fix pass completed"
                    fi

                    phase5b_success=true
                done
            else
                log "INFO" "TEA:RV review found no P1/P2 issues requiring code fixes"
            fi
        else
            log "INFO" "No review file found for $story_id - skipping fix pass"
        fi

        local phase5_seconds=$(($(date +%s) - phase5_start))
        local phase5_duration=$(format_duration $phase5_seconds)
        log "SUCCESS" "TEA:RV-Review tests complete ($phase5_duration)"
        complete_phase "$story_number" "$story_id" "tea-rv" "$phase5_seconds"
        sleep 5  # Delay between phases to allow Claude state reset
    fi

    # =============================================================================
    # Phase 6: DEV Agent - Code Review (CR)
    # =============================================================================
    if [[ $start_phase -le 6 ]]; then
        local phase6_start=$(date +%s)
        log "INFO" "[Phase 6] DEV Agent: CR-Code Review for story $story_id..."
        log "INFO" "  Allowed tools: $TOOLS_CODE_REVIEW"
        save_state "$story_number" "$story_id" "dev-cr" 0

        local prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-bmm-dev'

Step 2: Execute command: CR for story $story_id

Step 3: When the code review workflow asks 'What should I do with these issues?', automatically choose option 1 (Fix them automatically) without waiting for user input.

Mode:  Automated - always choose option 1 (Fix automatically) when asked, no waiting for user input.

Step 4: After completing the code review workflow, end your response with this AGENT IDENTIFICATION block:

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
Loaded files:
  - [exact path to each file you read during activation]
=== END IDENTIFICATION ===
"

        local phase6_attempt=0
        local phase6_max_attempts=2
        local phase6_passed=false
        # Track timeout retries separately from validation retries
        local phase6_timeout_retries=0
        local max_phase6_timeout_retries=1

        while [[ $phase6_attempt -lt $phase6_max_attempts && "$phase6_passed" != "true" ]]; do
            ((phase6_attempt++))

            if [[ $phase6_attempt -gt 1 ]]; then
                log "WARN" "[Phase 6] Retrying DEV:CR (attempt $phase6_attempt of $phase6_max_attempts)..."
            fi

            log_prompt "Phase 6 (DEV:CR)" "$story_id" "$phase6_attempt" "$prompt"
            local result=""
            result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_MEDIUM" "$TOOLS_CODE_REVIEW" "$prompt" "Phase6-DEV:CR")
            local exit_code=$?

            log_output_preview "Phase 6 (DEV:CR)" "$result"
            echo "Phase 6 full output (attempt $phase6_attempt):" >> "$STORY_LOG_FILE"
            echo "$result" >> "$STORY_LOG_FILE"

            # Save code review output
            local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
            cat >> "$CODE_REVIEW_LOG" << EOF

================================================================================
CODE REVIEW: Story $story_id (attempt $phase6_attempt)
Date: $timestamp
================================================================================
EOF
            echo "$result" | tail -100 >> "$CODE_REVIEW_LOG"

            # Handle timeout with retry
            if [[ $exit_code -eq 1 ]]; then
                ((phase6_timeout_retries++))
                log "WARN" "Phase 6 timed out after $CLAUDE_TIMEOUT_MEDIUM (timeout retry $phase6_timeout_retries of $max_phase6_timeout_retries)"
                echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$STORY_LOG_FILE"

                if [[ $phase6_timeout_retries -le $max_phase6_timeout_retries ]]; then
                    log "INFO" "Retrying Phase 6 due to timeout (freeze recovery)..."
                    sleep 30
                    # Don't count timeout as a validation attempt
                    ((phase6_attempt--))
                    continue
                else
                    log "ERROR" "Phase 6 timed out twice - something is wrong, stopping script"
                    exit 1
                fi
            elif [[ $exit_code -ne 0 ]]; then
                log "ERROR" "DEV:CR failed (exit code: $exit_code)"
                return 1
            fi

            if validate_agent_output "$result" "dev-cr"; then
                phase6_passed=true
            else
                log "WARN" "DEV:CR validation failed: $VALIDATION_REASON"
                if [[ $phase6_attempt -lt $phase6_max_attempts ]]; then
                    sleep 5
                else
                    log "ERROR" "DEV:CR validation failed after $phase6_max_attempts attempts"
                    return 1
                fi
            fi
        done

        local phase6_seconds=$(($(date +%s) - phase6_start))
        local phase6_duration=$(format_duration $phase6_seconds)
        log "SUCCESS" "DEV:CR-Code Review complete ($phase6_duration)"
        complete_phase "$story_number" "$story_id" "dev-cr" "$phase6_seconds"
        sleep 5  # Delay between phases to allow Claude state reset
    fi

    # =============================================================================
    # Phase 7: CI (make ci-story STORY=X-X)
    # =============================================================================
    local phase7_start=$(date +%s)
    log "INFO" "[Phase 7] Running CI: make ci-story STORY=$story_num_only..."
    save_state "$story_number" "$story_id" "ci" 0

    cd "$PROJECT_ROOT"

    # Pre-CI check: Verify migrations are up to date (fail fast before slow CI)
    log "INFO" "Pre-CI check: Verifying Django migrations..."
    local migration_precheck
    migration_precheck=$(cd "$PROJECT_ROOT/backend" && python manage.py makemigrations --check --dry-run 2>&1) || {
        log "WARN" "Pre-CI migration check failed - creating missing migrations..."
        (cd "$PROJECT_ROOT/backend" && python manage.py makemigrations 2>&1) | tee -a "$LOG_FILE"
        log "INFO" "Migrations created - adding to staging area"
        git add backend/*/migrations/*.py 2>/dev/null || true
    }

    # Ensure we're in project root for CI commands
    cd "$PROJECT_ROOT"

    local ci_passed=false
    local ci_attempt=0
    # Track timeout retries separately - timeouts are freeze recovery, not fix failures
    local ci_timeout_retries=0
    local max_ci_timeout_retries=1  # Only 1 timeout retry allowed

    while [[ $ci_attempt -lt $MAX_CI_ATTEMPTS && "$ci_passed" != "true" ]]; do
        ((ci_attempt++))
        save_state "$story_number" "$story_id" "ci" "$ci_attempt"
        log "INFO" "CI attempt $ci_attempt of $MAX_CI_ATTEMPTS"

        local ci_result=""
        local ci_exit_code=0

        ci_result=$(make ci-story STORY="$story_num_only" 2>&1) || ci_exit_code=$?

        if [[ $ci_exit_code -eq 0 ]]; then
            ci_passed=true
            local phase7_duration=$(format_duration $(($(date +%s) - phase7_start)))
            log "SUCCESS" "CI passed! ($phase7_duration)"
        else
            log "WARN" "CI failed (exit code: $ci_exit_code), asking Claude to fix..."
            log "INFO" "  Allowed tools for fix: $TOOLS_CI_FIX"

            # Log CI issues
            local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
            cat >> "$CODE_REVIEW_LOG" << EOF

================================================================================
CI FAILURE: Story $story_id - Attempt $ci_attempt of $MAX_CI_ATTEMPTS
Date: $timestamp
================================================================================
EOF
            echo "$ci_result" | tail -200 >> "$CODE_REVIEW_LOG"

            # Add error summary for quick diagnosis
            echo "" >> "$CODE_REVIEW_LOG"
            echo "=== ERROR SUMMARY (unique errors) ===" >> "$CODE_REVIEW_LOG"
            echo "$ci_result" | grep -E "(ERROR|FATAL|FAILED|error:)" | sort -u | head -20 >> "$CODE_REVIEW_LOG"
            echo "=== END ERROR SUMMARY ===" >> "$CODE_REVIEW_LOG"

            # Write CI issues to temp file (preserved per attempt)
            local ci_issues_file="$LOOPER_DIR/epic${EPIC_NUMBER}-ci-issues-attempt-${ci_attempt}.txt"
            echo "$ci_result" > "$ci_issues_file"
            # Also write to generic temp file for dev agent
            echo "$ci_result" > "$LOOPER_DIR/ci-issues-temp.txt"

            local fix_prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-bmm-dev'

Step 2: Fix CI failures

CI failed for story $story_id. Read the CI issues from: $ci_issues_file

Fix all lint errors (ruff), type errors (mypy), security issues (bandit), and test failures.

CRITICAL - STALE VITE SERVER: If E2E browser tests fail (Playwright timeouts, wrong URL params, missing elements), the Vite dev server may be serving stale code (known WSL2/DevContainer HMR issue). Before re-running E2E tests, kill and restart Vite:
  pkill -f 'node.*vite' || true; sleep 2
  cd /workspace/web && npx vite --host 0.0.0.0 --port 5173 >/dev/null 2>&1 &
  sleep 5  # Wait for Vite to start

IMPORTANT: After fixing, output a structured summary using this EXACT format:

=== CI FIXES APPLIED ===
- [LINT/TEST/TYPE/SECURITY] Brief description of the fix (file:line if applicable)
...
=== END CI FIXES ===

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
=== END IDENTIFICATION ===
"

            log_prompt "Phase 7 (ci-fix)" "$story_id" "$ci_attempt" "$fix_prompt"
            local fix_result=""
            fix_result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_LONG" "$TOOLS_CI_FIX" "$fix_prompt" "Phase7-CI-FIX")
            local fix_exit_code=$?

            log_output_preview "Phase 7 (ci-fix)" "$fix_result"

            # Log full dev agent output to story log file
            echo "" >> "$STORY_LOG_FILE"
            echo "=== FULL DEV AGENT OUTPUT (Attempt $ci_attempt) ===" >> "$STORY_LOG_FILE"
            echo "$fix_result" >> "$STORY_LOG_FILE"
            echo "=== END DEV AGENT OUTPUT ===" >> "$STORY_LOG_FILE"

            # Handle timeout with retry (timeout = freeze, not fix failure)
            if [[ $fix_exit_code -eq 1 ]]; then
                ((ci_timeout_retries++))
                log "WARN" "CI fix timed out after $CLAUDE_TIMEOUT_LONG (timeout retry $ci_timeout_retries of $max_ci_timeout_retries)"
                echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$STORY_LOG_FILE"

                if [[ $ci_timeout_retries -le $max_ci_timeout_retries ]]; then
                    log "INFO" "Retrying CI fix due to timeout (freeze recovery)..."
                    # Don't count timeout against regular CI attempts
                    ((ci_attempt--))
                    sleep 30
                    continue
                else
                    log "ERROR" "CI fix timed out twice - something is wrong, stopping script"
                    exit 1
                fi
            fi

            # Also log CI fixes to code review log if present
            if echo "$fix_result" | grep -q "=== CI FIXES APPLIED ==="; then
                echo "$fix_result" | sed -n '/=== CI FIXES APPLIED ===/,/=== END CI FIXES ===/p' >> "$CODE_REVIEW_LOG"
            fi
        fi
    done

    # If CI still hasn't passed but we applied fixes on the last attempt,
    # run one more verification CI to check if the fixes worked
    if [[ "$ci_passed" != "true" && $ci_attempt -eq $MAX_CI_ATTEMPTS ]]; then
        log "INFO" "Running verification CI after final fix attempt..."

        ci_exit_code=0
        ci_result=$(make ci-story STORY="$story_num_only" 2>&1) || ci_exit_code=$?

        if [[ $ci_exit_code -eq 0 ]]; then
            ci_passed=true
            local phase7_duration=$(format_duration $(($(date +%s) - phase7_start)))
            log "SUCCESS" "CI passed on verification run! ($phase7_duration)"
        else
            log "ERROR" "CI still failing after verification run"
            # Save the final CI output for debugging
            echo "$ci_result" > "$LOOPER_DIR/epic${EPIC_NUMBER}-ci-issues-verification.txt"
        fi
    fi

    if [[ "$ci_passed" != "true" ]]; then
        log "ERROR" "CI failed after $MAX_CI_ATTEMPTS attempts (plus verification)"
        return 1
    fi

    local phase7_seconds=$(($(date +%s) - phase7_start))
    complete_phase "$story_number" "$story_id" "ci" "$phase7_seconds"

    # =============================================================================
    # Phase 8: Local Commit (REQUIRED - failure stops story)
    # =============================================================================
    local phase8_start=$(date +%s)
    log "INFO" "[Phase 8] Creating local commit..."
    save_state "$story_number" "$story_id" "commit" 0

    # Update sprint status to done
    if ! confirm_story_status_done "$story_id"; then
        log "WARN" "Could not update sprint status - continuing anyway"
    fi

    # Create local commit (will auto-retry if pre-commit hooks modify files)
    if git_commit_story "$story_id"; then
        local phase8_seconds=$(($(date +%s) - phase8_start))
        log "SUCCESS" "[Phase 8] Local commit completed successfully"
        complete_phase "$story_number" "$story_id" "commit" "$phase8_seconds"
    else
        log "ERROR" "[Phase 8] Commit FAILED - story cannot be marked complete"
        log "ERROR" "Check 'git status' and resolve issues before resuming"
        log "INFO" "Common issues: missing migrations, ruff errors not auto-fixed, merge conflicts"
        return 1
    fi

    # Write completion footer to story log
    local end_timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    cat >> "$STORY_LOG_FILE" << EOF

================================================================================
STORY COMPLETED: $story_id
Finished: $end_timestamp
================================================================================
EOF

    return 0
}

# =============================================================================
# Check Dependencies
# =============================================================================
check_dependencies() {
    # Check Claude CLI
    if ! command -v claude &> /dev/null; then
        log "ERROR" "Claude CLI not found. Install it first."
        exit 1
    fi
    log "INFO" "Claude CLI found: $(claude --version 2>&1 | head -1)"

    # Check Python
    if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
        log "ERROR" "Python not found. Please install Python 3.14+."
        exit 1
    fi
    log "INFO" "Python found: $(python --version 2>&1 || python3 --version 2>&1)"

    # Check pytest
    if ! command -v pytest &> /dev/null; then
        log "WARN" "pytest not found directly - will use via make commands"
    else
        log "INFO" "pytest found: $(pytest --version 2>&1 | head -1)"
    fi

    # Check git
    if ! command -v git &> /dev/null; then
        log "ERROR" "Git not found. Please install git."
        exit 1
    fi
    log "INFO" "Git found: $(git --version)"

    # Check jq (required for JSON parsing)
    if ! command -v jq &> /dev/null; then
        log "ERROR" "jq not found. Please install jq for JSON parsing."
        exit 1
    fi
    log "INFO" "jq found: $(jq --version)"

    # Check make
    if ! command -v make &> /dev/null; then
        log "ERROR" "make not found. Please install make."
        exit 1
    fi
    log "INFO" "make found"

    # Check ruff (optional - part of CI)
    if command -v ruff &> /dev/null; then
        log "INFO" "ruff found: $(ruff --version 2>&1)"
    else
        log "WARN" "ruff not found directly - will use via make commands"
    fi

    # Check Docker (optional)
    if command -v docker &> /dev/null; then
        log "INFO" "Docker found: $(docker --version 2>&1)"
    else
        log "WARN" "Docker not found. Some services may not be available."
    fi
}

# =============================================================================
# Main Processing Loop
# =============================================================================
start_epic_processing() {
    echo ""
    echo -e "  ${MAGENTA}=====================================${NC}"
    echo -e "  ${MAGENTA}BUILD LOOP${NC}"
    echo -e "  ${MAGENTA}PetCompass Automated Development${NC}"
    echo -e "  ${MAGENTA}=====================================${NC}"
    echo ""
    echo -e "  ${GREEN}Security: Using scoped --allowedTools${NC}"
    echo -e "  ${GREEN}(No --dangerously-skip-permissions)${NC}"
    echo ""

    log "INFO" "========================================"
    log "INFO" "Starting Build Loop for Epic $EPIC_NUMBER"
    log "INFO" "========================================"
    log "INFO" "Max iterations per phase: $MAX_ITERATIONS_PER_PHASE"
    log "INFO" "Max CI attempts: $MAX_CI_ATTEMPTS"
    log "INFO" "Press Ctrl+C to stop gracefully"
    echo ""

    # Check for saved state to resume
    local resume_story_id=""
    local resume_from_phase=0
    local resume_story_number=0

    if [[ -f "$STATE_FILE" ]]; then
        local saved_epic=$(jq -r '.epic // 0' "$STATE_FILE" 2>/dev/null || echo "0")
        local saved_story_id=$(jq -r '.story_id // ""' "$STATE_FILE" 2>/dev/null || echo "")

        if [[ "$saved_epic" == "$EPIC_NUMBER" && -n "$saved_story_id" ]]; then
            if ! test_story_fully_completed "$saved_story_id"; then
                local all_phases=("sm-cs" "tea-at" "dev-ds" "tea-ta" "tea-rv" "dev-cr" "ci" "commit")

                for i in "${!all_phases[@]}"; do
                    local phase="${all_phases[$i]}"
                    if ! jq -e ".completed_phases // [] | index(\"$phase\") != null" "$STATE_FILE" > /dev/null 2>&1; then
                        resume_story_id="$saved_story_id"
                        resume_from_phase=$((i + 1))
                        resume_story_number=$(jq -r '.current_story // 0' "$STATE_FILE" 2>/dev/null || echo "0")

                        local completed_phases=$(jq -r '.completed_phases // [] | join(", ")' "$STATE_FILE" 2>/dev/null || echo "(none)")
                        [[ -z "$completed_phases" ]] && completed_phases="(none)"

                        echo ""
                        echo -e "  ${YELLOW}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${NC}"
                        echo -e "  ${YELLOW}!!!  RESUMING INCOMPLETE STORY  !!!${NC}"
                        echo -e "  ${YELLOW}!!!  Story: $resume_story_id${NC}"
                        echo -e "  ${YELLOW}!!!  Completed phases: $completed_phases${NC}"
                        echo -e "  ${YELLOW}!!!  Resuming from: $phase (Phase $resume_from_phase)${NC}"
                        echo -e "  ${YELLOW}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${NC}"
                        echo ""

                        log "INFO" "Resuming story $resume_story_id from phase $phase"
                        break
                    fi
                done
            else
                log "INFO" "Saved state story $saved_story_id is fully completed, checking for more stories..."
            fi
        fi
    fi

    # Show remaining stories
    local remaining_stories=$(get_remaining_stories)

    if [[ -n "$resume_story_id" ]]; then
        log "INFO" "Incomplete story detected from saved state: $resume_story_id"
    elif [[ -n "$remaining_stories" ]]; then
        log "INFO" "Remaining stories to process:"
        echo "$remaining_stories" | while read -r story; do
            echo -e "  - $story"
        done
        echo ""
    else
        log "INFO" "No stories remaining in Epic $EPIC_NUMBER. Nothing to do."
        return
    fi

    local story_count=0

    # If resuming, process the resumed story first
    if [[ -n "$resume_story_id" ]]; then
        story_count=$resume_story_number
        echo ""
        log "INFO" "==========================================="
        log "INFO" "Resuming Story #$story_count ($resume_story_id)"
        log "INFO" "==========================================="

        if ! invoke_story_phased_development "$story_count" "$resume_story_id" "$resume_from_phase"; then
            log "ERROR" "Story #$story_count failed. Pausing for human review."
            log "INFO" "Resume with: ./looper/build-loop.sh $EPIC_NUMBER"
            return 1
        fi

        log "SUCCESS" "Story #$story_count completed!"
        echo ""
        echo "Pausing 10 seconds before next story..."
        sleep 10
    fi

    while test_stories_remaining; do
        ((++story_count))
        echo ""
        log "INFO" "==========================================="
        log "INFO" "Story #$story_count"
        log "INFO" "==========================================="

        if ! invoke_story_phased_development "$story_count"; then
            log "ERROR" "Story #$story_count failed. Pausing for human review."
            log "INFO" "Resume with: ./looper/build-loop.sh $EPIC_NUMBER"
            return 1
        fi

        log "SUCCESS" "Story #$story_count completed!"
        echo ""
        echo "Pausing 10 seconds before next story..."
        sleep 10
    done

    # =============================================================================
    # Final Step: Full CI Pipeline (with retry loop)
    # =============================================================================
    echo ""
    log "INFO" "==========================================="
    log "INFO" "Final Step: Running full CI pipeline (make ci)"
    log "INFO" "==========================================="
    log "INFO" "Max attempts: $MAX_CI_ATTEMPTS"

    cd "$PROJECT_ROOT"
    local final_ci_start=$(date +%s)
    local final_ci_passed=false
    local final_ci_attempt=0
    # Track timeout retries separately - timeouts are freeze recovery, not fix failures
    local final_ci_timeout_retries=0
    local max_final_ci_timeout_retries=1  # Only 1 timeout retry allowed

    while [[ $final_ci_attempt -lt $MAX_CI_ATTEMPTS && "$final_ci_passed" != "true" ]]; do
        ((final_ci_attempt++))
        log "INFO" "Final CI attempt $final_ci_attempt of $MAX_CI_ATTEMPTS"

        local final_ci_result=""
        local final_ci_exit_code=0

        final_ci_result=$(make ci 2>&1) || final_ci_exit_code=$?

        # Also append to log file
        echo "$final_ci_result" >> "$LOG_FILE"

        if [[ $final_ci_exit_code -eq 0 ]]; then
            final_ci_passed=true
            local final_ci_duration=$(format_duration $(($(date +%s) - final_ci_start)))
            log "SUCCESS" "Full CI pipeline passed! ($final_ci_duration)"
        else
            log "WARN" "Final CI failed (exit code: $final_ci_exit_code), asking Claude to fix..."

            # Show summary of failures
            echo ""
            echo -e "${RED}=== FINAL CI FAILURE SUMMARY ===${NC}"

            # Extract test failures
            local test_failures=$(echo "$final_ci_result" | grep -E "^FAILED " | head -10)
            if [[ -n "$test_failures" ]]; then
                echo -e "${YELLOW}Test Failures (pytest):${NC}"
                echo "$test_failures" | while read -r line; do
                    echo "  - $line"
                done
                local test_count
                test_count=$(echo "$final_ci_result" | grep -cE "^FAILED ") || test_count=0
                if [[ $test_count -gt 10 ]]; then
                    echo "  ... and $((test_count - 10)) more"
                fi
                echo ""
            fi

            # Extract lint errors
            local ruff_errors=$(echo "$final_ci_result" | grep -E "^(backend|apps|tests)/.*:[0-9]+:[0-9]+:" | head -10)
            if [[ -n "$ruff_errors" ]]; then
                echo -e "${YELLOW}Lint Errors (ruff):${NC}"
                echo "$ruff_errors" | while read -r line; do
                    echo "  - $line"
                done
                echo ""
            fi

            # Extract type errors
            local mypy_errors=$(echo "$final_ci_result" | grep -E "^(backend|apps|tests)/.*: error:" | head -10)
            if [[ -n "$mypy_errors" ]]; then
                echo -e "${YELLOW}Type Errors (mypy):${NC}"
                echo "$mypy_errors" | while read -r line; do
                    echo "  - $line"
                done
                echo ""
            fi

            # Extract make errors
            local make_errors=$(echo "$final_ci_result" | grep -E "^make(\[[0-9]+\])?: \*\*\*" | head -5)
            if [[ -n "$make_errors" ]]; then
                echo -e "${YELLOW}Make Errors:${NC}"
                echo "$make_errors" | while read -r line; do
                    echo "  - $line"
                done
                echo ""
            fi

            echo -e "${RED}=== END FAILURE SUMMARY ===${NC}"
            echo ""

            log "INFO" "  Allowed tools for fix: $TOOLS_CI_FIX"

            # Log CI issues
            local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
            cat >> "$CODE_REVIEW_LOG" << EOF

================================================================================
FINAL CI FAILURE - Attempt $final_ci_attempt of $MAX_CI_ATTEMPTS
Date: $timestamp
================================================================================
EOF
            echo "$final_ci_result" | tail -200 >> "$CODE_REVIEW_LOG"

            # Write CI issues to temp file
            local final_ci_issues_file="$LOOPER_DIR/epic${EPIC_NUMBER}-final-ci-issues-attempt-${final_ci_attempt}.txt"
            echo "$final_ci_result" > "$final_ci_issues_file"
            echo "$final_ci_result" > "$LOOPER_DIR/ci-issues-temp.txt"

            local fix_prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-bmm-dev'

Step 2: Fix CI failures

The full CI pipeline (make ci) failed. Read the CI issues from: $final_ci_issues_file

Fix all lint errors (ruff), type errors (mypy), security issues (bandit), and test failures.

CRITICAL - STALE VITE SERVER: If E2E browser tests fail (Playwright timeouts, wrong URL params, missing elements), the Vite dev server may be serving stale code (known WSL2/DevContainer HMR issue). Before re-running E2E tests, kill and restart Vite:
  pkill -f 'node.*vite' || true; sleep 2
  cd /workspace/web && npx vite --host 0.0.0.0 --port 5173 >/dev/null 2>&1 &
  sleep 5  # Wait for Vite to start

IMPORTANT: After fixing, output a structured summary using this EXACT format:

=== CI FIXES APPLIED ===
- [LINT/TEST/TYPE/SECURITY] Brief description of the fix (file:line if applicable)
...
=== END CI FIXES ===

=== AGENT IDENTIFICATION ===
Agent: [Your agent type, e.g., DEV Agent]
Persona: [Your persona name from the agent file]
=== END IDENTIFICATION ===
"

            log "INFO" "Pausing 15 seconds before invoking Claude to fix CI issues..."
            sleep 15
            log "INFO" "Invoking DEV agent to fix CI issues..."
            local fix_result=""
            fix_result=$(invoke_claude_with_timeout "$CLAUDE_TIMEOUT_LONG" "$TOOLS_CI_FIX" "$fix_prompt" "FinalCI-FIX")
            local fix_exit_code=$?

            log_output_preview "Final CI Fix" "$fix_result"

            # Log full dev agent output
            echo "" >> "$LOG_FILE"
            echo "=== FULL DEV AGENT OUTPUT (Final CI Attempt $final_ci_attempt) ===" >> "$LOG_FILE"
            echo "$fix_result" >> "$LOG_FILE"
            echo "=== END DEV AGENT OUTPUT ===" >> "$LOG_FILE"

            # Handle timeout with retry (timeout = freeze, not fix failure)
            if [[ $fix_exit_code -eq 1 ]]; then
                ((final_ci_timeout_retries++))
                log "WARN" "Final CI fix timed out after $CLAUDE_TIMEOUT_LONG (timeout retry $final_ci_timeout_retries of $max_final_ci_timeout_retries)"
                echo "TIMEOUT at $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"

                if [[ $final_ci_timeout_retries -le $max_final_ci_timeout_retries ]]; then
                    log "INFO" "Retrying Final CI fix due to timeout (freeze recovery)..."
                    # Don't count timeout against regular CI attempts
                    ((final_ci_attempt--))
                    sleep 30
                    continue
                else
                    log "ERROR" "Final CI fix timed out twice - something is wrong, stopping script"
                    exit 1
                fi
            fi

            # Also log CI fixes to code review log if present
            if echo "$fix_result" | grep -q "=== CI FIXES APPLIED ==="; then
                echo "$fix_result" | sed -n '/=== CI FIXES APPLIED ===/,/=== END CI FIXES ===/p' >> "$CODE_REVIEW_LOG"
            fi
        fi
    done

    # If CI still hasn't passed but we applied fixes on the last attempt,
    # run one more verification CI to check if the fixes worked
    if [[ "$final_ci_passed" != "true" && $final_ci_attempt -eq $MAX_CI_ATTEMPTS ]]; then
        log "INFO" "Running verification CI after final fix attempt..."

        final_ci_exit_code=0
        final_ci_result=$(make ci 2>&1) || final_ci_exit_code=$?

        if [[ $final_ci_exit_code -eq 0 ]]; then
            final_ci_passed=true
            local final_ci_duration=$(format_duration $(($(date +%s) - final_ci_start)))
            log "SUCCESS" "Full CI passed on verification run! ($final_ci_duration)"
        else
            log "ERROR" "Full CI still failing after verification run"
            # Save the final CI output for debugging
            echo "$final_ci_result" > "$LOOPER_DIR/epic${EPIC_NUMBER}-final-ci-issues-verification.txt"
        fi
    fi

    if [[ "$final_ci_passed" != "true" ]]; then
        local final_ci_duration=$(format_duration $(($(date +%s) - final_ci_start)))
        log "ERROR" "Full CI pipeline failed after $final_ci_duration"
        log "ERROR" "All stories completed but final CI check failed after $MAX_CI_ATTEMPTS attempts. Please investigate."
        return 1
    fi

    # Print epic summary table with durations
    print_epic_summary

    echo ""
    log "SUCCESS" "========================================"
    log "SUCCESS" "Epic $EPIC_NUMBER completed!"
    log "SUCCESS" "Total stories processed: $story_count"
    log "SUCCESS" "========================================"
}

# =============================================================================
# Main Entry Point
# =============================================================================
main() {
    echo ""
    echo -e "  ${MAGENTA}=====================================${NC}"
    echo -e "  ${MAGENTA}BUILD LOOP${NC}"
    echo -e "  ${MAGENTA}PetCompass Automated Development${NC}"
    echo -e "  ${MAGENTA}=====================================${NC}"
    echo ""

    if [[ -z "$EPIC_INPUT" ]]; then
        echo "Usage: ./looper/build-loop.sh <epic-number>[,<epic-number>,...]"
        echo "Examples:"
        echo "  ./looper/build-loop.sh 5        # Process Epic 5"
        echo "  ./looper/build-loop.sh 5,6      # Process Epic 5, then Epic 6"
        echo "  ./looper/build-loop.sh 5,6,7    # Process Epics 5, 6, and 7"
        exit 1
    fi

    check_dependencies

    # Parse comma-separated epic numbers into array
    IFS=',' read -ra EPIC_ARRAY <<< "$EPIC_INPUT"
    local total_epics=${#EPIC_ARRAY[@]}
    local epic_index=0
    local failed_epics=()

    if [[ $total_epics -gt 1 ]]; then
        echo -e "  ${GREEN}Processing $total_epics epics: ${EPIC_ARRAY[*]}${NC}"
        echo ""
    fi

    for epic in "${EPIC_ARRAY[@]}"; do
        ((++epic_index))  # Pre-increment to avoid exit code 1 when epic_index=0

        # Trim whitespace from epic number
        epic=$(echo "$epic" | tr -d '[:space:]')

        # Validate epic is a number
        if ! [[ "$epic" =~ ^[0-9]+$ ]]; then
            echo -e "${RED}Error: Invalid epic number '$epic' - must be a number${NC}"
            continue
        fi

        # Setup paths for this epic
        setup_epic_paths "$epic"

        if [[ $total_epics -gt 1 ]]; then
            echo ""
            echo -e "  ${MAGENTA}=====================================${NC}"
            echo -e "  ${MAGENTA}EPIC $epic ($epic_index of $total_epics)${NC}"
            echo -e "  ${MAGENTA}=====================================${NC}"
            echo ""
        fi

        # Process this epic
        if start_epic_processing; then
            echo ""
            if [[ $total_epics -gt 1 ]]; then
                log "SUCCESS" "Epic $epic completed successfully ($epic_index of $total_epics)"
            fi
        else
            echo ""
            log "ERROR" "Epic $epic failed ($epic_index of $total_epics)"
            if [[ $total_epics -gt 1 && $epic_index -lt $total_epics ]]; then
                log "ERROR" "Stopping - remaining epics will not be processed"
            fi
            exit 1
        fi

        # Pause between epics if processing multiple
        if [[ $total_epics -gt 1 && $epic_index -lt $total_epics ]]; then
            echo ""
            log "INFO" "Pausing 30 seconds before next epic..."
            sleep 30
        fi
    done

    # Summary for multiple epics (only reached if all succeeded)
    if [[ $total_epics -gt 1 ]]; then
        echo ""
        echo -e "  ${MAGENTA}=====================================${NC}"
        echo -e "  ${MAGENTA}MULTI-EPIC SUMMARY${NC}"
        echo -e "  ${MAGENTA}=====================================${NC}"
        echo ""
        echo -e "  ${GREEN}All $total_epics epics completed successfully!${NC}"
    fi
}

main "$@"
