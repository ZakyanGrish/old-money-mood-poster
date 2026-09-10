#!/usr/bin/env python3
"""Regenerate dashboard.html from live data + the queue + the activity log.

Run by the poster workflow after every run (several times a day), so the page at
GitHub Pages always reflects the latest state, including recent changes and errors.
Data is baked into the file; the page itself makes no API calls.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smposter.config import load_env  # noqa: E402
from smposter.meta import MetaClient, MetaError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard.template.html"
OUT = ROOT / "dashboard.html"
IG_USER_ID = "17841477100835322"


def _read(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return default


def gather() -> dict:
    load_env()
    now = dt.datetime.now(dt.timezone.utc)
    token = os.environ.get("META_ACCESS_TOKEN", "")

    profile, recent, api_error = {}, [], None
    if token:
        try:
            c = MetaClient(token)
            profile = c._call(
                "GET", IG_USER_ID,
                fields="username,followers_count,follows_count,media_count",
            )
            data = c._call(
                "GET", "%s/media" % IG_USER_ID,
                fields="id,caption,media_product_type,media_type,permalink,timestamp,"
                       "like_count,comments_count",
                limit=16,
            )
            for i, m in enumerate(data.get("data", [])):
                reach = None
                if i < 12:
                    try:
                        ins = c._call("GET", "%s/insights" % m["id"], metric="reach")
                        vals = (ins.get("data") or [{}])[0].get("values") or []
                        reach = vals[0].get("value") if vals else None
                    except MetaError:
                        pass
                recent.append({
                    "caption": (m.get("caption") or "").split("\n")[0],
                    "type": m.get("media_product_type") or m.get("media_type"),
                    "permalink": m.get("permalink"),
                    "timestamp": m.get("timestamp"),
                    "likes": m.get("like_count", 0),
                    "comments": m.get("comments_count", 0),
                    "reach": reach,
                })
        except MetaError as e:
            api_error = str(e)

    q = _read(ROOT / "content" / "queue.json", [])
    sched = [it for it in q if str(it.get("id", "")).startswith("sched-")]
    unposted = sorted(
        (it for it in sched if not it.get("posted_at") and it.get("not_before")),
        key=lambda it: it["not_before"],
    )
    rr = [r["reach"] for r in recent if r["type"] == "REELS" and r["reach"] and r["reach"] >= 25]

    return {
        "generated_at": now.isoformat(),
        "profile": profile or {"username": "oldmoneymood", "followers_count": None,
                               "follows_count": None, "media_count": None},
        "api_error": api_error,
        "series": _read(ROOT / "content" / "followers.json", []),
        "status": _read(ROOT / "content" / "status.json", {}),
        "activity": _read(ROOT / "content" / "activity.json", [])[-60:],
        "recent": recent,
        "reels_reach_med": int(statistics.median(rr)) if rr else 135,
        "engine": {
            "posts_per_day": 4,
            "queued": len(unposted),
            "days_left": len({it["not_before"][:10] for it in unposted}),
            "library": len({it.get("source_public_id") for it in sched if it.get("source_public_id")}),
        },
        "upcoming": [
            {"when": it["not_before"], "caption": (it.get("caption") or "").split("\n")[0]}
            for it in unposted[:16]
        ],
    }


def main() -> int:
    data = gather()
    tmpl = TEMPLATE.read_text()
    marker_a, marker_b = "/*DATA*/{}/*END*/", None
    if marker_a not in tmpl:
        raise SystemExit("template marker not found in %s" % TEMPLATE)
    html = tmpl.replace(marker_a, json.dumps(data, separators=(",", ":")), 1)
    OUT.write_text(html)
    print("wrote %s  (followers=%s, activity=%d, upcoming=%d, api_error=%s)" % (
        OUT.name, data["profile"].get("followers_count"),
        len(data["activity"]), len(data["upcoming"]), bool(data["api_error"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
