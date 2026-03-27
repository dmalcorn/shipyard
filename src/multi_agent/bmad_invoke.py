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
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default timeout (seconds) per agent type
# ---------------------------------------------------------------------------
TIMEOUT_SHORT = 15 * 60   # 15 min — story creation, test review
TIMEOUT_MEDIUM = 25 * 60  # 25 min — code review, test automation
TIMEOUT_LONG = 45 * 60    # 45 min — implementation, CI fix

# ---------------------------------------------------------------------------
# Scoped tool permissions per phase (from looper/build-loop.sh)
# ---------------------------------------------------------------------------
TOOLS_SM = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Skill"
TOOLS_TEA = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(npm *),Bash(npx *),Bash(pytest *),Bash(make *),Skill"
TOOLS_TEA_FIX = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(npm *),Bash(npx *),Bash(pytest *),Bash(make *),Skill"
TOOLS_DEV = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pip *),Bash(npm *),Bash(npx *),Bash(pytest *),Bash(make *),Bash(git *),Skill"
TOOLS_CODE_REVIEW = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(npm *),Bash(npx *),Bash(pytest *),Bash(make *),Skill"
TOOLS_CI_FIX = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pip *),Bash(npm *),Bash(npx *),Bash(pytest *),Bash(ruff *),Bash(mypy *),Skill"
TOOLS_REVIEW_READONLY = "Read,Glob,Grep,Task,TodoWrite"


def _print_stream_event(
    event: dict[str, Any],
    agent_name: str,
    start_time: float,
    output_chunks: list[str],
) -> None:
    """Parse a stream-json event and print meaningful content in real-time.

    Only prints actionable information: agent text output, tool usage,
    and final results. Silently skips noise (user messages, progress pings).
    """
    elapsed = time.time() - start_time
    tag = f"[{agent_name} {elapsed:5.0f}s]"

    msg_type = event.get("type", "")
    subtype = event.get("subtype", "")

    # --- Init: one-liner that agent session started ---
    if msg_type == "system" and subtype == "init":
        model = event.get("model", "?")
        print(f"      {tag} Session started (model={model})")
        return

    # --- Final result: show summary and capture output ---
    if msg_type == "result":
        result_text = event.get("result", "")
        cost = event.get("total_cost_usd", 0)
        turns = event.get("num_turns", 0)
        status = subtype  # "success" or "error"
        print(f"      {tag} RESULT: {status} ({turns} turns, ${cost:.4f})")
        if result_text:
            # Show first 300 chars of result
            preview = result_text[:300].replace("\n", "\n      " + " " * len(tag) + " ")
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
                    preview = text[:200].replace("\n", "\n      " + " " * len(tag) + " ")
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
                        summary = str(tool_input)[:120]
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


