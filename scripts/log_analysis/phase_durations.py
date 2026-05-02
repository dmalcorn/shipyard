"""Wall-clock time per pipeline phase, per story.

Usage:
    python -m scripts.log_analysis.phase_durations <dump.json>

Output:
    Per-story breakdown of how long each phase took (dev_story, run_ci,
    fix_ci, code_review, git_commit, etc.) plus a summary across all stories.

Useful for:
- Spotting the slow phase in a build (almost always dev_story)
- Comparing dev_story duration across stories of similar complexity
- Estimating wall-clock for an upcoming epic from prior epic's pattern
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime

# Phase markers we count (line patterns + the timestamp of the matching line)
PHASE_PATTERNS = {
    "dev_story":     re.compile(r">>> \[dev_story\] Invoking"),
    "code_review":   re.compile(r">>> \[code_review\] (Invoking|Skipped)"),
    "run_ci":        re.compile(r">>> \[run_ci\] Running CI"),
    "fix_ci":        re.compile(r">>> \[fix_ci\] Invoking"),
    "git_commit":    re.compile(r">>> \[git_commit\] Committing"),
}
END_RE = re.compile(r"STORY RESULT: (\d+-\d+)")
STORY_RE = re.compile(r"STORY (\d+-\d+):")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.log_analysis.phase_durations <dump.json>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("events", [])
    print(f"Session {data.get('session_id', '?')[:8]}…  {len(events)} events")

    # Per (story, phase) -> list of (start_time, end_time) intervals.
    # We don't have explicit phase-end markers, so we approximate end time
    # as the start of the next phase, or STORY RESULT for the final phase.
    story_phase_events: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    current_story: str | None = None

    for e in events:
        text = e.get("text", "")
        ts_s = e.get("created_at", "")
        if not ts_s:
            continue

        m = STORY_RE.search(text)
        if m:
            current_story = m.group(1)
            story_phase_events[current_story]  # ensure key exists
            continue

        if not current_story:
            continue

        for phase, pat in PHASE_PATTERNS.items():
            if pat.search(text):
                story_phase_events[current_story].append((phase, parse_iso(ts_s)))
                break

        if END_RE.search(text):
            story_phase_events[current_story].append(("__end__", parse_iso(ts_s)))

    # Compute durations
    total_by_phase: dict[str, float] = defaultdict(float)
    print()
    print(
        f"{'Story':<10}  {'dev_story':>10}  {'code_rev':>9}  "
        f"{'run_ci':>8}  {'fix_ci':>8}  {'git_cmt':>8}",
    )
    print("-" * 70)

    def _story_sort_key(s: str) -> tuple[int, ...]:
        return tuple(int(x) for x in s.split("-"))

    def _fmt_duration(per_phase: dict[str, float], p: str) -> str:
        sec = per_phase.get(p, 0.0)
        return f"{sec:.0f}s" if sec else "-"

    for story in sorted(story_phase_events.keys(), key=_story_sort_key):
        seq = story_phase_events[story]
        if len(seq) < 2:
            continue
        per_phase: dict[str, float] = defaultdict(float)
        for i, (phase, t) in enumerate(seq):
            if phase == "__end__":
                continue
            t_next = seq[i + 1][1] if i + 1 < len(seq) else None
            if t_next is None:
                continue
            duration = (t_next - t).total_seconds()
            per_phase[phase] += duration
            total_by_phase[phase] += duration

        f = _fmt_duration
        print(
            f"{story:<10}  {f(per_phase, 'dev_story'):>10}  "
            f"{f(per_phase, 'code_review'):>9}  "
            f"{f(per_phase, 'run_ci'):>8}  "
            f"{f(per_phase, 'fix_ci'):>8}  "
            f"{f(per_phase, 'git_commit'):>8}",
        )

    if not story_phase_events:
        print("No phase events found.")
        return

    print()
    print("Total time by phase across all stories:")
    grand_total = sum(total_by_phase.values())
    for phase in ("dev_story", "code_review", "run_ci", "fix_ci", "git_commit"):
        sec = total_by_phase.get(phase, 0.0)
        pct = (sec / grand_total * 100) if grand_total else 0
        print(f"  {phase:<14}  {sec:>8.0f}s  ({pct:>5.1f}%)")
    print(f"  {'GRAND TOTAL':<14}  {grand_total:>8.0f}s  ({grand_total / 3600:.2f}h)")


if __name__ == "__main__":
    main()
