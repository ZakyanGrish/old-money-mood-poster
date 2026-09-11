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
import hashlib
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

# 5 daily UTC slots, all inside the same US-Eastern calendar day
# (~8:00 AM / 10:30 AM / 1:00 PM / 4:00 PM / 7:00 PM ET in summer; one hour
# earlier in winter). Each day fills MIN_PER_DAY..MAX_PER_DAY of them.
SLOTS_UTC = [(12, 0), (14, 30), (17, 0), (20, 0), (23, 0)]
MIN_PER_DAY = 3
MAX_PER_DAY = 5
SEED = 20260908
GENERIC_HASHTAGS = ["#oldmoney", "#oldmoneyaesthetic", "#quietluxury", "#oldmoneystyle", "#timelesselegance"]

# keyword -> (emoji pool, extra themed hashtags). First match wins; order matters.
THEMES = [
    ("travel", ("monaco", "como", "riviera", "dubai", "paris", "italy", "dolce vita", "yacht",
                "boat", "summer", "vacation", "destination", "travel", "milan", "moritz",
                "switzerland", "courchevel", "alps", "ski", "winter"),
     ["🛥️", "🥂", "🇮🇹", "✈️", "🏖️"],
     ["#rivierastyle", "#cotedazur", "#monacolife", "#travelinstyle", "#jetset"]),
    ("style", ("outfit", "wear", "tailor", "suit", "dress", "loafers", "cashmere", "style",
               "fashion", "closet", "wardrobe", "accessor", "classy"),
     ["🧥", "⌚", "🤎", "👞"],
     ["#quietluxurystyle", "#tailoredfit", "#oldmoneystyle", "#timelessstyle"]),
    ("legacy", ("legacy", "tradition", "family", "future", "goal", "dream", "success", "wealth",
                "money", "class", "value", "generation", "born", "job", "career"),
     ["👑", "💼", "🥃", "🕰️"],
     ["#oldmoneymindset", "#legacywealth", "#generationalwealth", "#oldmoneyvalues"]),
    ("romance", ("love", "romance", "soulmate", "together", "wedding", "married", "couple"),
     ["💌", "💍", "🤍"],
     ["#oldmoneylove", "#classiccouple", "#timelessromance"]),
]

CTAS = [
    "Save this for later.",
    "Tag someone who'd get it.",
    "Which one are you?",
    "Send this to your future self.",
    "Follow for more of this.",
    "Drop a \U0001F90D if you agree.",
    "Screenshot this.",
]


def enrich_caption(hook: str, rng: random.Random) -> str:
    """hook -> full caption: maybe an emoji, maybe a CTA line, themed hashtags."""
    low = hook.lower()
    theme = next((t for t in THEMES if any(k in low for k in t[1])), None)

    line1 = hook
    if rng.random() < 0.5:                                   # emoji ~half the time
        pool = theme[2] if theme else ["✨", "🥂", "🕊️"]
        line1 = hook + " " + rng.choice(pool)

    parts = [line1]
    if not hook.rstrip().endswith("?") and rng.random() < 0.7:  # skip CTA on questions
        parts.append(rng.choice(CTAS))

    tags = GENERIC_HASHTAGS[:3]
    if theme:
        tags = tags + rng.sample(theme[3], k=min(2, len(theme[3])))
    else:
        tags = GENERIC_HASHTAGS
    parts.append(" ".join(tags))
    return "\n\n".join(parts)

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


def theme_of(caption_or_hook: str) -> str:
    low = (caption_or_hook or "").lower()
    for name, keywords, *_ in THEMES:
        if any(k in low for k in keywords):
            return name
    return "generic"


def theme_weights(history: list, min_samples: int = 8) -> dict:
    """Average measured reach per theme from posted history -> a selection weight.

    Falls back to 1.0 (even weighting) for any theme without enough samples yet —
    same "model until measured" pattern as the follower projection.
    """
    from collections import defaultdict

    sums, counts = defaultdict(float), defaultdict(int)
    for it in history:
        r, th = it.get("reach"), it.get("theme")
        if r is not None and th:
            sums[th] += r
            counts[th] += 1
    overall = (sum(sums.values()) / sum(counts.values())) if counts else None
    names = [t[0] for t in THEMES] + ["generic"]
    weights = {}
    for name in names:
        if overall and counts.get(name, 0) >= min_samples:
            weights[name] = max(0.7, min(1.6, sums[name] / counts[name] / overall))
        else:
            weights[name] = 1.0
    return weights


