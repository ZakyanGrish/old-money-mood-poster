#!/usr/bin/env python3
"""Post the next due item from content/queue.json, then mark it posted.

Designed to be run on a schedule (GitHub Actions cron / crontab). One item per run:
the cron cadence IS the posting cadence, so just keep the queue filled.

queue.json is a JSON array of items:
    {
      "id": "2026-02-01-rules",     # unique, your choice
      "type": "reel",               # reel | image | carousel | story
      "media_url": "https://.../rules.mp4",       # reel / image / story
      "media_urls": ["https://.../1.jpg", "..."], # carousel only (2-10)
      "caption": "text ...",         # ignored for story
      "not_before": "2026-02-01T17:00:00Z",  # optional ISO-8601 UTC gate
      "posted_at": null,            # set by this script
      "result_id": null             # set by this script
    }

Exit codes: 0 = posted or nothing due, 1 = a post was attempted and failed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smposter.config import get_account  # noqa: E402
from smposter.meta import MetaClient, MetaError  # noqa: E402

QUEUE_PATH = Path(__file__).resolve().parent.parent / "content" / "queue.json"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso(s: str) -> dt.datetime:
    s = s.strip().replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _due(item: dict, now: dt.datetime) -> bool:
    if item.get("posted_at"):
        return False
    nb = item.get("not_before")
    if nb and _parse_iso(nb) > now:
        return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True)
    ap.add_argument("--queue", default=str(QUEUE_PATH))
    ap.add_argument("--dry-run", action="store_true", help="show the next item, do not post")
    args = ap.parse_args(argv)

    qpath = Path(args.queue)
    if not qpath.exists():
        print("No queue file at %s — nothing to do." % qpath)
        return 0

    items = json.loads(qpath.read_text() or "[]")
    now = _now()
    nxt = next((it for it in items if _due(it, now)), None)
    if nxt is None:
        print("Queue: %d items, none due right now." % len(items))
        return 0

    print("Next due: id=%s type=%s" % (nxt.get("id"), nxt.get("type")))
    if args.dry_run:
        print(json.dumps(nxt, indent=2))
        return 0

    acct = get_account(args.account)
    client = MetaClient(acct.access_token)
    t = (nxt.get("type") or "").lower()

    try:
        if t == "reel":
            res = client.post_reel(acct.ig_user_id, nxt["media_url"], nxt.get("caption", ""))
        elif t == "image":
            res = client.post_image(acct.ig_user_id, nxt["media_url"], nxt.get("caption", ""))
        elif t == "carousel":
            res = client.post_carousel(acct.ig_user_id, nxt["media_urls"], nxt.get("caption", ""))
        elif t == "story":
            url = nxt["media_url"]
            is_video = url.lower().split("?")[0].endswith((".mp4", ".mov"))
            res = client.post_story(
                acct.ig_user_id,
                video_url=url if is_video else None,
                image_url=None if is_video else url,
            )
        else:
            print("Unknown item type: %r" % t)
            return 1
    except (MetaError, KeyError) as e:
        print("POST FAILED for id=%s: %s" % (nxt.get("id"), e))
        return 1

    nxt["posted_at"] = now.isoformat()
    nxt["result_id"] = res.get("id")
    qpath.write_text(json.dumps(items, indent=2) + "\n")
    print("Published id=%s -> media %s" % (nxt.get("id"), res.get("id")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
