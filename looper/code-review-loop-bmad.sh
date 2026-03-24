#!/bin/bash
#
# code-review-loop-bmad - Read-Only Code Review using BMAD Agent Workflow
#
# Uses the BMAD DEV agent's structured code-review workflow on every story
# in an epic. READ-ONLY mode (no fixes applied).
#
# Compare with: code-review-loop-claude.sh (direct Claude review without BMAD)
#
# Safe to run in parallel with other development work since it doesn't
# modify any files.
#
# Usage: ./looper/code-review-loop-bmad.sh <epic-number>
# Example: ./looper/code-review-loop-bmad.sh 2
#
# Output files:
#   - epic<N>-code-review-bmad.log      (full processing log)
#   - epic<N>-code-review-bmad-results.log (findings only, for comparison)
#
# Stop: Ctrl+C (graceful shutdown)
#
# Prerequisites:
#   - Claude Code CLI installed
#   - Project files accessible
#

set -e
set -o pipefail

# Allow running from within a Claude Code session (e.g. via /bmad-dev)
unset CLAUDECODE 2>/dev/null || true

# =============================================================================
# Configuration
# =============================================================================
EPIC_NUMBER="${1:-}"

# Timezone: Central US (Austin, TX) via PowerShell (TZ env var unreliable on Windows)
get_timestamp() {
    powershell -Command "[System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Central Standard Time').ToString('yyyy-MM-dd HH:mm:ss')" 2>/dev/null || date '+%Y-%m-%d %H:%M:%S'
}

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="$PROJECT_ROOT/_bmad-output"
IMPL_DIR="$OUTPUT_DIR/implementation-artifacts"
LOOPER_DIR="$PROJECT_ROOT/looper"
LOG_FILE="$LOOPER_DIR/epic${EPIC_NUMBER}-code-review-bmad.log"
RESULTS_FILE="$LOOPER_DIR/epic${EPIC_NUMBER}-code-review-bmad-results.log"

# =============================================================================
# READ-ONLY TOOLS - No Edit, Write, or destructive Bash commands
# =============================================================================
# This ensures the review cannot modify any files
TOOLS_REVIEW_READONLY="Read,Glob,Grep,Task,TodoWrite,Skill"

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
# Logging function
# =============================================================================
log() {
    local level="$1"
    local message="$2"
    local timestamp=$(get_timestamp)

    case "$level" in
        "INFO")    echo -e "${CYAN}${timestamp} [${level}] *bmad* ${message}${NC}" ;;
        "WARN")    echo -e "${YELLOW}${timestamp} [${level}] *bmad* ${message}${NC}" ;;
        "ERROR")   echo -e "${RED}${timestamp} [${level}] *bmad* ${message}${NC}" ;;
        "SUCCESS") echo -e "${GREEN}${timestamp} [${level}] *bmad* ${message}${NC}" ;;
        "REVIEW")  echo -e "${MAGENTA}${timestamp} [${level}] *bmad* ${message}${NC}" ;;
        *)         echo -e "${timestamp} [${level}] *bmad* ${message}" ;;
    esac

    echo "${timestamp} [${level}] ${message}" >> "$LOG_FILE"
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
shutdown() {
    echo ""
    log "INFO" "Shutting down Code Review Loop..."
    log "INFO" "Log saved to: $LOG_FILE"
    exit 0
}

trap shutdown SIGINT SIGTERM

# =============================================================================
# Get ALL stories in an epic by scanning story files
# =============================================================================
# Story files follow the pattern: <epic>-<story>-<name>.md
# Status is read from line 3 of each file: "Status: <status>"
# Output format: "<story-id>: <status>" (one per line)
get_all_stories_in_epic() {
    if [[ ! -d "$IMPL_DIR" ]]; then
        return
    fi

    for story_file in "$IMPL_DIR"/${EPIC_NUMBER}-*.md; do
        [[ -f "$story_file" ]] || continue
        local basename=$(basename "$story_file" .md)
        local status=$(sed -n '3s/^Status: *//p' "$story_file" 2>/dev/null || echo "unknown")
        echo "${basename}: ${status}"
    done | sort
}

