"""Confirm whether the auth-halt detection fired (or didn't).

Usage:
    python -m scripts.log_analysis.auth_halt_check <dump.json>

Output:
    For each occurrence of an Anthropic auth/rate-limit signal in the dump,
    report: timestamp, the matching string, and whether the factory's
    auth-halt logic fired in response. Surfaces:

    - Successful halts (rate limit hit, factory force-quit cleanly)
    - Missed halts (rate-limit string in agent output but no halt followup —
      indicates the auth-halt detection has gaps and should be improved)
    - False positives (halt fired when it shouldn't have)

Useful for:
- Validating commit d88ce0d (auth-halt detection) on every run
- Spotting new auth/rate-limit message variants Anthropic introduces that
  we should add to the detection patterns
"""

from __future__ import annotations

import json
import re
import sys

# Match either the agent-output line OR the halt confirmation line
AGENT_AUTH_PATTERNS = [
    "does not have access to Claude",
    "You've hit your limit",
    "Please login again or contact your administrator",
]
HALT_CONFIRMATION_RE = re.compile(r"\*\*\* HALT: Anthropic auth/rate-limit signal detected")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.log_analysis.auth_halt_check <dump.json>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("events", [])
    print(f"Session {data.get('session_id', '?')[:8]}…  {len(events)} events")
    print()

    auth_hits: list[tuple[int, str, str, str]] = []  # (idx, ts, pattern, line)
    halt_lines: list[tuple[int, str]] = []  # (idx, ts)

    for i, e in enumerate(events):
        text = e.get("text", "")
        ts = e.get("created_at", "")[11:19]
        for p in AGENT_AUTH_PATTERNS:
            if p in text:
                auth_hits.append((i, ts, p, text.strip()[:200]))
                break
        if HALT_CONFIRMATION_RE.search(text):
            halt_lines.append((i, ts))

    if not auth_hits:
        print("No Anthropic auth/rate-limit signals detected — clean run.")
        return

    print(f"Found {len(auth_hits)} auth-signal event(s):")
    for idx, ts, pattern, line in auth_hits:
        print(f"\n[{ts}]  pattern: {pattern!r}")
        print(f"  event #{idx}: {line[:160]}")

        # Did a halt confirmation appear within the next 5 events?
        followup = [(hi, hts) for hi, hts in halt_lines if 0 <= hi - idx <= 5]
        if followup:
            hi, hts = followup[0]
            print(f"  -> HALT fired at [{hts}] (event #{hi}, lag {hi - idx} events)")
        else:
            print("  -> NO HALT followup detected.")
            print(
                "     Either: (a) factory was running an old version (pre-d88ce0d)\n"
                "             (b) the pattern isn't in AUTH_HALT_PATTERNS — "
                "consider adding it to bmad_invoke._AUTH_HALT_PATTERNS\n"
                "             (c) the cascade was caught by a different mechanism",
            )

    print()
    print(f"Total auth signals: {len(auth_hits)}")
    print(f"Total halts fired:  {len(halt_lines)}")
    if len(auth_hits) > len(halt_lines):
        print(
            f"WARN: {len(auth_hits) - len(halt_lines)} auth signal(s) without "
            "corresponding halt — investigate.",
        )


if __name__ == "__main__":
    main()
