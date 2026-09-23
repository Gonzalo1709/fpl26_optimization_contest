"""Summarize explicit server command events, never infer timeouts by duration.

Usage: python tools/meemar_timeline.py path/to/vivado-mcp.log
"""

import argparse
import json
from pathlib import Path


def command_events(text):
    for line in text.splitlines():
        if "FPL26_COMMAND_EVENT=" not in line:
            continue
        try:
            event = json.loads(line.split("FPL26_COMMAND_EVENT=", 1)[1])
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("command_id"):
            yield event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    events = list(command_events(args.log.read_text(encoding="utf-8", errors="replace")))
    for event in events:
        print(json.dumps(event, sort_keys=True))
    if not events:
        print("No explicit command events; historical runtime attribution is unknown.")


if __name__ == "__main__":
    main()
