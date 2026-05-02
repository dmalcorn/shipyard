"""Surface fix_ci cycle counts and common failure signatures.

Usage:
    python -m scripts.log_analysis.failure_patterns <dump.json>

Output:
    Per-story fix_ci cycle counts (how many times CI failed before passing)
    plus a summary of which stories hit the max retry limit.

Useful for:
- Spotting stories that needed multiple fix_ci passes (signal of
  ambiguous specs or schema-drift cascades)
- Identifying the per-cycle CI duration to spot timeouts
- Comparing fix_ci behavior between runs after a factory change
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime

CYCLE_RUN_RE = re.compile(r"\[run_ci\] Running CI \(cycle=(\d+)\)")
CYCLE_RES_RE = re.compile(r"\[run_ci\] Result: (\w+) \(cycle=(\d+)\)")
STORY_RE = re.compile(r"STORY (\d+-\d+):")
PIPELINE_FAIL_RE = re.compile(r"Pipeline failed at phase=run_ci for task=(\d+-\d+)")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.log_analysis.failure_patterns <dump.json>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("events", [])
    print(f"Session {data.get('session_id', '?')[:8]}…  {len(events)} events")
    print()

    current_story: str | None = None
    cycle_starts: dict[tuple[str, int], datetime] = {}
    cycle_results: dict[str, list[tuple[int, str, float]]] = defaultdict(list)
    given_up: set[str] = set()

    for e in events:
        text = e.get("text", "")
        ts = e.get("created_at", "")

        m = STORY_RE.search(text)
        if m:
            current_story = m.group(1)
            continue

        m = CYCLE_RUN_RE.search(text)
        if m and current_story and ts:
            cycle = int(m.group(1))
            cycle_starts[(current_story, cycle)] = parse_iso(ts)
            continue

        m = CYCLE_RES_RE.search(text)
        if m and current_story and ts:
            result = m.group(1)
            cycle = int(m.group(2))
            start = cycle_starts.get((current_story, cycle))
            duration = (parse_iso(ts) - start).total_seconds() if start else 0.0
            cycle_results[current_story].append((cycle, result, duration))
            continue

        m = PIPELINE_FAIL_RE.search(text)
        if m:
            given_up.add(m.group(1))

    print(f"{'Story':<10}  {'Cycles':>6}  {'Final':>6}  {'Total CI s':>10}  Cycle breakdown")
    print("-" * 80)

    multi_cycle = 0
    for story in sorted(cycle_results.keys(), key=lambda s: tuple(int(x) for x in s.split("-"))):
        cycles = cycle_results[story]
        final = cycles[-1][1] if cycles else "?"
        total_s = sum(d for _, _, d in cycles)
        breakdown = ", ".join(f"c{c}={r[:1]}{d:.0f}s" for c, r, d in cycles)
        marker = "  *** GAVE UP" if story in given_up else ""
        print(
            f"{story:<10}  {len(cycles):>6}  {final:>6}  {total_s:>10.1f}  "
            f"{breakdown}{marker}",
        )
        if len(cycles) > 1:
            multi_cycle += 1

    print()
    print(f"{multi_cycle} of {len(cycle_results)} stories needed >1 CI cycle")
    if given_up:
        print(
            f"{len(given_up)} stories hit the max retry limit "
            f"(Pipeline failed): {sorted(given_up)}",
        )
    else:
        print("No stories hit the max retry limit")


if __name__ == "__main__":
    main()
