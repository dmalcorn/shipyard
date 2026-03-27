#!/bin/bash
# PetCompass Local CI Pipeline
# Parallelized test execution optimized for Docker (16-core host)
#
# Usage:
#   ./scripts/ci.sh              # Full CI pipeline
#   ./scripts/ci.sh --quick      # Smoke tests only (fast feedback)
#   ./scripts/ci.sh --story 0-3  # Run tests for specific story only
#   ./scripts/ci.sh --test       # Skip linting, run tests only

set -e

# Configuration
# CI uses lower worker counts for resource-constrained environments
# Local dev (Makefile) uses higher values (8/4) for 16-core/32GB machines
UNIT_WORKERS=2      # Postgres connection pool limit (reduced to avoid connection exhaustion)
E2E_WORKERS=2       # Browser memory limit
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
STORY_FILTER=""     # Story pattern filter (e.g., "0-3" or "0_3")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Timing
START_TIME=$(date +%s)

print_header() {
    echo -e "\n${BLUE}===${NC} $1 ${BLUE}===${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_time() {
    local END_TIME=$(date +%s)
    local DURATION=$((END_TIME - START_TIME))
    echo -e "\n${GREEN}Total time: ${DURATION}s${NC}"
}

# Reset database connections to prevent connection exhaustion
reset_db_connections() {
    echo "Checking database connections..."

    # Determine database credentials from test settings
    local DB_HOST="${DB_HOST:-db}"
    local DB_USER="${DB_USER:-petcompass}"
    local DB_PASS="${DB_PASS:-devpassword}"
    local DB_NAME="${DB_NAME:-petcompass_dev}"
    local DB_CONTAINER="${DB_CONTAINER:-petcompass_db}"

    # Strategy: Try docker exec first (bypasses connection limits), then Python fallback
    set +e

    # Method 1: docker exec psql (doesn't need a client connection, bypasses max_connections)
    local docker_ok=false
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -c "
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
        AND datname IS NOT NULL;
    " 2>/dev/null && docker_ok=true

    if [ "$docker_ok" = true ]; then
        local conn_count
        conn_count=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -t -c "SELECT count(*) FROM pg_stat_activity;" 2>/dev/null | tr -d ' ' || echo "unknown")
        echo "Terminated stale connections via docker exec"
        echo "Current database connections: $conn_count"
        set -e
        return 0
    fi

    # Method 2: Python/psycopg (works inside container where docker exec is unavailable)
    python3 -c "
import sys, time

DB_HOST = '${DB_HOST}'
DB_USER = '${DB_USER}'
DB_PASS = '${DB_PASS}'

def try_reset():
    import psycopg
    conn = psycopg.connect(
        host=DB_HOST, user=DB_USER,
        password=DB_PASS, dbname='postgres',
        connect_timeout=5,
        autocommit=True
    )
    cur = conn.cursor()
    cur.execute('''
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
        AND datname IS NOT NULL
    ''')
    terminated = cur.rowcount
    print(f'Terminated {terminated} stale connections')
    cur.execute('SELECT count(*) FROM pg_stat_activity')
    count = cur.fetchone()[0]
    print(f'Current database connections: {count}')
    conn.close()
    return True

for attempt in range(5):
    try:
        if try_reset():
            break
    except Exception as e:
        if attempt < 4:
            print(f'Retry {attempt+1}/5: {e}', file=sys.stderr)
            time.sleep(3)
        else:
            print(f'Warning: Connection reset failed after 5 attempts: {e}', file=sys.stderr)
"
    set -e
}

# Parse arguments
QUICK_MODE=false
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            QUICK_MODE=true
            shift
            ;;
        --test)
            TEST_ONLY=true
            shift
            ;;
        --story)
            STORY_FILTER="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════╗"
echo "║     PetCompass Local CI Pipeline          ║"
echo "║     Parallelized for 16-core Docker       ║"
echo "╚═══════════════════════════════════════════╝"
echo -e "${NC}"

if $QUICK_MODE; then
    print_warning "Quick mode: Running smoke tests only"
fi

if [ -n "$STORY_FILTER" ]; then
    print_warning "Story filter: Running tests for story ${STORY_FILTER} only"
fi

# Change to project root
cd "$PROJECT_ROOT"

# Reset stale database connections before running tests
reset_db_connections

#
# STAGE 1: Static Analysis (parallel-safe, run together)
#
if ! $TEST_ONLY; then
    print_header "Stage 1: Static Analysis"

    echo "Running ruff linting..."
    if ruff check backend/; then
        print_success "Ruff linting passed"
    else
        print_error "Ruff linting failed"
        exit 1
    fi

    echo "Running mypy type checking..."
    if (cd backend && mypy . --ignore-missing-imports); then
        print_success "Mypy type checking passed"
    else
        print_error "Mypy type checking failed"
        exit 1
    fi

    echo "Running bandit security scan..."
    if bandit -r backend/ -x backend/tests,backend/test_dna_direct.py -q; then
        print_success "Bandit security scan passed"
    else
        print_error "Bandit security scan failed"
        exit 1
    fi
