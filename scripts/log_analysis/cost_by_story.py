"""Sum agent dollar costs per story, given a relay log dump.

Usage:
    python -m scripts.log_analysis.cost_by_story <dump.json>

Output:
    A table of (story_id, total_dollars, invocation_count) rows plus a total.

Useful for:
- Identifying expensive stories (heavy fix_ci loops, large dev_story passes)
- Comparing cost per story across runs
- Estimating remaining build cost from current spend trajectory
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

COST_RE = re.compile(r"RESULT: (\w+) \((\d+) turns, \$([\d.]+)\)")
STORY_RE = re.compile(r"STORY (\d+-\d+):")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.log_analysis.cost_by_story <dump.json>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("events", [])
    print(f"Session {data.get('session_id', '?')[:8]}…  {len(events)} events")

    costs: dict[str, list[float]] = defaultdict(list)
    current_story: str | None = None

    for e in events:
        text = e.get("text", "")
        story_match = STORY_RE.search(text)
        if story_match:
            current_story = story_match.group(1)
            continue

        cost_match = COST_RE.search(text)
        if cost_match and current_story:
            cost = float(cost_match.group(3))
            costs[current_story].append(cost)

    if not costs:
        print("No story-tagged costs found in this dump.")
        return

    print()
    print(f"{'Story':<10}  {'Cost':>10}  {'Invocations':>12}")
    print("-" * 40)

    total = 0.0
    for story in sorted(costs.keys(), key=lambda s: tuple(int(x) for x in s.split("-"))):
        amounts = costs[story]
        sub = sum(amounts)
        total += sub
        print(f"{story:<10}  ${sub:>9.2f}  {len(amounts):>12}")

    print("-" * 40)
    print(f"{'TOTAL':<10}  ${total:>9.2f}  {sum(len(v) for v in costs.values()):>12}")


if __name__ == "__main__":
    main()
