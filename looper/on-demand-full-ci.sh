#!/bin/bash
#
# on-demand-full-ci - Run full CI pipeline with automatic fix attempts
#
# Runs `make ci` and if errors are found, asks Claude to fix them.
# Retries up to MAX_CI_ATTEMPTS times.
#
# Usage: ./looper/on-demand-full-ci.sh
#
# Stop: Ctrl+C (graceful shutdown)
#

set -e

# =============================================================================
# Configuration
# =============================================================================
MAX_CI_ATTEMPTS=4

# Timezone for timestamps (Mountain Time - Denver)
export TZ="America/Denver"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="$PROJECT_ROOT/_bmad-output"
LOOPER_DIR="$PROJECT_ROOT/looper"
LOG_FILE="$LOOPER_DIR/on-demand-full-ci.log"

# =============================================================================
# SCOPED PERMISSIONS - Tools needed for CI fixes
# =============================================================================
TOOLS_CI_FIX="Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pip *),Bash(pytest *),Bash(make *),Bash(ruff *),Bash(mypy *),Bash(bandit *),Skill"

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

# =============================================================================
# Database Connection Reset
# =============================================================================
# Terminates stale PostgreSQL connections to prevent "too many clients" errors.
# Called before make ci and Claude invocations since they run tests.
# Uses docker exec to bypass connection limits when pool is exhausted.
# =============================================================================
reset_db_connections() {
    local DB_CONTAINER="${DB_CONTAINER:-petcompass_db}"
    local DB_USER="${DB_USER:-petcompass}"

    echo -e "${CYAN}[DB] Resetting idle database connections...${NC}"

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
    " 2>/dev/null | xargs || echo "0")

    echo -e "${CYAN}[DB] Terminated ${reset_result:-0} idle connections${NC}"

    # Pause to let connections fully close
    sleep 1
}

# =============================================================================
# Logging function
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

    echo "${timestamp} [${level}] ${message}" >> "$LOG_FILE"
}

# =============================================================================
# Output preview function
# =============================================================================
log_output_preview() {
    local phase="$1"
    local output="$2"
    local lines="${3:-5}"

    local preview=$(echo "$output" | head -n "$lines")

    cat >> "$LOG_FILE" << EOF

--- OUTPUT PREVIEW: $phase (first $lines lines) ---
$preview
--- END PREVIEW ---

EOF

    echo ""
    echo -e "${CYAN}--- OUTPUT PREVIEW: $phase (first $lines lines) ---${NC}"
    echo "$preview"
    echo -e "${CYAN}--- END PREVIEW ---${NC}"
    echo ""
}

