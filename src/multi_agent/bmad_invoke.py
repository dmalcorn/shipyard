"""BMAD agent invocation via Claude CLI.

Shells out to `claude --print --allowedTools` to invoke BMAD agents
in isolated sessions. Each call gets a fresh Claude context with
scoped tool permissions — matching the proven pattern from the
looper bash scripts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from src.intake.cost_tracker import add_cost
from src.intake.pause import force_quit_event
from src.multi_agent.proc_registry import register, unregister

logger = logging.getLogger(__name__)

# Resolve the claude CLI executable once at module load.
# Windows note: subprocess.Popen does NOT honor PATHEXT, so it can't
# find `claude.cmd` (the npm-global Windows shim) by stem. shutil.which
# does honor PATHEXT, so we resolve the full path here. On Linux/macOS
# this returns the same path as a bare "claude" lookup, so it's a no-op
# in practice. Falls back to the bare name if nothing resolves, which
# preserves the prior behavior + error message on misconfigured hosts.
CLAUDE_BIN = shutil.which("claude") or "claude"


def _subprocess_env() -> dict[str, str]:
    """Build env for Claude subprocesses — disables git pager to prevent hangs."""
    env = os.environ.copy()
    env["GIT_PAGER"] = "cat"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env

# ---------------------------------------------------------------------------
# Default timeout (seconds) per agent type
# ---------------------------------------------------------------------------
TIMEOUT_SHORT = 15 * 60   # 15 min — story creation, test review
TIMEOUT_MEDIUM = 25 * 60  # 25 min — code review, test automation
TIMEOUT_LONG = 45 * 60    # 45 min — implementation, CI fix

# ---------------------------------------------------------------------------
# Scoped tool permissions per phase
#
# Language-agnostic: includes Python, Node, Rust, and Go toolchains so
# agents can work with any target project. Having unused permissions is
# harmless; missing ones block the agent.
# ---------------------------------------------------------------------------

# Common bash tools shared across build/test/CI phases
_BASH_BUILD = ",".join([
    # Python
    "Bash(python *)", "Bash(pip *)", "Bash(pytest *)",
    "Bash(ruff *)", "Bash(mypy *)", "Bash(bandit *)",
    # Node / TypeScript
    "Bash(npm *)", "Bash(npx *)", "Bash(tsc *)", "Bash(eslint *)",
    # Rust
    "Bash(cargo *)", "Bash(rustc *)",
    # Go
    "Bash(go *)", "Bash(golangci-lint *)",
    # General
    "Bash(make *)",
])

# Read-only filesystem inspection. Agents reach for these naturally when
# diagnosing file state; without them they fall into tool-discovery loops
# trying to work around silent denials.
_BASH_INSPECT = ",".join([
    "Bash(cat *)",
    "Bash(ls *)", "Bash(ls)",
    "Bash(head *)", "Bash(tail *)",
    "Bash(wc *)",
    "Bash(find *)",
    "Bash(file *)",
])

# Read-only git: inspection only — no staging, commit, push, reset,
# checkout, merge, rebase, stash, or rm. Safe for a CI-fix agent that
# needs to inspect history and working-tree state without mutating it.
_BASH_GIT_READONLY = ",".join([
    "Bash(git status *)", "Bash(git status)",
    "Bash(git log *)", "Bash(git log)",
    "Bash(git diff *)", "Bash(git diff)",
    "Bash(git show *)", "Bash(git show)",
    "Bash(git blame *)",
    "Bash(git ls-files *)", "Bash(git ls-files)",
    "Bash(git branch *)", "Bash(git branch)",
    "Bash(git rev-parse *)",
])

_BASE_TOOLS = "Read,Edit,Write,Glob,Grep,Task,TodoWrite"

TOOLS_TEA = f"{_BASE_TOOLS},{_BASH_BUILD},Skill"
TOOLS_TEA_FIX = f"{_BASE_TOOLS},{_BASH_BUILD},Skill"
TOOLS_DEV = f"{_BASE_TOOLS},{_BASH_BUILD},{_BASH_INSPECT},Bash(git *),Skill"
TOOLS_CODE_REVIEW = f"{_BASE_TOOLS},{_BASH_BUILD},{_BASH_INSPECT},Skill"
TOOLS_CI_FIX = (
    f"{_BASE_TOOLS},{_BASH_BUILD},{_BASH_INSPECT},"
    f"{_BASH_GIT_READONLY},Bash(bash *),Skill"
)
TOOLS_REVIEW_READONLY = "Read,Glob,Grep,Task,TodoWrite,Skill"
TOOLS_CI_GENERATE = f"{_BASE_TOOLS},Skill"


_MODEL_VERSION_RE = re.compile(r"(\d+)-(\d+)")


def _model_families_match(requested: str, resolved: str) -> bool:
    """Return True when requested and resolved models are equivalent.

    The Claude CLI accepts short aliases (``opus``, ``sonnet``,
    ``haiku``) as well as full model IDs (``claude-opus-4-6``,
    ``claude-sonnet-4-6-20251201``). It then resolves whatever was
    passed to a concrete model name in the session init event. The
    comparison is two-stage:

    1. **Family check** — both names must share the same family
       keyword (``opus`` / ``sonnet`` / ``haiku``). Names with no
       recognized family fall back to literal case-insensitive match.
    2. **Version check** — if the requested name carries an explicit
       ``<major>-<minor>`` version (e.g. ``4-6``), the resolved name
       must share that same version. Bare aliases like ``sonnet``
       have no version and skip this stage. Dated variants like
       ``claude-sonnet-4-6-20251201`` are tolerated because their
       version prefix still matches.

    Examples:
        ``opus`` matches ``claude-opus-4-6``                 → True
        ``claude-opus-4-6`` matches ``claude-opus-4-6``      → True
        ``opus`` matches ``claude-sonnet-4-6``               → False
        ``sonnet`` matches ``claude-sonnet-4-5-20251001``    → True
        ``claude-sonnet-4-6`` matches ``claude-sonnet-4-6-20251201`` → True
        ``claude-sonnet-4-6`` matches ``claude-sonnet-4-5``  → False
    """
    def family(name: str) -> str:
        lowered = name.lower()
        for fam in ("opus", "sonnet", "haiku"):
            if fam in lowered:
                return fam
        return lowered

    def version(name: str) -> tuple[str, str] | None:
        match = _MODEL_VERSION_RE.search(name)
        return (match.group(1), match.group(2)) if match else None

    if family(requested) != family(resolved):
        return False

    req_version = version(requested)
    if req_version is None:
        # Bare alias (e.g. "sonnet") — family match is the contract.
        return True

    res_version = version(resolved)
    if res_version is None:
        # Resolved has no version in its name — trust the family match.
        return True

    return req_version == res_version


def _print_stream_event(
    event: dict[str, Any],
    agent_name: str,
    start_time: float,
    output_chunks: list[str],
    requested_model: str | None = None,
) -> None:
    """Parse a stream-json event and print meaningful content in real-time.

    Only prints actionable information: agent text output, tool usage,
    and final results. Silently skips noise (user messages, progress pings).

    When ``requested_model`` is provided, the init-event handler prints
    a ``MODEL MISMATCH`` warning if the CLI resolved to a different
    model family than the caller asked for — catches silent fallbacks
    (e.g. requesting opus but getting sonnet because the CLI couldn't
    resolve the alias on this host).
    """
    elapsed = time.time() - start_time
    tag = f"[{agent_name} {elapsed:5.0f}s]"

    msg_type = event.get("type", "")
    subtype = event.get("subtype", "")

    # --- Init: one-liner that agent session started ---
    if msg_type == "system" and subtype == "init":
        resolved = event.get("model", "?")
        if requested_model:
            if _model_families_match(requested_model, resolved):
                print(
                    f"      {tag} Session started "
                    f"(requested={requested_model}, resolved={resolved})",
                )
            else:
                print(
                    f"      {tag} MODEL MISMATCH: requested={requested_model} "
                    f"but CLI resolved to {resolved}",
                )
        else:
            print(f"      {tag} Session started (model={resolved})")
        return

    # --- Final result: show summary and capture output ---
    if msg_type == "result":
        result_text = event.get("result", "")
        cost = event.get("total_cost_usd", 0)
        turns = event.get("num_turns", 0)
        status = subtype  # "success" or "error"
        if cost:
            add_cost(cost)
        print(f"      {tag} RESULT: {status} ({turns} turns, ${cost:.4f})")
        if result_text:
            # Show first 300 chars of result
            preview = result_text[:500].replace("\n", "\n      " + " " * len(tag) + " ")
            print(f"      {tag}   {preview}")
            output_chunks.append(result_text)
        return

    # --- Assistant messages: extract text and tool_use blocks ---
    if msg_type == "assistant":
        message = event.get("message", {})
        content = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text = block.get("text", "").strip()
                if text:
                    preview = text[:500].replace("\n", "\n      " + " " * len(tag) + " ")
                    print(f"      {tag} {preview}")
                    output_chunks.append(text)
            elif block_type == "tool_use":
                tool_name = block.get("name", "?")
                tool_input = block.get("input", {})
                # Show tool name + compact input summary
                if isinstance(tool_input, dict):
                    # For file ops, show the path; for others, show first key
                    path = tool_input.get("file_path") or tool_input.get("path") or ""
                    if path:
                        print(f"      {tag} -> {tool_name}: {path}")
                    else:
                        summary = str(tool_input)[:500]
                        print(f"      {tag} -> {tool_name}: {summary}")
                else:
                    print(f"      {tag} -> {tool_name}")
        return

    # --- Skip everything else (user messages, system progress, etc.) ---


def _extract_agent_identification(output: str) -> str | None:
    """Extract the AGENT IDENTIFICATION block from CLI output.

    Returns the block content if found, or None.
    """
    match = re.search(
        r"=== AGENT IDENTIFICATION ===\s*\n(.*?)=== END IDENTIFICATION ===",
        output,
        re.DOTALL,
    )
    return match.group(1).strip() if match else None


# Module-global counter of seconds spent in rate-limit auto-retry sleeps.
# The orchestrator resets this at story-start and reads it at story-end so
# per-story duration metrics can subtract sleep time from wall-clock time —
# otherwise a story that hit a 2h rate-limit window looks "slow" when it
# was actually just waiting. Single-threaded in practice (one story at a
# time); the lock is defensive only.
_rate_limit_sleep_seconds: int = 0
_rate_limit_sleep_lock = threading.Lock()


def reset_rate_limit_sleep_counter() -> None:
    """Zero the rate-limit sleep counter. Called at story boundaries."""
    global _rate_limit_sleep_seconds
    with _rate_limit_sleep_lock:
        _rate_limit_sleep_seconds = 0


def get_rate_limit_sleep_seconds() -> int:
    """Return seconds spent in rate-limit sleeps since the last reset."""
    with _rate_limit_sleep_lock:
        return _rate_limit_sleep_seconds


def _add_rate_limit_sleep(seconds: int) -> None:
    global _rate_limit_sleep_seconds
    with _rate_limit_sleep_lock:
        _rate_limit_sleep_seconds += seconds


def _parse_rate_limit_wait_seconds(output: str) -> int | None:
    """Parse "You've hit your limit · resets HH:MMam/pm (...)" and return
    seconds until the wall-clock reset time (in local time). The CLI's
    timezone in parens matches the user's local timezone in practice, so
    we don't need IANA tz data — datetime.now() gives the correct frame.
    Returns None if the pattern isn't present or can't be parsed.
    """
    m = re.search(
        r"resets\s+(\d{1,2}):(\d{2})\s*(am|pm)",
        output,
        re.IGNORECASE,
    )
    if not m:
        return None
    hour_12 = int(m.group(1))
    minute = int(m.group(2))
    ampm = m.group(3).lower()
    if not (1 <= hour_12 <= 12 and 0 <= minute <= 59):
        return None
    hour_24 = hour_12 % 12
    if ampm == "pm":
        hour_24 += 12
    now = datetime.now()
    reset = now.replace(hour=hour_24, minute=minute, second=0, microsecond=0)
    if reset <= now:
        reset = reset + timedelta(days=1)
    return int((reset - now).total_seconds())


def _build_bmad_prompt(
    agent_command: str,
    bmad_agent: str,
    extra_context: str = "",
) -> str:
    """Build a BMAD-style agent invocation prompt.

    Args:
        agent_command: The BMAD command to execute (e.g. "DS for story 2-1").
        bmad_agent: The BMAD agent slash command (e.g. "bmad-agent-dev").
        extra_context: Optional additional context appended to the prompt.
    """
    prompt = (
        f"AUTOMATED PIPELINE MODE — This is a non-interactive execution. "
        f"There is no human operator. stdin is closed. You MUST:\n"
        f"- Never display menus or greetings\n"
        f"- Never wait for user input or confirmation\n"
        f"- Never ask clarifying questions\n"
        f"- Follow the skill's workflow faithfully. When a step would "
        f"normally HALT to ask the operator a question, the operator is "
        f"unavailable but the workflow's contract still binds you. "
        f"Derive what the step needs from the trigger prompt, project "
        f"state, recent git history, or your other tools, and continue "
        f"executing the workflow step as authored.\n"
        f"- Proceed with best judgment on tie-breaking choices within "
        f"a step (e.g., picking between two equivalent fix approaches).\n"
        f"- On failure after 3 retries, log the error and exit\n"
        f"- Execute the command below immediately and completely\n\n"
        f"TEST EXECUTION RULES:\n"
        f"- Run only the specific test file(s) related to your changes, "
        f"not the full test suite (e.g. `npx vitest run src/path/to/"
        f"your.test.ts`). The pipeline runs the full suite separately.\n"
        f"- If a test command times out, report the timeout and move on "
        f"— do not retry with different flags or poll for completion.\n"
        f"- Never use `sleep` commands. Never run background tasks and "
        f"poll their output files.\n\n"
        f"IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE "
        f"TO INVOKE THE BMAD AGENT.\n\n"
        f"Step 1: Use the Skill tool to invoke '{bmad_agent}'\n\n"
        f"Step 2: Execute command: {agent_command}\n\n"
        # We intentionally do NOT ask the agent what model it is here.
        # The CLI's stream-json init event is the authoritative source
        # for that, and we parse it silently in _print_stream_event so
        # the agent has no indication we care about model identity. The
        # fields below are things only the agent can tell us — persona
        # name and which skill files its activation actually loaded.
        f"Step 3: After completing your work, end your response with "
        f"this AGENT IDENTIFICATION block:\n\n"
        f"=== AGENT IDENTIFICATION ===\n"
        f"Agent: [Your agent type, e.g., DEV Agent]\n"
        f"Persona: [Your persona name from the agent file]\n"
        f"Loaded files:\n"
        f"  - [exact path to each file you read during activation]\n"
        f"=== END IDENTIFICATION ==="
    )
    if extra_context:
        prompt += f"\n\n{extra_context}"
    return prompt


def invoke_bmad_agent(
    bmad_agent: str,
    command: str,
    tools: str,
    working_dir: str | None = None,
    timeout: int = TIMEOUT_MEDIUM,
    extra_context: str = "",
    model: str | None = None,
    _rate_limit_retries: int = 0,
) -> dict[str, Any]:
    """Invoke a BMAD agent via Claude CLI in an isolated session.

    Shells out to `claude --print --allowedTools` with a BMAD-style
    prompt. Returns the CLI output and detected file modifications.

    Args:
        bmad_agent: BMAD agent slash command (e.g. "bmad-agent-dev").
        command: BMAD command to execute (e.g. "DS for story 2-1").
        tools: Comma-separated tool permission string.
        working_dir: Working directory for the Claude CLI process.
        timeout: Maximum execution time in seconds.
        extra_context: Optional additional context for the prompt.
        model: Optional model override (e.g. "opus", "sonnet",
            or full name like "claude-opus-4-6").

    Returns:
        Dict with keys: output (str), files_modified (list[str]),
        success (bool), exit_code (int).
    """
    prompt = _build_bmad_prompt(command, bmad_agent, extra_context)
    cwd = working_dir or os.getcwd()

    print(f"\n      [bmad] === INVOCATION START: {bmad_agent} ===")
    print(f"      [bmad] Command: {command}")
    print(f"      [bmad] Tools: {tools}")
    print(f"      [bmad] Timeout: {timeout}s | CWD: {cwd}")
    print("      [bmad] --- PROMPT ---")
    for line in prompt.splitlines():
        print(f"      [bmad]   {line}")
    print("      [bmad] --- END PROMPT ---")
    model_label = f" (model={model})" if model else ""
    print(f"      [bmad] Streaming via claude --print --output-format stream-json{model_label} ...")
    start_time = time.time()

    output_chunks: list[str] = []
    stderr_lines: list[str] = []

    try:
        cli_args = [
            CLAUDE_BIN, "--print", "--verbose",
            "--output-format", "stream-json",
            "--setting-sources", "project",
            "--allowedTools", tools,
        ]
        if model:
            cli_args.extend(["--model", model])
        # Prompt is delivered via stdin (not argv) so multi-line content
        # survives Windows cmd.exe argument parsing on the claude.CMD shim.
        # On Linux/macOS this is functionally equivalent to argv delivery.

        proc = subprocess.Popen(
            cli_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            stdin=subprocess.PIPE,
            env=_subprocess_env(),
        )
        register(proc)

        # Send the prompt and close stdin so claude knows the input is complete.
        # Prompts are well under the OS pipe buffer limit, so a single write
        # without separate draining is safe.
        assert proc.stdin is not None
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except OSError as e:
            logger.warning("Failed to send prompt to claude stdin: %s", e)

        # Watchdog: kill subprocess on force-quit (second Ctrl+C)
        def _watchdog() -> None:
            force_quit_event.wait()
            if proc.poll() is None:
                print(f"\n      [bmad] Force-quit: killing {bmad_agent} subprocess...")
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except OSError:
                    pass

        watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
        watchdog_thread.start()

        # Stream stderr in a background thread so it doesn't block
        def _drain_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    stderr_lines.append(line)
                    print(f"      [bmad:err] {line[:500]}")

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # Stream stdout line-by-line (each line is a JSON event)
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            raw_line = raw_line.rstrip()
            if not raw_line:
                continue

            # Parse the stream-json event and print meaningful content
            try:
                event = json.loads(raw_line)
                _print_stream_event(
                    event, bmad_agent, start_time, output_chunks,
                    requested_model=model,
                )
            except json.JSONDecodeError:
                # Not JSON — print raw
                print(f"      [bmad:raw] {raw_line[:500]}")
                output_chunks.append(raw_line)

        proc.wait(timeout=30)
        stderr_thread.join(timeout=5)
        unregister(proc)

        exit_code = proc.returncode
        success = exit_code == 0

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"      [bmad] TIMEOUT after {elapsed:.0f}s: {bmad_agent} {command}")
        proc.kill()
        proc.wait()
        unregister(proc)
        output_chunks.append(f"TIMEOUT: Claude CLI did not respond within {timeout}s")
        success = False
        exit_code = 124

    except Exception as e:
        print(f"      [bmad] ERROR: {e}")
        output_chunks.append(f"ERROR: Failed to invoke Claude CLI: {e}")
        success = False
        exit_code = 1

    output = "\n".join(output_chunks)
    elapsed = time.time() - start_time
    print(f"\n      [bmad] Finished in {elapsed:.1f}s (exit={exit_code})")

    # Detect modified files via git
    files_modified = _detect_modified_files(cwd)

    print(
        f"      [bmad] Complete: exit={exit_code} "
        f"files_modified={len(files_modified)} output_len={len(output)}"
    )

    # Empty-output sanity: on exit=0 with zero output, the subprocess was
    # pause-killed or crashed silently — treat as failure so the calling
    # node routes to its error path instead of saving a bogus "success".
    if success and len(output.strip()) == 0:
        print(
            "      [bmad] WARNING: exit=0 but output_len=0 — "
            "treating as failure (likely pause-kill or silent crash)",
        )
        success = False

    # Auth/rate-limit halt: when the claude CLI surfaces an org-access
    # or 5-hour-window message, every subsequent agent invocation will
    # return in 1 turn / $0.00 and the pipeline cascades through every
    # remaining story marking each "failed" — even though the failures
    # are not real. Halt the pipeline immediately so resumption after
    # the limit window lifts is clean. Hit twice on the chat2diagram
    # run (subscription expired, then 5-hour rate window).
    _AUTH_HALT_PATTERNS = (
        "does not have access to Claude",
        "You've hit your limit",
        "Please login again or contact your administrator",
    )
    if any(p in output for p in _AUTH_HALT_PATTERNS):
        match = next((p for p in _AUTH_HALT_PATTERNS if p in output), "")

        # Rate-limit window with parseable reset time: sleep until the
        # window lifts and retry the same invocation, instead of halting
        # the pipeline. Capped at 2 retries and 6h sleep as safety bounds.
        # Other auth patterns ("does not have access", "Please login")
        # are revocations that need human intervention — fall through to
        # the halt path below.
        MAX_RATE_LIMIT_RETRIES = 2
        MAX_WAIT_SECONDS = 6 * 3600
        if "You've hit your limit" in output and _rate_limit_retries < MAX_RATE_LIMIT_RETRIES:
            wait_s = _parse_rate_limit_wait_seconds(output)
            if wait_s is not None and 0 < wait_s <= MAX_WAIT_SECONDS:
                wait_s += 60  # buffer past the reset minute
                wait_min = wait_s // 60
                wake = (datetime.now() + timedelta(seconds=wait_s)).strftime("%H:%M:%S")
                print(
                    f"\n      [bmad] *** RATE LIMIT detected: '{match}'\n"
                    f"      [bmad] *** Sleeping {wait_min} min until ~{wake} "
                    f"(retry {_rate_limit_retries + 1}/{MAX_RATE_LIMIT_RETRIES}), "
                    f"then re-running: {bmad_agent} {command}",
                )
                # force_quit_event lets a Ctrl+C abort the sleep cleanly
                if force_quit_event.wait(timeout=wait_s):
                    print(
                        "      [bmad] Force-quit during rate-limit sleep — "
                        "aborting retry.",
                    )
                    raise SystemExit(2)
                # Record the slept time so per-story duration metrics can
                # subtract it from wall time and distinguish "slow story"
                # from "story that waited on a rate-limit window."
                _add_rate_limit_sleep(wait_s)
                print(
                    f"      [bmad] *** Resuming after rate-limit wait — "
                    f"re-invoking {bmad_agent} {command}",
                )
                return invoke_bmad_agent(
                    bmad_agent=bmad_agent,
                    command=command,
                    tools=tools,
                    working_dir=working_dir,
                    timeout=timeout,
                    extra_context=extra_context,
                    model=model,
                    _rate_limit_retries=_rate_limit_retries + 1,
                )

        print(
            f"\n      [bmad] *** HALT: Anthropic auth/rate-limit signal "
            f"detected: '{match}'",
        )
        print(
            "      [bmad] *** Force-quitting the pipeline. "
            "Resume after the auth window lifts.",
        )
        try:
            from src.intake.pause import request_force_quit
            from src.multi_agent.proc_registry import kill_all
            from src.web_relay import stop_relay
            request_force_quit()
            kill_all()
            stop_relay("paused")
        except Exception:
            pass
        raise SystemExit(2)

    # Extract and display agent identification if present
    ident = _extract_agent_identification(output)
    if ident:
        print(f"\n      --- AGENT IDENTIFICATION: {bmad_agent} ---")
        for line in ident.splitlines():
            print(f"      {line}")
        print("      --- END IDENTIFICATION ---\n")
    else:
        print(f"      [bmad] WARNING: No agent identification block found in {bmad_agent} output")

    return {
        "output": output,
        "files_modified": files_modified,
        "success": success,
        "exit_code": exit_code,
    }


def invoke_claude_cli(
    prompt: str,
    tools: str,
    working_dir: str | None = None,
    timeout: int = TIMEOUT_MEDIUM,
    model: str | None = None,
    label: str = "claude",
) -> dict[str, Any]:
    """Invoke Claude CLI directly (no BMAD skill wrapper).

    Used for agents that don't need a BMAD persona — plain Claude
    review, analysis/classification, architect decisions.

    Args:
        prompt: The full prompt to send to Claude CLI.
        tools: Comma-separated tool permission string.
        working_dir: Working directory for the Claude CLI process.
        timeout: Maximum execution time in seconds.
        model: Optional model override (e.g. "opus", "sonnet").
        label: Label for log output (e.g. "claude-review", "analyze").

    Returns:
        Dict with keys: output (str), files_modified (list[str]),
        success (bool), exit_code (int).
    """
    cwd = working_dir or os.getcwd()

    model_label = f" (model={model})" if model else ""
    print(f"\n      [{label}] === INVOCATION START ===")
    print(f"      [{label}] Tools: {tools}")
    print(f"      [{label}] Timeout: {timeout}s | CWD: {cwd}{model_label}")
    print(f"      [{label}] --- PROMPT ---")
    for line in prompt.splitlines():
        print(f"      [{label}]   {line}")
    print(f"      [{label}] --- END PROMPT ---")
    start_time = time.time()

    output_chunks: list[str] = []
    stderr_lines: list[str] = []

    try:
        cli_args = [
            CLAUDE_BIN, "--print", "--verbose",
            "--output-format", "stream-json",
            "--setting-sources", "project",
            "--allowedTools", tools,
        ]
        if model:
            cli_args.extend(["--model", model])
        # Prompt via stdin — see note in _invoke_bmad_streaming above.

        proc = subprocess.Popen(
            cli_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            stdin=subprocess.PIPE,
            env=_subprocess_env(),
        )
        register(proc)

        assert proc.stdin is not None
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except OSError as e:
            logger.warning("Failed to send prompt to claude stdin: %s", e)

        # Watchdog: kill subprocess on force-quit (second Ctrl+C)
        def _watchdog() -> None:
            force_quit_event.wait()
            if proc.poll() is None:
                print(f"\n      [{label}] Force-quit: killing subprocess...")
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except OSError:
                    pass

        watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
        watchdog_thread.start()

        def _drain_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    stderr_lines.append(line)
                    print(f"      [{label}:err] {line[:500]}")

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        assert proc.stdout is not None
        for raw_line in proc.stdout:
            raw_line = raw_line.rstrip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
                _print_stream_event(
                    event, label, start_time, output_chunks,
                    requested_model=model,
                )
            except json.JSONDecodeError:
                print(f"      [{label}:raw] {raw_line[:500]}")
                output_chunks.append(raw_line)

        proc.wait(timeout=30)
        stderr_thread.join(timeout=5)
        unregister(proc)

        exit_code = proc.returncode
        success = exit_code == 0

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"      [{label}] TIMEOUT after {elapsed:.0f}s")
        proc.kill()
        proc.wait()
        unregister(proc)
        output_chunks.append(f"TIMEOUT: Claude CLI did not respond within {timeout}s")
        success = False
        exit_code = 124

    except Exception as e:
        print(f"      [{label}] ERROR: {e}")
        output_chunks.append(f"ERROR: Failed to invoke Claude CLI: {e}")
        success = False
        exit_code = 1

    output = "\n".join(output_chunks)
    elapsed = time.time() - start_time
    print(f"\n      [{label}] Finished in {elapsed:.1f}s (exit={exit_code})")

    files_modified = _detect_modified_files(cwd)
    print(
        f"      [{label}] Complete: exit={exit_code} "
        f"files_modified={len(files_modified)} output_len={len(output)}"
    )

    # Empty-output sanity: exit=0 with zero output means the subprocess
    # was pause-killed or crashed silently. Downgrade to failure.
    if success and len(output.strip()) == 0:
        print(
            f"      [{label}] WARNING: exit=0 but output_len=0 — "
            f"treating as failure (likely pause-kill or silent crash)",
        )
        success = False

    return {
        "output": output,
        "files_modified": files_modified,
        "success": success,
        "exit_code": exit_code,
    }


def invoke_ci_with_fix(
    ci_command: list[str],
    fix_tools: str = TOOLS_CI_FIX,
    working_dir: str | None = None,
    max_attempts: int = 4,
    fix_timeout: int = TIMEOUT_LONG,
    scope_hint: str = "",
    fix_pre_existing: bool = True,
    bash_timeout: int = 300,
) -> dict[str, Any]:
    """Run CI via bash, invoking BMAD dev agent only on failure.

    Implements the "bash first, LLM on failure" pattern from
    looper/build-loop.sh Phase 7.

    Args:
        ci_command: Command to run CI (e.g. ["pytest", "tests/", "-v"]).
        fix_tools: Tool permissions for the fix agent.
        working_dir: Working directory for commands.
        max_attempts: Maximum CI+fix cycles before giving up.
        fix_timeout: Timeout for the LLM fix call.
        scope_hint: Label used for ci-output filename and (when
            ``fix_pre_existing`` is False) for the scope-constraint
            message passed to the fix agent. Example: "story 1-3"
            or "epic 1".
        fix_pre_existing: When True (greenfield default), the fix
            agent is told to fix every error CI reports. When False
            (brownfield-rebuild mode), a scope constraint tells the
            agent to ignore failures outside ``scope_hint``.
        bash_timeout: Wall-clock seconds before the CI subprocess is
            killed. Per-attempt; the retry loop runs up to
            ``max_attempts`` of these.

    Returns:
        Dict with keys: passed (bool), ci_output (str), ci_output_path (str),
        attempts (int), files_modified (list[str]).
    """
    cwd = working_dir or os.getcwd()
    all_files_modified: list[str] = []

    for attempt in range(1, max_attempts + 1):
        logger.info("CI attempt %d of %d", attempt, max_attempts)

        # Run CI (bash — no LLM)
        try:
            result = subprocess.run(
                ci_command,
                capture_output=True,
                text=True,
                timeout=bash_timeout,
                cwd=cwd,
                encoding="utf-8",
                errors="replace",
            )
            ci_output = result.stdout
            if result.stderr:
                ci_output += "\n" + result.stderr
            passed = result.returncode == 0
        except subprocess.TimeoutExpired:
            ci_output = (
                f"CI command timed out after {bash_timeout}s: "
                f"{' '.join(ci_command)}"
            )
            passed = False
        except Exception as e:
            ci_output = f"CI command failed: {e}"
            passed = False

        if passed:
            logger.info("CI passed on attempt %d", attempt)
            return {
                "passed": True,
                "ci_output": ci_output,
                "attempts": attempt,
                "files_modified": all_files_modified,
            }

        # CI failed — invoke LLM to fix (only if we have attempts left)
        if attempt < max_attempts:
            logger.info("CI failed, invoking BMAD dev agent to fix...")

            scope_constraint = ""
            if scope_hint and not fix_pre_existing:
                scope_constraint = (
                    f"\n\nIMPORTANT SCOPE CONSTRAINT: Fix every failure "
                    f"caused by {scope_hint}. This includes:\n"
                    f"  - Failures in files you created or modified for "
                    f"this work.\n"
                    f"  - Failures in OTHER files (tests, route handlers, "
                    f"queries) that became broken because of a "
                    f"type/schema/signature change introduced by "
                    f"{scope_hint}. These are downstream effects of "
                    f"your work — IN SCOPE — fix them even when the "
                    f"failing file lives outside the primary area.\n\n"
                    f"Do NOT fix failures unrelated to {scope_hint}'s "
                    f"changes — a test that was already failing before "
                    f"this work started, in code you did not touch, with "
                    f"errors unrelated to your type or schema changes.\n\n"
                    f"Rule of thumb: if the error message mentions a "
                    f"field, column, type, interface, or function that "
                    f"YOU added or modified in {scope_hint}, it IS in "
                    f"scope — fix it. Global typechecks like "
                    f"`tsc --noEmit` surface errors in every mock that "
                    f"constructs a type you changed; all of those are "
                    f"yours to fix."
                )

            # Write CI output to file so the LLM reads on demand
            ci_out_dir = os.path.join(cwd, "checkpoints")
            os.makedirs(ci_out_dir, exist_ok=True)
            safe_hint = re.sub(r"[^\w\-]", "_", scope_hint) if scope_hint else "ci"
            ci_out_file = f"ci-output-{safe_hint}.txt"
            ci_out_path = os.path.join(ci_out_dir, ci_out_file)
            with open(ci_out_path, "w", encoding="utf-8") as f:
                f.write(ci_output)
            ci_rel_path = os.path.join("checkpoints", ci_out_file)

            fix_context = (
                f"CI failed. The full CI output is saved at "
                f"`{ci_rel_path}`. Read that file to understand "
                f"the errors.\n\n"
                f"Fix all errors reported by the CI pipeline — this may "
                f"include lint errors, type-check errors, security scan "
                f"findings, and test failures. Read the output carefully "
                f"to determine which tools reported issues.\n\n"
                f"Do NOT run `git add` or `git commit`. Any file you "
                f"modify, create, or leave untracked in the working tree "
                f"is auto-staged by a downstream commit step. Spending "
                f"cycles trying to stage files yourself is wasted work — "
                f"the factory observed an Epic 11 batch 1 halt where the "
                f"fix agent burned an attempt retrying `git add` for an "
                f"untracked Playwright snapshot that the next CI run "
                f"would have picked up from disk automatically."
                f"{scope_constraint}"
            )

            fix_result = invoke_bmad_agent(
                bmad_agent="bmad-agent-dev",
                command="Fix CI failures",
                tools=fix_tools,
                working_dir=working_dir,
                timeout=fix_timeout,
                extra_context=fix_context,
            )
            all_files_modified.extend(fix_result.get("files_modified", []))

    logger.error("CI failed after %d attempts", max_attempts)
    # Write final failure output to file for downstream consumers
    ci_out_dir = os.path.join(cwd, "checkpoints")
    os.makedirs(ci_out_dir, exist_ok=True)
    safe_hint = re.sub(r"[^\w\-]", "_", scope_hint) if scope_hint else "ci"
    ci_out_file = f"ci-output-{safe_hint}.txt"
    ci_out_path = os.path.join(ci_out_dir, ci_out_file)
    with open(ci_out_path, "w", encoding="utf-8") as f:
        f.write(ci_output)
    ci_rel_path = os.path.join("checkpoints", ci_out_file)
    return {
        "passed": False,
        "ci_output": ci_output,
        "ci_output_path": ci_rel_path,
        "attempts": max_attempts,
        "files_modified": all_files_modified,
    }


def _detect_modified_files(working_dir: str) -> list[str]:
    """Detect modified/untracked files via git in the working directory."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        files = [f.strip() for f in result.stdout.splitlines() if f.strip()]

        result2 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        files.extend(f.strip() for f in result2.stdout.splitlines() if f.strip())

        return sorted(set(files))
    except Exception as e:
        logger.warning("Failed to detect modified files: %s", e)
        return []