# =============================================================================
# Check if story implementation file exists
# =============================================================================
test_story_file_exists() {
    local story_id="$1"
    local story_file="$IMPL_DIR/${story_id}.md"
    [[ -f "$story_file" ]]
}

# =============================================================================
# Run read-only code review on a single story
# =============================================================================
review_story() {
    local story_id="$1"
    local story_number="$2"
    local story_status="$3"

    log "REVIEW" "=========================================="
    log "REVIEW" "Reviewing: $story_id (status: $story_status)"
    log "REVIEW" "=========================================="

    # Check if story implementation file exists
    if ! test_story_file_exists "$story_id"; then
        log "WARN" "Story file not found: ${story_id}.md - skipping"
        echo "" >> "$LOG_FILE"
        echo "SKIPPED: $story_id - No implementation file found" >> "$LOG_FILE"
        echo "" >> "$LOG_FILE"
        return 0
    fi

    sleep 5  # Delay between stories to allow Claude state reset
    local review_start=$(date +%s)

    # Build the BMAD-style review prompt (headless — no interactive BMAD skill)
    # The bmad-code-review skill has interactive HALTs that block in --print mode.
    # Instead, we bake the BMAD 3-layer review structure directly into the prompt.
    local prompt="You are performing a BMAD-style adversarial code review for story $story_id.

SETUP: Read these files first for project context and coding standards:
  - $PROJECT_ROOT/_bmad-output/project-context.md
  - $PROJECT_ROOT/CLAUDE.md
  - $PROJECT_ROOT/coding-standards.md

Then read the story spec file:
  - $IMPL_DIR/${story_id}.md

Then find and read ALL source files and test files referenced in or created by the story.

CRITICAL: This is a READ-ONLY audit. Do NOT fix any issues. ONLY report them.

YOU MUST EXECUTE ALL THREE REVIEW LAYERS BELOW:

=== LAYER 1: BLIND HUNTER ===
Review the code with NO regard for the spec — purely from what you see in the code itself.
Find: bugs, security issues, logic errors, code quality problems, anti-patterns.
For each finding: one-line title, severity (critical/high/medium/low), evidence from the code.

=== LAYER 2: EDGE CASE HUNTER ===
Walk every branching path and boundary condition. Report ONLY unhandled edge cases.
Focus on: boundary conditions, missing validation, race conditions, platform-specific issues,
encoding problems, empty inputs, path traversal, concurrency, error propagation.
For each finding: one-line title, severity, the specific edge case, evidence.

=== LAYER 3: ACCEPTANCE AUDITOR ===
Review the implementation against the story spec and acceptance criteria.
Check for: violations of acceptance criteria, deviations from spec intent,
missing implementation of specified behavior, contradictions between spec constraints and code.
Also check against coding-standards.md and CLAUDE.md rules.
For each finding: one-line title, which AC/rule it violates, evidence.

=== OUTPUT FORMAT ===
Present findings grouped by layer. For each finding include:
- One-line title
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- Evidence: file path, line number, code snippet
- Category: BUG / SECURITY / LOGIC / QUALITY / EDGE_CASE / SPEC_VIOLATION / CONVENTION

End with a summary:
Issues Found: [total count]
By Layer: Blind Hunter: [N], Edge Case Hunter: [N], Acceptance Auditor: [N]
By Severity: Critical: [N], High: [N], Medium: [N], Low: [N]
"

    local story_num=$(echo "$story_id" | cut -d'-' -f1-2)
    echo -e "${YELLOW}>>> Invoking BMAD code reviewer for $story_num...${NC}"
    log "INFO" "Running read-only code review (tools: $TOOLS_REVIEW_READONLY)..."

    # Log the prompt
    local timestamp=$(get_timestamp)
    cat >> "$LOG_FILE" << EOF

================================================================================
PROMPT: Code Review | Story: $story_id | Time: $timestamp
================================================================================
$prompt
================================================================================

EOF

    # Run Claude with read-only tools
    # Note: </dev/null prevents claude from consuming the while loop's stdin
    echo -e "${YELLOW}>>> Waiting for BMAD code reviewer response...${NC}"
    local result=""
    local exit_code=0
    result=$(claude --print --allowedTools "$TOOLS_REVIEW_READONLY" -- "$prompt" </dev/null 2>&1) || exit_code=$?
    echo -e "${GREEN}>>> BMAD code reviewer response received.${NC}"

    # Log the full output
    cat >> "$LOG_FILE" << EOF

================================================================================
OUTPUT: Code Review | Story: $story_id
================================================================================
$result
================================================================================

EOF

    # Log results only (for comparison analysis)
    cat >> "$RESULTS_FILE" << EOF

================================================================================
STORY: $story_id
================================================================================
$result
================================================================================

EOF

    # Show preview on terminal
    echo ""
    echo -e "${MAGENTA}--- Review Output Preview (first 8 lines) ---${NC}"
    echo "$result" | head -8
    echo -e "${MAGENTA}--- End Preview (full output in log file) ---${NC}"
    echo ""

    local review_duration=$(format_duration $(($(date +%s) - review_start)))

    if [[ $exit_code -ne 0 ]]; then
        log "ERROR" "Code review failed for $story_id (exit code: $exit_code) - Duration: $review_duration"
        return 1
    fi

    # Extract issue count if present
    local issue_count=$(echo "$result" | grep -oE "Issues Found:?\s*[0-9]+" | grep -oE "[0-9]+" | head -1 || echo "unknown")

    log "SUCCESS" "Code review complete for $story_id - Issues found: $issue_count - Duration: $review_duration"
    return 0
}

