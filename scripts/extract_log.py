"""Fetch all events for a relay session and write them to a JSON file."""

import json
import sys
import urllib.request

BASE_URL = "https://shipyard-production-29ae.up.railway.app"


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python extract_log.py <session_id> <output_file>")
        sys.exit(1)

    session_id = sys.argv[1]
    output_file = sys.argv[2]

    all_events: list[dict] = []
    after_id = 0

    while True:
        url = f"{BASE_URL}/api/logs/{session_id}?after_id={after_id}"
        resp = urllib.request.urlopen(urllib.request.Request(url), timeout=180)
        data = json.loads(resp.read())
        events = data.get("events", [])
        if not events:
            break
        all_events.extend(events)
        after_id = data.get("latest_id", events[-1]["id"])
        print(f"  Fetched {len(all_events)} events (latest_id: {after_id})")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "session_id": session_id,
                "event_count": len(all_events),
                "events": all_events,
            },
            f,
            indent=2,
        )

    print(f"Done: {len(all_events)} events -> {output_file}")


if __name__ == "__main__":
    main()
