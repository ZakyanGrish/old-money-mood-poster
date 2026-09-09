#!/usr/bin/env python3
"""Fill content/queue.json with a full year of Reels drawn from the Cloudinary library.

- Pulls every video under the account's Cloudinary cloud (resource_type=video).
- Derives a caption from each file's public_id (they carry the original wording).
- Shuffles the library (seeded) and cycles it to cover DAYS * POSTS_PER_DAY slots,
  re-shuffling on each pass so repeats don't run in the same order.
- Stamps each item with a not_before at the daily UTC slot times, so the cron
  posts exactly one per slot and rapid/duplicate runs can't burst-post.
- Keeps any already-posted items already in the queue; appends the schedule.

Run once:  python scripts/build_year_schedule.py --days 365
Preview:   python scripts/build_year_schedule.py --days 365 --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smposter.config import load_env  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = ROOT / "content" / "queue.json"

# 5 daily UTC slots (~8:00 / 11:30 / 14:30 / 18:00 / 21:00 ET in summer).
# Each day fills MIN_PER_DAY..MAX_PER_DAY of them, chosen at build time.
SLOTS_UTC = [(12, 0), (15, 30), (18, 30), (22, 0), (1, 0)]
MIN_PER_DAY = 3
MAX_PER_DAY = 5
SEED = 20260908
HASHTAGS = "#oldmoney #oldmoneyaesthetic #quietluxury #oldmoneystyle #timelesselegance"

# Cloudinary public_ids we never want to schedule (test uploads, demo assets).
EXCLUDE_IDS = {"omm/d5hnlmlpryzabctndrsm"}
EXCLUDE_PREFIXES = ("samples/", "omm/")


def fetch_videos() -> list:
    load_env()
    import cloudinary
    import cloudinary.api

    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    out, cursor = [], None
    while True:
        kw = dict(resource_type="video", type="upload", max_results=500)
        if cursor:
            kw["next_cursor"] = cursor
        r = cloudinary.api.resources(**kw)
        out.extend(r["resources"])
        cursor = r.get("next_cursor")
        if not cursor:
            break
    keep = [
        v for v in out
        if v["public_id"] not in EXCLUDE_IDS
        and not v["public_id"].startswith(EXCLUDE_PREFIXES)
    ]
    return keep


def _looks_like_shortcode(tail: str) -> bool:
    # Instagram shortcodes: start C/D, ~9-12 chars of [A-Za-z0-9-], with a digit
    # or mixed case. Cloudinary may split one across tokens via sanitized chars.
    if not re.fullmatch(r"[CD][A-Za-z0-9\-]{7,12}", tail):
        return False
    return any(c.isdigit() for c in tail) or (
        any(c.islower() for c in tail) and any(c.isupper() for c in tail[1:])
    )


def caption_from_public_id(pid: str) -> str:
    base = pid.split("/")[-1]
    toks = base.replace("_", " ").split()
    if toks and re.fullmatch(r"\d{1,3}", toks[-1]):          # trailing counter e.g. "06"
        toks.pop()
    for take in (3, 2, 1):                                    # trailing shortcode, maybe split
        if len(toks) > take and _looks_like_shortcode("".join(toks[-take:])):
            del toks[-take:]
            break
    s = " ".join(toks)
    # Cloudinary flattened apostrophes to spaces — restore common contractions.
    s = re.sub(r"\b([Ii]t|[Tt]hat|[Hh]ere|[Ww]hat|[Hh]e|[Ss]he|[Tt]here|[Ww]ho)\s+s\b", r"\1's", s)
    s = re.sub(r"\b([A-Za-z]+)\s+(t|re|ll|ve|m|d)\b", r"\1'\2", s)
    s = s.replace(" .", ".").replace(" ,", ",").replace(" -", " ")
    s = re.sub(r"\s{2,}", " ", s).strip(" .,-‍️❤")
    if len(s) < 4 or _looks_like_shortcode(s.replace(" ", "")):
        return "The old money mood."
    return s


def build(days: int) -> list:
    vids = fetch_videos()
    if not vids:
        raise SystemExit("No videos found in Cloudinary.")
    rng = random.Random(SEED)

    # How many posts each day, and which of the 5 slots they land in.
    day_slots = []
    for _ in range(days):
        k = rng.randint(MIN_PER_DAY, MAX_PER_DAY)
        slots = sorted(rng.sample(range(len(SLOTS_UTC)), k))
        day_slots.append(slots)
    total = sum(len(s) for s in day_slots)

    order: list = []
    while len(order) < total:
        deck = vids[:]
        rng.shuffle(deck)
        order.extend(deck)
    order = order[:total]

    start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).date()
    items = []
    seen_pass: dict = {}
    idx = 0
    for day, slots in enumerate(day_slots):
        for slot in slots:
            v = order[idx]
            idx += 1
            h, m = SLOTS_UTC[slot]
            when = dt.datetime.combine(
                start + dt.timedelta(days=day), dt.time(h, m), dt.timezone.utc
            )
            pid = v["public_id"]
            seen_pass[pid] = seen_pass.get(pid, 0) + 1
            cap = caption_from_public_id(pid)
            items.append({
                "id": "sched-%s-%d" % (when.date().isoformat(), slot + 1),
                "type": "reel",
                "media_url": v["secure_url"],
                "caption": "%s\n\n%s" % (cap, HASHTAGS),
                "not_before": when.isoformat(),
                "posted_at": None,
                "result_id": None,
                "source_public_id": pid,
                "pass": seen_pass[pid],
            })
    items.sort(key=lambda it: it["not_before"])
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=1825)  # 5 years
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    existing = json.loads(QUEUE_PATH.read_text() or "[]") if QUEUE_PATH.exists() else []
    kept = [it for it in existing if it.get("posted_at")]
    live_sched = [it for it in existing if not it.get("posted_at") and str(it.get("id", "")).startswith("sched-")]
    if live_sched:
        print("Note: %d unposted sched-* items already in queue; they will be replaced." % len(live_sched))

    sched = build(args.days)
    new_queue = kept + sched

    uniq = len({it["source_public_id"] for it in sched})
    print("videos in library:      %d" % uniq)
    print("scheduled items:        %d  (%d days, %d-%d/day)" % (
        len(sched), args.days, MIN_PER_DAY, MAX_PER_DAY))
    print("avg posts/day:          %.2f" % (len(sched) / args.days))
    print("first post not_before:  %s" % sched[0]["not_before"])
    print("last  post not_before:  %s" % sched[-1]["not_before"])
    print("avg re-airs per video:  %.1f  (~every %d days)" % (
        len(sched) / uniq, int(args.days / (len(sched) / uniq))))
    print("kept (already posted):  %d" % len(kept))
    print("queue.json size est:    ~%.1f MB" % (len(sched) * 360 / 1e6))
    print("\nfirst 6:")
    for it in sched[:6]:
        print("  %s  %s  | %s" % (it["not_before"], it["id"], it["caption"].split("\n")[0][:60]))

    if args.dry_run:
        print("\n--dry-run: queue.json not written")
        return 0

    QUEUE_PATH.write_text(json.dumps(new_queue, indent=2) + "\n")
    print("\nWrote %s (%d items)" % (QUEUE_PATH, len(new_queue)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
