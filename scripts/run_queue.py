#!/usr/bin/env python3
"""Post one item per run. Never let the account go dark.

Order of preference each run:
  1. FRESH  — the oldest queued item that is due and not yet posted.
  2. RECYCLE — if nothing fresh is due, re-post the best-performing past post
     (by reach), skipping anything posted in the last RECYCLE_COOLDOWN_DAYS.
  3. SKIP   — if even recycling has nothing eligible, post nothing this run.

Always writes content/status.json with `fresh_remaining` so the workflow can
alert when the real content pipeline is running low.

Usage:
    python scripts/run_queue.py --account oldmoneymood
    python scripts/run_queue.py --account oldmoneymood --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smposter.config import get_account  # noqa: E402
from smposter.meta import MetaClient, MetaError  # noqa: E402
from smposter.youtube import YouTubeClient, YouTubeError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = ROOT / "content" / "queue.json"
STATUS_PATH = ROOT / "content" / "status.json"

RECYCLE_COOLDOWN_DAYS = 30   # don't re-post the same media within this window
LOW_QUEUE_THRESHOLD = 3      # fresh items at or below this -> workflow raises an alert
MAX_FAILS = 3               # after this many failed attempts, skip an item and move on
CROSSPOST_FB = True         # also publish reels/images to the linked Facebook Page
CROSSPOST_YT = True         # also upload reels to YouTube as Shorts (needs YOUTUBE_* env)
POSTABLE = ("reel", "image", "carousel")  # stories are ephemeral, never recycled


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _media_key(item: dict) -> str:
    """Stable identity for a piece of media, independent of queue id."""
    raw = json.dumps(item.get("media_urls") or item.get("media_url") or "", sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _is_fresh_due(item: dict, now: dt.datetime) -> bool:
    if item.get("posted_at") or item.get("recycled_from"):
        return False
    if (item.get("type") or "").lower() not in ("reel", "image", "carousel", "story"):
        return False
    nb = item.get("not_before")
    if nb and _parse_iso(nb) > now:
        return False
    return True


def _fresh_remaining(items: list, now: dt.datetime) -> int:
    return sum(
        1
        for it in items
        if not it.get("posted_at")
        and not it.get("recycled_from")
        and (it.get("type") or "").lower() in ("reel", "image", "carousel", "story")
    )


def _post_item(client: MetaClient, ig_user_id: str, item: dict) -> dict:
    t = (item.get("type") or "").lower()
    if t == "reel":
        return client.post_reel(ig_user_id, item["media_url"], item.get("caption", ""))
    if t == "image":
        return client.post_image(ig_user_id, item["media_url"], item.get("caption", ""))
    if t == "carousel":
        return client.post_carousel(ig_user_id, item["media_urls"], item.get("caption", ""))
    if t == "story":
        url = item["media_url"]
        is_video = url.lower().split("?")[0].endswith((".mp4", ".mov"))
        return client.post_story(
            ig_user_id,
            video_url=url if is_video else None,
            image_url=None if is_video else url,
        )
    raise MetaError("Unknown item type: %r" % t)


def _pick_recycle(items: list, client: MetaClient, now: dt.datetime):
    """Return a NEW queue item cloned from the best eligible past post, or None."""
    cooldown = dt.timedelta(days=RECYCLE_COOLDOWN_DAYS)
    posted = [
        it for it in items
        if it.get("result_id") and it.get("posted_at") and (it.get("type") or "").lower() in POSTABLE
    ]
    if not posted:
        return None

    # Most recent post per media identity, and when that media was last posted.
    latest: dict = {}
    last_posted: dict = {}
    for it in posted:
        k = _media_key(it)
        ts = _parse_iso(it["posted_at"])
        if k not in last_posted or ts > last_posted[k]:
            last_posted[k] = ts
        if k not in latest or ts > _parse_iso(latest[k]["posted_at"]):
            latest[k] = it

    eligible = [it for k, it in latest.items() if now - last_posted[k] >= cooldown]
    if not eligible:
        return None

    scored = sorted(
        eligible, key=lambda it: client.media_score(it["result_id"]), reverse=True
    )
    src = scored[0]
    clone = {
        "id": "recycle-%s-%s" % (now.date().isoformat(), _media_key(src)),
        "type": src["type"],
        "caption": src.get("caption", ""),
        "recycled_from": src.get("id"),
        "not_before": None,
        "posted_at": None,
        "result_id": None,
    }
    if src.get("media_urls"):
        clone["media_urls"] = src["media_urls"]
    else:
        clone["media_url"] = src["media_url"]
    return clone


def _write_status(action: str, item_id, fresh_remaining: int, now: dt.datetime) -> None:
    STATUS_PATH.write_text(
        json.dumps(
            {
                "checked_at": now.isoformat(),
                "action": action,           # posted | recycled | skipped | failed
                "item_id": item_id,
                "fresh_remaining": fresh_remaining,
                "low_queue": fresh_remaining <= LOW_QUEUE_THRESHOLD,
            },
            indent=2,
        )
        + "\n"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    items = json.loads(QUEUE_PATH.read_text() or "[]") if QUEUE_PATH.exists() else []
    now = _now()
    fresh_left = _fresh_remaining(items, now)

    fresh = next((it for it in items if _is_fresh_due(it, now)), None)
    # A client is always useful: recycle selection reads insights even on a dry run.
    acct = get_account(args.account)
    client = MetaClient(acct.access_token)

    # ---- choose what to post -------------------------------------------------
    mode = "fresh"
    target = fresh
    if target is None:
        mode = "recycle"
        target = _pick_recycle(items, client, now)
        if args.dry_run:
            if target is None:
                print("No fresh item due; nothing eligible to recycle either.")
            else:
                print("No fresh item due. Would recycle:")
                print(json.dumps(target, indent=2))
            _write_status("dry-run", target.get("id") if target else None, fresh_left, now)
            return 0
        if target is None:
            print("Nothing due right now (fresh reserve: %d). Posting nothing this run." % fresh_left)
            if fresh_left <= LOW_QUEUE_THRESHOLD:
                print("::low-queue::%d" % fresh_left)
            _write_status("idle", None, fresh_left, now)
            return 0

    print("mode=%s id=%s type=%s" % (mode, target.get("id"), target.get("type")))
    if args.dry_run:
        print(json.dumps(target, indent=2))
        _write_status("dry-run", target.get("id"), fresh_left, now)
        return 0

    # ---- post -------------------------------------------------------------
    try:
        res = _post_item(client, acct.ig_user_id, target)
    except (MetaError, KeyError) as e:
        target["fail_count"] = int(target.get("fail_count", 0)) + 1
        target["last_error"] = str(e)
        give_up = target["fail_count"] >= MAX_FAILS
        if give_up:
            # Don't let one bad item wedge a 365-day queue: mark it done and move on.
            target["posted_at"] = now.isoformat()
            target["skipped"] = True
        if mode == "recycle" and give_up:
            items.append(target)
        QUEUE_PATH.write_text(json.dumps(items, indent=2) + "\n")
        _write_status("skipped-bad" if give_up else "failed", target.get("id"), fresh_left, now)
        print("POST FAILED id=%s (attempt %d/%d)%s: %s" % (
            target.get("id"), target["fail_count"], MAX_FAILS,
            " — giving up, skipping" if give_up else " — will retry next run", e))
        return 0 if give_up else 1

    target["posted_at"] = now.isoformat()
    target["result_id"] = res.get("id")

    # ---- best-effort Facebook Page crosspost (never fails the run) --------
    if CROSSPOST_FB and acct.fb_page_id and (target.get("type") or "").lower() in ("reel", "image"):
        try:
            ptoken = client.resolve_page_token(acct.fb_page_id)
            if (target["type"] or "").lower() == "reel":
                fb = client.page_post_video(
                    acct.fb_page_id, ptoken, target["media_url"], target.get("caption", ""))
            else:
                fb = client.page_post_photo(
                    acct.fb_page_id, ptoken, target["media_url"], target.get("caption", ""))
            target["fb_result_id"] = fb.get("id")
            target.pop("fb_error", None)
            print("  + Facebook Page: %s" % fb.get("id"))
        except (MetaError, KeyError) as e:
            target["fb_error"] = str(e)
            print("  ! Facebook crosspost failed (Instagram post is live): %s" % e)

    # ---- best-effort YouTube Shorts crosspost (never fails the run) -------
    if CROSSPOST_YT and (target.get("type") or "").lower() == "reel":
        yt = YouTubeClient.from_env()
        if yt is None:
            print("  · YouTube not configured (no YOUTUBE_* env); skipping")
        else:
            try:
                cap = target.get("caption", "") or "Old Money Mood"
                title = cap.split("\n")[0][:90]
                tags = [t.lstrip("#") for t in cap.split() if t.startswith("#")]
                r = yt.upload(
                    target["media_url"],
                    title=title,
                    description=cap + "\n\n#Shorts",
                    tags=tags,
                )
                target["yt_result_id"] = r.get("id")
                target.pop("yt_error", None)
                print("  + YouTube: https://youtu.be/%s" % r.get("id"))
            except (YouTubeError, KeyError, requests.RequestException) as e:
                target["yt_error"] = str(e)
                print("  ! YouTube crosspost failed (Instagram post is live): %s" % e)

    if mode == "recycle":
        items.append(target)  # recycle clone is a new record
    fresh_left = _fresh_remaining(items, now)
    QUEUE_PATH.write_text(json.dumps(items, indent=2) + "\n")
    _write_status("posted" if mode == "fresh" else "recycled", target.get("id"), fresh_left, now)

    print("Published id=%s -> media %s  (fresh remaining: %d)" % (
        target.get("id"), res.get("id"), fresh_left))
    if fresh_left <= LOW_QUEUE_THRESHOLD:
        print("::low-queue::%d" % fresh_left)
    return 0


if __name__ == "__main__":
    sys.exit(main())