fi

#
# STAGE 2: Unit/Integration Tests (parallelized)
#
print_header "Stage 2: Unit & Integration Tests (${UNIT_WORKERS} workers)"

if $QUICK_MODE; then
    # Quick mode: smoke tests only
    echo "Running smoke tests..."
    if DJANGO_SETTINGS_MODULE=config.settings.test pytest backend/tests/ -n "$UNIT_WORKERS" --dist loadscope -m "p0 or smoke" -v --tb=short; then
        print_success "Smoke tests passed"
    else
        print_error "Smoke tests failed"
        exit 1
    fi
else
    # Full mode: run unit tests (optionally filtered by story)
    if [ -n "$STORY_FILTER" ]; then
        STORY_PATTERN=$(echo "$STORY_FILTER" | tr '-' '_')
        UNIT_TEST_PATH="backend/tests/test_story_${STORY_PATTERN}*.py"
        if ! ls $UNIT_TEST_PATH 1>/dev/null 2>&1; then
            print_warning "No unit tests found for story ${STORY_FILTER}, skipping unit tests"
            UNIT_TEST_PATH=""
        else
            echo "Running unit tests for story ${STORY_FILTER}..."
        fi
    else
        UNIT_TEST_PATH="backend/tests/"
        echo "Running all unit tests..."
    fi
    if [ -n "$UNIT_TEST_PATH" ]; then
        if DJANGO_SETTINGS_MODULE=config.settings.test pytest $UNIT_TEST_PATH -n "$UNIT_WORKERS" --dist loadscope -v --tb=short; then
            print_success "Unit tests passed"
        else
            print_error "Unit tests failed"
            exit 1
        fi
    fi
fi