# =============================================================================
# CI Failure Summary function
# =============================================================================
show_ci_failure_summary() {
    local ci_output="$1"

    echo ""
    echo -e "${RED}=== CI FAILURE SUMMARY ===${NC}"

    # Extract ruff (lint) errors
    local ruff_errors=$(echo "$ci_output" | grep -E "^(backend|apps|tests)/.*:\d+:\d+:" | head -10)
    if [[ -n "$ruff_errors" ]]; then
        echo -e "${YELLOW}Lint Errors (ruff):${NC}"
        echo "$ruff_errors" | while read -r line; do
            echo "  - $line"
        done
        local ruff_count=$(echo "$ci_output" | grep -cE "^(backend|apps|tests)/.*:\d+:\d+:" || echo "0")
        if [[ $ruff_count -gt 10 ]]; then
            echo "  ... and $((ruff_count - 10)) more"
        fi
        echo ""
    fi

    # Extract mypy (type) errors
    local mypy_errors=$(echo "$ci_output" | grep -E "^(backend|apps|tests)/.*: error:" | head -10)
    if [[ -n "$mypy_errors" ]]; then
        echo -e "${YELLOW}Type Errors (mypy):${NC}"
        echo "$mypy_errors" | while read -r line; do
            echo "  - $line"
        done
        local mypy_count=$(echo "$ci_output" | grep -cE "^(backend|apps|tests)/.*: error:" || echo "0")
        if [[ $mypy_count -gt 10 ]]; then
            echo "  ... and $((mypy_count - 10)) more"
        fi
        echo ""
    fi

    # Extract bandit (security) issues
    local bandit_issues=$(echo "$ci_output" | grep -E "^>> Issue:" | head -5)
    if [[ -n "$bandit_issues" ]]; then
        echo -e "${YELLOW}Security Issues (bandit):${NC}"
        echo "$bandit_issues" | while read -r line; do
            echo "  - $line"
        done
        local bandit_count=$(echo "$ci_output" | grep -cE "^>> Issue:" || echo "0")
        if [[ $bandit_count -gt 5 ]]; then
            echo "  ... and $((bandit_count - 5)) more"
        fi
        echo ""
    fi

    # Extract pytest failures
    local test_failures=$(echo "$ci_output" | grep -E "^FAILED " | head -10)
    if [[ -n "$test_failures" ]]; then
        echo -e "${YELLOW}Test Failures (pytest):${NC}"
        echo "$test_failures" | while read -r line; do
            echo "  - $line"
        done
        local test_count=$(echo "$ci_output" | grep -cE "^FAILED " || echo "0")
        if [[ $test_count -gt 10 ]]; then
            echo "  ... and $((test_count - 10)) more"
        fi
        echo ""
    fi

    # Extract pytest short test summary (the actual failure reasons)
    local short_summary=$(echo "$ci_output" | sed -n '/=* short test summary info =*/,/==/p' | grep -E "^(FAILED|ERROR)" | head -5)
    if [[ -n "$short_summary" ]]; then
        echo -e "${YELLOW}Test Summary:${NC}"
        echo "$short_summary" | while read -r line; do
            echo "  - $line"
        done
        echo ""
    fi

    # Check for make target failures
    local make_errors=$(echo "$ci_output" | grep -E "^make(\[[0-9]+\])?: \*\*\*" | head -5)
    if [[ -n "$make_errors" ]]; then
        echo -e "${YELLOW}Make Errors:${NC}"
        echo "$make_errors" | while read -r line; do
            echo "  - $line"
        done
        echo ""
    fi

    echo -e "${RED}=== END FAILURE SUMMARY ===${NC}"
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

# =============================================================================
# Graceful shutdown handler
# =============================================================================
CHILD_PID=""

shutdown() {
    echo ""
    log "INFO" "Shutting down On-Demand CI..."
    # Kill any tracked child process
    if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
        log "INFO" "Stopping child process (PID: $CHILD_PID)..."
        kill -TERM "$CHILD_PID" 2>/dev/null
        # Give it a moment, then force kill if needed
        sleep 1
        kill -9 "$CHILD_PID" 2>/dev/null
    fi
    # Kill any remaining background jobs
    jobs -p | xargs -r kill 2>/dev/null
    log "INFO" "Log saved to: $LOG_FILE"
    exit 0
}

trap shutdown SIGINT SIGTERM

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

    # Check make
    if ! command -v make &> /dev/null; then
        log "ERROR" "make not found. Please install make."
        exit 1
    fi
    log "INFO" "make found"
}