# =============================================================================
# Main loop - review all stories in the epic
# =============================================================================
start_epic_review() {
    local total_start=$(date +%s)

    log "INFO" "============================================================"
    log "INFO" "CODE REVIEW LOOP (BMAD WORKFLOW) - Epic $EPIC_NUMBER"
    log "INFO" "Mode: READ-ONLY (no fixes will be applied)"
    log "INFO" "Results file: $RESULTS_FILE"
    log "INFO" "Log file: $LOG_FILE"
    log "INFO" "============================================================"

    # Get all stories in the epic
    local stories=$(get_all_stories_in_epic)

    if [[ -z "$stories" ]]; then
        log "ERROR" "No stories found for Epic $EPIC_NUMBER"
        exit 1
    fi

    local story_count=$(echo "$stories" | wc -l | tr -d ' ')
    log "INFO" "Found $story_count stories in Epic $EPIC_NUMBER"

    # Show story list
    log "INFO" "Stories to review:"
    echo "$stories" | while read -r line; do
        log "INFO" "  - $line"
    done

    echo "" >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"
    echo "STORIES IN EPIC $EPIC_NUMBER" >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"
    echo "$stories" >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"

    echo ""
    log "INFO" "============================================================"
    log "INFO" "STARTING CODE REVIEWS NOW..."
    log "INFO" "============================================================"
    echo ""

    # Process each story
    local story_number=0
    local reviewed=0
    local skipped=0
    local failed=0

    while IFS= read -r story_line; do
        story_number=$((story_number + 1))

        # Parse story ID and status from "story-id: status"
        local story_id=$(echo "$story_line" | cut -d':' -f1 | xargs)
        local story_status=$(echo "$story_line" | cut -d':' -f2 | xargs)

        echo ""
        echo -e "${BLUE}============================================================${NC}"
        log "INFO" "[$story_number/$story_count] Processing: $story_id (status: $story_status)"
        echo -e "${BLUE}============================================================${NC}"

        if review_story "$story_id" "$story_number" "$story_status"; then
            reviewed=$((reviewed + 1))
        else
            if ! test_story_file_exists "$story_id"; then
                skipped=$((skipped + 1))
            else
                failed=$((failed + 1))
            fi
        fi

    done <<< "$stories"

    # Summary
    local total_duration=$(format_duration $(($(date +%s) - total_start)))

    log "INFO" ""
    log "INFO" "============================================================"
    log "INFO" "CODE REVIEW LOOP COMPLETE"
    log "INFO" "============================================================"
    log "INFO" "Epic: $EPIC_NUMBER"
    log "INFO" "Total stories: $story_count"
    log "SUCCESS" "Reviewed: $reviewed"
    if [[ $skipped -gt 0 ]]; then
        log "WARN" "Skipped: $skipped (no implementation file)"
    fi
    if [[ $failed -gt 0 ]]; then
        log "ERROR" "Failed: $failed"
    fi
    log "INFO" "Total duration: $total_duration"
    log "INFO" "Full log: $LOG_FILE"
    log "INFO" "Results only: $RESULTS_FILE"
    log "INFO" "============================================================"

    # Write summary to log
    cat >> "$LOG_FILE" << EOF

============================================================
SUMMARY
============================================================
Epic: $EPIC_NUMBER
Total stories: $story_count
Reviewed: $reviewed
Skipped: $skipped
Failed: $failed
Total duration: $total_duration
============================================================
EOF

    # Write summary to results file
    cat >> "$RESULTS_FILE" << EOF

================================================================================
SUMMARY
================================================================================
Epic: $EPIC_NUMBER
Total stories: $story_count
Reviewed: $reviewed
Skipped: $skipped
Failed: $failed
Total duration: $total_duration
================================================================================
EOF
}

