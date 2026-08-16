#!/usr/bin/env python3
import sys

from scripts.publish_slot import run

SLOTS = {
    "07:00": ["topic1-long", "topic1-short", "topic1-instagram"],
    "12:00": ["topic2-long", "topic2-short", "topic2-instagram"],
    "19:00": ["topic3-long", "topic3-short", "topic3-instagram"],
}


def publish_slot(slot):
    if slot not in SLOTS:
        raise SystemExit("Usage: publish_today.py 07:00|12:00|19:00")
    for job in SLOTS[slot]:
        if job.endswith("-long") or job.endswith("-short"):
            print(f"skip {job}: YouTube uses API schedule via scripts/schedule_youtube_today.py")
            continue
        run(job)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: publish_today.py 07:00|12:00|19:00")
    publish_slot(sys.argv[1])
