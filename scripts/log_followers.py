#!/usr/bin/env python3
"""Append today's follower count to content/followers.json.

Run on every poster run. Keeps one entry per calendar day (updates it if the
day already has one), so a real growth curve accumulates over time. The
dashboard/report use this series to show measured growth and to replace the
assumed projection rate with the observed one once enough days exist.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smposter.config import load_env  # noqa: E402
from smposter.meta import MetaClient, MetaError  # noqa: E402

IG_USER_ID = "17841477100835322"
LOG = Path(__file__).resolve().parent.parent / "content" / "followers.json"


def main() -> int:
    load_env()
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        print("No META_ACCESS_TOKEN; skipping follower log.")
        return 0
    try:
        d = MetaClient(token)._call(
            "GET", IG_USER_ID, fields="followers_count,media_count,follows_count"
        )
    except MetaError as e:
        print("Could not read followers: %s" % e)
        return 0

    now = dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    entry = {
        "date": today,
        "t": now.isoformat(),
        "followers": d.get("followers_count"),
        "following": d.get("follows_count"),
        "media": d.get("media_count"),
    }

    series = json.loads(LOG.read_text() or "[]") if LOG.exists() else []
    if series and series[-1].get("date") == today:
        series[-1] = entry            # refresh today's point
    else:
        series.append(entry)          # new day
    LOG.write_text(json.dumps(series, indent=1) + "\n")
    print("followers=%s  media=%s  (%d days logged)" % (
        entry["followers"], entry["media"], len(series)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