# =============================================================================
# Main CI Loop
# =============================================================================
run_ci_with_fixes() {
    local ci_start=$(date +%s)
    log "INFO" "Starting full CI pipeline (make ci)..."
    log "INFO" "Max attempts: $MAX_CI_ATTEMPTS"

    local ci_passed=false
    local ci_attempt=0

    cd "$PROJECT_ROOT"

    while [[ $ci_attempt -lt $MAX_CI_ATTEMPTS && "$ci_passed" != "true" ]]; do
        ((ci_attempt++))
        log "INFO" "CI attempt $ci_attempt of $MAX_CI_ATTEMPTS"

        local ci_result=""
        local ci_exit_code=0
        local ci_temp_file="$LOOPER_DIR/.ci-output-temp.txt"

        # Reset database connections before running CI
        reset_db_connections

        # Run make ci in background so Ctrl+C can interrupt
        make ci > "$ci_temp_file" 2>&1 &
        CHILD_PID=$!
        wait $CHILD_PID || ci_exit_code=$?
        CHILD_PID=""
        ci_result=$(cat "$ci_temp_file")
        rm -f "$ci_temp_file"

        if [[ $ci_exit_code -eq 0 ]]; then
            ci_passed=true
            local ci_duration=$(format_duration $(($(date +%s) - ci_start)))
            log "SUCCESS" "CI passed! ($ci_duration)"
        else
            log "WARN" "CI failed (exit code: $ci_exit_code), asking Claude to fix..."

            # Show summary of failures
            show_ci_failure_summary "$ci_result"

            log "INFO" "  Allowed tools for fix: $TOOLS_CI_FIX"

            # Log CI issues
            local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
            cat >> "$LOG_FILE" << EOF

================================================================================
CI FAILURE - Attempt $ci_attempt of $MAX_CI_ATTEMPTS
Date: $timestamp
================================================================================
EOF
            echo "$ci_result" | tail -100 >> "$LOG_FILE"

            # Write CI issues to temp file
            local ci_issues_file="$LOOPER_DIR/ci-issues-temp.txt"
            echo "$ci_result" > "$ci_issues_file"

            local fix_prompt="IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Execute the .claude command 'bmad-agent-bmm-dev'

Step 2: Fix CI failures

The full CI pipeline (make ci) failed. Read the CI issues from: $ci_issues_file

Fix all lint errors (ruff), type errors (mypy), security issues (bandit), and test failures.

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

            # Reset database connections before Claude invocation
            reset_db_connections

            log "INFO" "Invoking DEV agent to fix CI issues..."
            local fix_temp_file="$LOOPER_DIR/.fix-output-temp.txt"

            # Run claude in background so Ctrl+C can interrupt
            claude --print --allowedTools "$TOOLS_CI_FIX" -- "$fix_prompt" > "$fix_temp_file" 2>&1 &
            CHILD_PID=$!
            wait $CHILD_PID || true
            CHILD_PID=""
            local fix_result=$(cat "$fix_temp_file")
            rm -f "$fix_temp_file"

            log_output_preview "CI Fix" "$fix_result"

            # Log full dev agent output
            echo "" >> "$LOG_FILE"
            echo "=== FULL DEV AGENT OUTPUT ===" >> "$LOG_FILE"
            echo "$fix_result" >> "$LOG_FILE"
            echo "=== END DEV AGENT OUTPUT ===" >> "$LOG_FILE"
        fi
    done

    if [[ "$ci_passed" != "true" ]]; then
        local total_duration=$(format_duration $(($(date +%s) - ci_start)))
        log "ERROR" "CI failed after $MAX_CI_ATTEMPTS attempts ($total_duration)"
        return 1
    fi

    return 0
}

# =============================================================================
# Main Entry Point
# =============================================================================
main() {
    echo ""
    echo -e "  ${MAGENTA}=====================================${NC}"
    echo -e "  ${MAGENTA}ON-DEMAND FULL CI${NC}"
    echo -e "  ${MAGENTA}PetCompass CI Pipeline${NC}"
    echo -e "  ${MAGENTA}=====================================${NC}"
    echo ""
    echo -e "  ${GREEN}Security: Using scoped --allowedTools${NC}"
    echo ""

    check_dependencies

    log "INFO" "========================================"
    log "INFO" "Starting On-Demand Full CI"
    log "INFO" "========================================"
    log "INFO" "Press Ctrl+C to stop gracefully"
    echo ""

    if run_ci_with_fixes; then
        echo ""
        log "SUCCESS" "========================================"
        log "SUCCESS" "Full CI pipeline completed successfully!"
        log "SUCCESS" "========================================"
        exit 0
    else
        echo ""
        log "ERROR" "========================================"
        log "ERROR" "Full CI pipeline failed. Please investigate."
        log "ERROR" "========================================"
        exit 1
    fi
}

main "$@"