# =============================================================================
# Check dependencies
# =============================================================================
check_dependencies() {
    if ! command -v claude &> /dev/null; then
        echo -e "${RED}Error: Claude CLI not found. Please install Claude Code CLI.${NC}"
        exit 1
    fi

    if [[ ! -d "$IMPL_DIR" ]]; then
        echo -e "${RED}Error: Implementation artifacts directory not found: $IMPL_DIR${NC}"
        exit 1
    fi

    # Verify at least one story file exists for the epic
    local count=$(ls "$IMPL_DIR"/${EPIC_NUMBER}-*.md 2>/dev/null | wc -l)
    if [[ $count -eq 0 ]]; then
        echo -e "${RED}Error: No story files found for epic $EPIC_NUMBER in $IMPL_DIR${NC}"
        exit 1
    fi
}

# =============================================================================
# Main
# =============================================================================
main() {
    if [[ -z "$EPIC_NUMBER" ]]; then
        echo "Usage: $0 <epic-number>"
        echo ""
        echo "Runs read-only code review using BMAD agent workflow on all stories."
        echo "Does NOT modify any files - safe to run in parallel with other work."
        echo ""
        echo "Output files:"
        echo "  - epic<N>-code-review-bmad.log         (full processing log)"
        echo "  - epic<N>-code-review-bmad-results.log (findings only)"
        echo ""
        echo "Example: $0 2"
        exit 1
    fi

    # Initialize log file
    cat > "$LOG_FILE" << EOF
================================================================================
CODE REVIEW LOOP LOG (BMAD WORKFLOW)
Epic: $EPIC_NUMBER
Started: $(get_timestamp)
Mode: READ-ONLY with BMAD Agent
================================================================================

EOF

    # Initialize results-only file
    cat > "$RESULTS_FILE" << EOF
================================================================================
CODE REVIEW RESULTS (BMAD WORKFLOW)
Epic: $EPIC_NUMBER
Started: $(get_timestamp)
================================================================================
This file contains only the review findings for easy comparison.
================================================================================

EOF

    check_dependencies
    start_epic_review
}

main "$@"
