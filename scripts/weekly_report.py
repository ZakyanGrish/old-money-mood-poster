#!/usr/bin/env python3
"""Build a weekly performance + health report and print it as GitHub-flavoured Markdown.

The workflow pipes this into `gh issue create`. Covers the trailing 7 days:
what published, engagement per post, any failures, and how much runway is left
in content/queue.json.
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

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "content" / "queue.json"
STATUS = ROOT / "content" / "status.json"
IG_USER_ID = "17841477100835322"  # Old Money Mood
SLOTS_PER_DAY = 3


try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = dt.timezone(dt.timedelta(hours=-5))


def _fmt_dt(iso: str) -> str:
    try:
        d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(_ET).strftime("%b %d %I:%M %p ET")
    except Exception:
        return iso


def main() -> int:
    load_env()
    token = os.environ.get("META_ACCESS_TOKEN", "")
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=7)
    lines = []
    lines.append("## Old Money Mood — weekly report")
    lines.append("_%s → %s_" % (since.strftime("%b %d"), now.strftime("%b %d, %Y")))
    lines.append("")

    # ---- published in the last 7 days ------------------------------------
    posts = []
    if token:
        try:
            c = MetaClient(token)
            data = c._call(
                "GET", "%s/media" % IG_USER_ID,
                fields="id,caption,media_product_type,permalink,timestamp,like_count,comments_count",
                limit=50,
            )
            for m in data.get("data", []):
                ts = dt.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
                if ts >= since:
                    reach = None
                    try:
                        ins = c._call("GET", "%s/insights" % m["id"], metric="reach")
                        vals = (ins.get("data") or [{}])[0].get("values") or []
                        reach = vals[0].get("value") if vals else None
                    except MetaError:
                        pass
                    posts.append((ts, m, reach))
        except MetaError as e:
            lines.append("> Could not read Instagram data: %s" % e)
            lines.append("")

    if posts:
        posts.sort(key=lambda x: x[0])
        tot_l = sum(p[1].get("like_count", 0) for p in posts)
        tot_c = sum(p[1].get("comments_count", 0) for p in posts)
        reaches = [p[2] for p in posts if p[2] is not None]
        lines.append("**Published:** %d posts · %d likes · %d comments%s" % (
            len(posts), tot_l, tot_c,
            (" · %d avg reach" % (sum(reaches) // len(reaches))) if reaches else "",
        ))
        lines.append("")
        lines.append("| Date | Type | Likes | Comments | Reach | Post |")
        lines.append("|---|---|--:|--:|--:|---|")
        for ts, m, reach in posts:
            cap = (m.get("caption") or "").split("\n")[0][:40]
            lines.append("| %s | %s | %s | %s | %s | [link](%s) |" % (
                ts.astimezone(_ET).strftime("%a %d %I:%M%p").replace(" 0", " "),
                (m.get("media_product_type") or "").title() or "Feed",
                m.get("like_count", 0), m.get("comments_count", 0),
                reach if reach is not None else "—",
                m.get("permalink", ""),
            ))
        lines.append("")
        best = max(posts, key=lambda x: x[1].get("like_count", 0))
        lines.append("**Top post:** [%s](%s) — %d likes" % (
            (best[1].get("caption") or "").split("\n")[0][:50],
            best[1].get("permalink", ""), best[1].get("like_count", 0),
        ))
        lines.append("")
    else:
        lines.append("**Published:** no posts detected in the last 7 days.")
        lines.append("")

    # ---- queue health ---------------------------------------------------
    q = json.loads(QUEUE.read_text() or "[]") if QUEUE.exists() else []
    sched = [it for it in q if str(it.get("id", "")).startswith(("sched-", "story-"))]
    unposted = [it for it in sched if not it.get("posted_at")]
    skipped = [it for it in q if it.get("skipped")]
    failing = [it for it in q if it.get("fail_count") and not it.get("posted_at")]
    days_left = len({it["not_before"][:10] for it in unposted if it.get("not_before")})
    next_due = min((it["not_before"] for it in unposted if it.get("not_before")), default=None)
    wk_iso = (now - dt.timedelta(days=7)).isoformat()
    fb_ok = sum(1 for it in q if it.get("fb_result_id") and (it.get("posted_at") or "") >= wk_iso)
    fb_err = sum(1 for it in q if it.get("fb_error") and (it.get("posted_at") or "") >= wk_iso)

    lines.append("### Queue health")
    lines.append("")
    lines.append("- **Runway:** %d posts queued ≈ **%d days** of content" % (len(unposted), days_left))
    lines.append("- **Facebook crossposts (7d):** %d ok%s" % (
        fb_ok, (", **%d failed**" % fb_err) if fb_err else ""))
    if next_due:
        lines.append("- **Next scheduled:** %s" % _fmt_dt(next_due))
    lines.append("- **Skipped (bad media, gave up):** %d" % len(skipped))
    if failing:
        lines.append("- **⚠️ Currently retrying:** %d item(s) — %s" % (
            len(failing), ", ".join(it["id"] for it in failing[:5])))
    if STATUS.exists():
        st = json.loads(STATUS.read_text())
        lines.append("- **Last run:** %s (%s) at %s" % (
            st.get("action"), st.get("item_id") or "—", _fmt_dt(st.get("checked_at", ""))))
    lines.append("")

    if skipped:
        lines.append("<details><summary>Skipped items</summary>")
        lines.append("")
        for it in skipped[:20]:
            lines.append("- `%s` — %s" % (it.get("id"), (it.get("last_error") or "")[:120]))
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("---")
    lines.append("_Automated. Reply here or start a Claude Code session to change anything._")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
