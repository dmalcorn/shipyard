"""Fetch events for a relay session and write them to a JSON file.

Two modes:
  - Full pull (default):
      python extract_log.py <session_id> <output_file>
    Pulls every event for the session.

  - Incremental pull (recommended for active monitoring):
      python extract_log.py <session_id> <output_file> --incremental
    Reads <output_file>'s existing events (if any), pulls only events
    with id > the highest seen, appends, and rewrites. Resumable across
    invocations — safe to run repeatedly while a session is live.

Use --since <id> to override the resumption point manually:
      python extract_log.py <session_id> <output_file> --since 75000
    Useful for grabbing a slice of events from a known marker.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from typing import Any

BASE_URL = "https://shipyard-production-29ae.up.railway.app"


def fetch_page(session_id: str, after_id: int) -> dict[str, Any]:
    """Fetch one page of events from the relay."""
    url = f"{BASE_URL}/api/logs/{session_id}?after_id={after_id}"
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=180)
    return json.loads(resp.read())


def load_existing(output_file: str) -> tuple[list[dict[str, Any]], int]:
    """Read events from an existing dump; return (events, max_id_seen).

    Returns ([], 0) if the file doesn't exist or is unreadable.
    """
    if not os.path.isfile(output_file):
        return [], 0
    try:
        with open(output_file, encoding="utf-8") as f:
            data = json.load(f)
        events = data.get("events", [])
        max_id = max((e.get("id", 0) for e in events), default=0)
        return events, max_id
    except (OSError, json.JSONDecodeError):
        return [], 0


def fetch_all(session_id: str, start_after_id: int) -> list[dict[str, Any]]:
    """Page through events starting after start_after_id, returning the new ones."""
    new_events: list[dict[str, Any]] = []
    after_id = start_after_id
    while True:
        data = fetch_page(session_id, after_id)
        events = data.get("events", [])
        if not events:
            break
        new_events.extend(events)
        after_id = data.get("latest_id", events[-1]["id"])
        print(f"  Fetched {len(new_events)} new events (latest_id: {after_id})")
    return new_events


def write_dump(output_file: str, session_id: str, events: list[dict[str, Any]]) -> None:
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "session_id": session_id,
                "event_count": len(events),
                "events": events,
            },
            f,
            indent=2,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("session_id", help="Relay session UUID")
    parser.add_argument("output_file", help="Path to write the JSON dump")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Resume from the highest event id already in <output_file>; "
            "append only newer events. Safe to run repeatedly while a "
            "session is live."
        ),
    )
    parser.add_argument(
        "--since",
        type=int,
        default=None,
        help=(
            "Manually specify the starting after_id. Overrides --incremental "
            "if both are given. Use 0 for a full pull."
        ),
    )
    args = parser.parse_args()

    if args.since is not None:
        # Manual override: ignore existing dump, start from --since
        existing: list[dict[str, Any]] = []
        start_after = args.since
        print(f"Manual --since {start_after}: pulling fresh from event id {start_after}")
    elif args.incremental:
        existing, max_seen = load_existing(args.output_file)
        start_after = max_seen
        print(
            f"Incremental: {len(existing)} existing events, "
            f"resuming after id {start_after}",
        )
    else:
        existing = []
        start_after = 0
        print("Full pull")

    new_events = fetch_all(args.session_id, start_after)

    if args.incremental and existing:
        all_events = existing + new_events
        # Defensive de-dup by event id (in case relay returns overlap)
        seen: set[int] = set()
        deduped: list[dict[str, Any]] = []
        for e in all_events:
            eid = e.get("id")
            if eid in seen:
                continue
            seen.add(eid)
            deduped.append(e)
        all_events = sorted(deduped, key=lambda e: e.get("id", 0))
    else:
        all_events = new_events

    write_dump(args.output_file, args.session_id, all_events)
    print(
        f"Done: {len(new_events)} new event(s) fetched, "
        f"{len(all_events)} total -> {args.output_file}",
    )


if __name__ == "__main__":
    main()