def _build_bmad_prompt(
    agent_command: str,
    bmad_agent: str,
    extra_context: str = "",
) -> str:
    """Build a BMAD-style agent invocation prompt.

    Args:
        agent_command: The BMAD command to execute (e.g. "DS for story 2-1").
        bmad_agent: The BMAD agent slash command (e.g. "bmad-dev").
        extra_context: Optional additional context appended to the prompt.
    """
    prompt = (
        f"IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE "
        f"TO INVOKE THE BMAD AGENT.\n\n"
        f"Step 1: Use the Skill tool to invoke '{bmad_agent}'\n\n"
        f"Step 2: Execute command: {agent_command}\n\n"
        f"Step 3: After completing your work, end your response with "
        f"this AGENT IDENTIFICATION block:\n\n"
        f"=== AGENT IDENTIFICATION ===\n"
        f"Agent: [Your agent type, e.g., DEV Agent]\n"
        f"Persona: [Your persona name from the agent file]\n"
        f"Loaded files:\n"
        f"  - [exact path to each file you read during activation]\n"
        f"=== END IDENTIFICATION ===\n\n"
        f"Mode: Automated, no menus, no questions, always fix issues "
        f"automatically, no waiting for user input."
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
) -> dict[str, Any]:
    """Invoke a BMAD agent via Claude CLI in an isolated session.

    Shells out to `claude --print --allowedTools` with a BMAD-style
    prompt. Returns the CLI output and detected file modifications.

    Args:
        bmad_agent: BMAD agent slash command (e.g. "bmad-dev").
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
    print(f"      [bmad] --- PROMPT ---")
    for line in prompt.splitlines():
        print(f"      [bmad]   {line}")
    print(f"      [bmad] --- END PROMPT ---")
    model_label = f" (model={model})" if model else ""
    print(f"      [bmad] Streaming via claude --print --output-format stream-json{model_label} ...")
    start_time = time.time()

    output_chunks: list[str] = []
    stderr_lines: list[str] = []

    try:
        cli_args = [
            "claude", "--print", "--verbose",
            "--output-format", "stream-json",
            "--setting-sources", "project",
            "--allowedTools", tools,
        ]
        if model:
            cli_args.extend(["--model", model])
        cli_args.extend(["--", prompt])

        proc = subprocess.Popen(
            cli_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            stdin=subprocess.DEVNULL,
        )

        # Stream stderr in a background thread so it doesn't block
        def _drain_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    stderr_lines.append(line)
                    print(f"      [bmad:err] {line[:200]}")

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
                _print_stream_event(event, bmad_agent, start_time, output_chunks)
            except json.JSONDecodeError:
                # Not JSON — print raw
                print(f"      [bmad:raw] {raw_line[:200]}")
                output_chunks.append(raw_line)

        proc.wait(timeout=30)
        stderr_thread.join(timeout=5)

        exit_code = proc.returncode
        success = exit_code == 0

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"      [bmad] TIMEOUT after {elapsed:.0f}s: {bmad_agent} {command}")
        proc.kill()
        proc.wait()
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

    print(f"      [bmad] Complete: exit={exit_code} files_modified={len(files_modified)} output_len={len(output)}")

    # Extract and display agent identification if present
    ident = _extract_agent_identification(output)
    if ident:
        print(f"\n      --- AGENT IDENTIFICATION: {bmad_agent} ---")
        for line in ident.splitlines():
            print(f"      {line}")
        print(f"      --- END IDENTIFICATION ---\n")
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
            "claude", "--print", "--verbose",
            "--output-format", "stream-json",
            "--setting-sources", "project",
            "--allowedTools", tools,
        ]
        if model:
            cli_args.extend(["--model", model])
        cli_args.extend(["--", prompt])

        proc = subprocess.Popen(
            cli_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            stdin=subprocess.DEVNULL,
        )

        def _drain_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    stderr_lines.append(line)
                    print(f"      [{label}:err] {line[:200]}")

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        assert proc.stdout is not None
        for raw_line in proc.stdout:
            raw_line = raw_line.rstrip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
                _print_stream_event(event, label, start_time, output_chunks)
            except json.JSONDecodeError:
                print(f"      [{label}:raw] {raw_line[:200]}")
                output_chunks.append(raw_line)

        proc.wait(timeout=30)
        stderr_thread.join(timeout=5)

        exit_code = proc.returncode
        success = exit_code == 0

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"      [{label}] TIMEOUT after {elapsed:.0f}s")
        proc.kill()
        proc.wait()
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
    print(f"      [{label}] Complete: exit={exit_code} files_modified={len(files_modified)} output_len={len(output)}")

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

    Returns:
        Dict with keys: passed (bool), ci_output (str), attempts (int),
        files_modified (list[str]).
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
                timeout=300,
                cwd=cwd,
            )
            ci_output = result.stdout
            if result.stderr:
                ci_output += "\n" + result.stderr
            passed = result.returncode == 0
        except subprocess.TimeoutExpired:
            ci_output = f"CI command timed out after 300s: {' '.join(ci_command)}"
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

            fix_context = (
                f"CI failed. Here is the CI output:\n\n"
                f"```\n{ci_output[:5000]}\n```\n\n"
                f"Fix all lint errors (ruff), type errors (mypy), "
                f"and test failures."
            )

            fix_result = invoke_bmad_agent(
                bmad_agent="bmad-dev",
                command="Fix CI failures",
                tools=fix_tools,
                working_dir=working_dir,
                timeout=fix_timeout,
                extra_context=fix_context,
            )
            all_files_modified.extend(fix_result.get("files_modified", []))

    logger.error("CI failed after %d attempts", max_attempts)
    return {
        "passed": False,
        "ci_output": ci_output,
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