#
# STAGE 3: E2E Tests (parallelized, fewer workers for browser memory)
#
if ! $QUICK_MODE; then
    print_header "Stage 3: E2E Tests (${E2E_WORKERS} workers)"

    # Check if Django server is running on localhost:8000
    E2E_SERVER_STARTED=false
    if ! python3 -c "import socket; s=socket.socket(); s.settimeout(2); exit(0 if s.connect_ex(('localhost', 8000))==0 else 1)" 2>/dev/null; then
        echo "Django server not running on port 8000, starting it for E2E tests..."
        cd "$PROJECT_ROOT/backend"
        DJANGO_SETTINGS_MODULE=config.settings.dev python3 manage.py runserver 0.0.0.0:8000 >/dev/null 2>&1 &
        E2E_SERVER_PID=$!
        E2E_SERVER_STARTED=true
        cd "$PROJECT_ROOT"

        # Wait for server to be ready (max 30 seconds)
        for i in $(seq 1 30); do
            if python3 -c "import socket; s=socket.socket(); s.settimeout(2); exit(0 if s.connect_ex(('localhost', 8000))==0 else 1)" 2>/dev/null; then
                print_success "Django server started (PID: $E2E_SERVER_PID)"
                break
            fi
            if [ $i -eq 30 ]; then
                print_warning "Django server failed to start, skipping E2E tests"
                kill $E2E_SERVER_PID 2>/dev/null || true
                E2E_SERVER_STARTED=false
            fi
            sleep 1
        done
    else
        print_success "Django server already running on port 8000"
    fi

    # Ensure Vite dev server is running with fresh code on localhost:5173
    # Always kill and restart to avoid stale code (WSL2/DevContainer HMR issue)
    VITE_SERVER_STARTED=false
    if grep -rl "localhost:5173\|WEB_BASE_URL" tests/e2e/ >/dev/null 2>&1; then
        if python3 -c "import socket; s=socket.socket(); s.settimeout(2); exit(0 if s.connect_ex(('localhost', 5173))==0 else 1)" 2>/dev/null; then
            echo "Killing existing Vite server to ensure fresh code..."
            pkill -f "node.*vite" 2>/dev/null || true
            sleep 2
        fi

        echo "Starting fresh Vite dev server on port 5173..."
        cd "$PROJECT_ROOT/web"
        npx vite --host 0.0.0.0 --port 5173 >/dev/null 2>&1 &
        VITE_SERVER_PID=$!
        VITE_SERVER_STARTED=true
        cd "$PROJECT_ROOT"

        # Wait for Vite to be ready (max 30 seconds)
        for i in $(seq 1 30); do
            if python3 -c "import socket; s=socket.socket(); s.settimeout(2); exit(0 if s.connect_ex(('localhost', 5173))==0 else 1)" 2>/dev/null; then
                print_success "Vite dev server started (PID: $VITE_SERVER_PID)"
                break
            fi
            if [ $i -eq 30 ]; then
                print_warning "Vite dev server failed to start, browser E2E tests may fail"
                kill $VITE_SERVER_PID 2>/dev/null || true
                VITE_SERVER_STARTED=false
            fi
            sleep 1
        done
    fi

    # Build E2E test path based on story filter
    E2E_FAILED=false
    if [ -n "$STORY_FILTER" ]; then
        # Convert story format (0-3 or 0_3) to file pattern
        STORY_PATTERN=$(echo "$STORY_FILTER" | tr '-' '_')
        E2E_PATH="tests/e2e/test_story_${STORY_PATTERN}*.py"

        if ! ls $E2E_PATH 1>/dev/null 2>&1; then
            print_warning "No E2E tests found for story ${STORY_FILTER}, skipping"
        else
            echo "Running E2E tests for story ${STORY_FILTER}..."
            # Set PYTHONPATH: project root for test imports, backend for Django settings
            # Skip admin tests (require admin service on port 8001 which isn't started in CI)
            # Note: Capture exit code explicitly to prevent set -e from exiting before we can check it
            set +e
            PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/backend:${PYTHONPATH:-}" pytest $E2E_PATH -n "$E2E_WORKERS" --dist loadfile -v --tb=short -m "not admin" --reruns 1 --reruns-delay 2
            E2E_EXIT_CODE=$?
            set -e
            if [ $E2E_EXIT_CODE -eq 0 ]; then
                print_success "E2E tests passed"
            elif [ $E2E_EXIT_CODE -eq 5 ]; then
                # Exit code 5 = no tests collected (all tests filtered by marker)
                print_warning "No non-admin E2E tests for story ${STORY_FILTER} (all tests marked admin), skipping"
            else
                print_error "E2E tests failed"
                E2E_FAILED=true
            fi
        fi
    else
        # No story filter - run all E2E tests
        if [ -d "tests/e2e" ] && [ "$(find tests/e2e -name 'test_*.py' | head -1)" ]; then
            echo "Running all E2E tests..."
            # Set PYTHONPATH: project root for test imports, backend for Django settings
            # Skip admin tests (require admin service on port 8001 which isn't started in CI)
            # Note: Capture exit code explicitly to prevent set -e from exiting before we can check it
            set +e
            PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/backend:${PYTHONPATH:-}" pytest tests/e2e/ -n "$E2E_WORKERS" --dist loadfile -v --tb=short -m "not admin" --reruns 1 --reruns-delay 2
            E2E_EXIT_CODE=$?
            set -e
            if [ $E2E_EXIT_CODE -eq 0 ]; then
                print_success "E2E tests passed"
            elif [ $E2E_EXIT_CODE -eq 5 ]; then
                # Exit code 5 = no tests collected (all tests filtered by marker)
                print_warning "No non-admin E2E tests collected (all tests marked admin), skipping"
            else
                print_error "E2E tests failed"
                E2E_FAILED=true
            fi
        else
            print_warning "No E2E tests found, skipping"
        fi
    fi

    # Clean up servers if we started them
    if $VITE_SERVER_STARTED && [ -n "${VITE_SERVER_PID:-}" ]; then
        kill $VITE_SERVER_PID 2>/dev/null || true
        wait $VITE_SERVER_PID 2>/dev/null || true
        echo "Stopped Vite dev server (PID: $VITE_SERVER_PID)"
    fi
    if $E2E_SERVER_STARTED && [ -n "${E2E_SERVER_PID:-}" ]; then
        kill $E2E_SERVER_PID 2>/dev/null || true
        wait $E2E_SERVER_PID 2>/dev/null || true
        echo "Stopped Django server (PID: $E2E_SERVER_PID)"
    fi

    # Exit after cleanup if E2E tests failed
    if $E2E_FAILED; then
        exit 1
    fi
fi

#
# STAGE 4: Coverage Report (optional, sequential)
#
if ! $QUICK_MODE && [ "${COVERAGE:-false}" = "true" ]; then
    print_header "Stage 4: Coverage Report"

    echo "Generating coverage report..."
    DJANGO_SETTINGS_MODULE=config.settings.test pytest backend/tests/ --cov=backend --cov-report=term-missing --cov-report=html -n "$UNIT_WORKERS"
    print_success "Coverage report generated: htmlcov/index.html"
fi

#
# Summary
#
echo -e "\n${GREEN}"
echo "╔═══════════════════════════════════════════╗"
echo "║         ✓ CI Pipeline Passed!             ║"
echo "╚═══════════════════════════════════════════╝"
echo -e "${NC}"

print_time