def build(days: int, recent_pids: set = frozenset(), history: list = ()) -> list:
    vids = fetch_videos()
    if not vids:
        raise SystemExit("No videos found in Cloudinary.")
    # Reseed per build date so a regen isn't the same order as last time.
    rng = random.Random(SEED + int(dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")))

    # How many posts each day, and which of the 5 slots they land in.
    day_slots = []
    for _ in range(days):
        k = rng.randint(MIN_PER_DAY, MAX_PER_DAY)
        slots = sorted(rng.sample(range(len(SLOTS_UTC)), k))
        day_slots.append(slots)
    total = sum(len(s) for s in day_slots)

    # Weight the deck toward themes that have measurably performed better, once
    # there's enough posted history to say so; every video still gets at least
    # one copy per pass, so nothing is ever excluded -- just less frequent.
    weights = theme_weights(list(history))
    weighted_vids: list = []
    for v in vids:
        w = weights.get(theme_of(caption_from_public_id(v["public_id"])), 1.0)
        weighted_vids.extend([v] * max(1, round(w * 10)))

    order: list = []
    while len(order) < total + len(vids):        # + one deck of buffer for skip-forward
        deck = weighted_vids[:]
        rng.shuffle(deck)
        order.extend(deck)

    # Start today (UTC): the earliest slot is 12:00 UTC, so if this runs before
    # noon the schedule still covers today; otherwise today's early slots simply
    # sit in the past and are skipped by the not_before gate.
    now = dt.datetime.now(dt.timezone.utc)
    start = now.date()
    items = []
    seen_pass: dict = {}
    idx = 0
    for day, slots in enumerate(day_slots):
        for slot in slots:
            h, m = SLOTS_UTC[slot]
            when = dt.datetime.combine(
                start + dt.timedelta(days=day), dt.time(h, m), dt.timezone.utc
            )
            if when <= now:                       # don't schedule a slot already past
                continue
            # Skip forward past any video posted in the last ~3 weeks, so a regen
            # right after some test posts doesn't re-air them the next morning.
            while day < 21 and idx + 1 < len(order) and order[idx]["public_id"] in recent_pids:
                idx += 1
            v = order[min(idx, len(order) - 1)]
            idx += 1
            pid = v["public_id"]
            seen_pass[pid] = seen_pass.get(pid, 0) + 1
            hook = caption_from_public_id(pid)
            caption = enrich_caption(hook, rng)
            pid_tag = hashlib.sha1(pid.encode()).hexdigest()[:6]
            item = {
                # slot time + a hash of the video: unique even across re-runs that
                # regenerate the same slot with a different pick.
                "id": "sched-%s-%s" % (when.strftime("%Y%m%dT%H%M"), pid_tag),
                "type": "reel",
                "media_url": v["secure_url"],
                "caption": caption,
                "not_before": when.isoformat(),
                "posted_at": None,
                "result_id": None,
                "source_public_id": pid,
                "theme": theme_of(hook),
                "pass": seen_pass[pid],
            }
            items.append(item)
            if slot == slots[0]:
                # One Story a day, reusing the day's first reel -- keeps the
                # account in followers' top bar at zero extra content cost.
                story_when = dt.datetime.combine(
                    start + dt.timedelta(days=day), dt.time(11, 0), dt.timezone.utc
                )
                if story_when > now:
                    items.append({
                        "id": "story-%s-%s" % (story_when.strftime("%Y%m%dT%H%M"), pid_tag),
                        "type": "story",
                        "media_url": v["secure_url"],
                        "caption": "",
                        "not_before": story_when.isoformat(),
                        "posted_at": None,
                        "result_id": None,
                        "source_public_id": pid,
                        "theme": item["theme"],
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
    live_sched = [it for it in existing if not it.get("posted_at") and str(it.get("id", "")).startswith(("sched-", "story-"))]
    if live_sched:
        print("Note: %d unposted sched-* items already in queue; they will be replaced." % len(live_sched))

    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=21)).isoformat()
    recent_pids = {
        it["source_public_id"] for it in kept
        if it.get("source_public_id") and (it.get("posted_at") or "") >= cutoff
    }
    if recent_pids:
        print("Note: %d recently-posted videos held back from the first 3 weeks." % len(recent_pids))

    sched = build(args.days, recent_pids, history=kept)
    new_queue = kept + sched
    reels = [it for it in sched if it["type"] == "reel"]
    stories = [it for it in sched if it["type"] == "story"]

    uniq = len({it["source_public_id"] for it in reels})
    print("videos in library:      %d" % uniq)
    print("scheduled reels:        %d  (%d days, %d-%d/day)" % (
        len(reels), args.days, MIN_PER_DAY, MAX_PER_DAY))
    print("scheduled stories:      %d  (1/day)" % len(stories))
    print("avg posts/day:          %.2f" % (len(reels) / args.days))
    print("first post not_before:  %s" % sched[0]["not_before"])
    print("last  post not_before:  %s" % sched[-1]["not_before"])
    print("avg re-airs per video:  %.1f  (~every %d days)" % (
        len(reels) / uniq, int(args.days / (len(reels) / uniq))))
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
