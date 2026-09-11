#!/usr/bin/env python3
"""Backfill `reach` and `theme` onto posted queue items.

Run daily. For each posted item older than 2 days (reach needs time to settle)
that doesn't have `reach` yet, fetch it via the Graph API and store it. Also
back-fills `theme` on older items that predate caption theming. This is what
lets build_year_schedule.py weight future picks toward themes that measurably
perform better -- with no data yet, everything stays evenly weighted.
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
from build_year_schedule import theme_of  # noqa: E402

QUEUE_PATH = Path(__file__).resolve().parent.parent / "content" / "queue.json"
SETTLE_DAYS = 2


def main() -> int:
    load_env()
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        print("No META_ACCESS_TOKEN; skipping.")
        return 0
    client = MetaClient(token)

    items = json.loads(QUEUE_PATH.read_text() or "[]") if QUEUE_PATH.exists() else []
    now = dt.datetime.now(dt.timezone.utc)
    updated = 0
    for it in items:
        if not it.get("posted_at") or not it.get("result_id"):
            continue
        if not it.get("theme"):
            it["theme"] = theme_of(it.get("caption", ""))
        if "reach" in it:
            continue
        try:
            posted = dt.datetime.fromisoformat(it["posted_at"])
        except ValueError:
            continue
        if (now - posted).total_seconds() < SETTLE_DAYS * 86400:
            continue
        try:
            it["reach"] = client.media_score(it["result_id"])
            updated += 1
        except MetaError:
            pass

    QUEUE_PATH.write_text(json.dumps(items, indent=2) + "\n")
    print("backfilled reach on %d item(s)" % updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
