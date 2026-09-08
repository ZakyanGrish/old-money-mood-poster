#!/usr/bin/env python3
"""Regenerate docs/index.html — the always-on status dashboard.

Run by the poster workflow after each post, so the page reflects the latest
queue, run status, and Instagram engagement. Data is baked into the HTML at
build time (window.__DATA__); the page itself makes no API calls.
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
OUT = ROOT / "docs" / "index.html"
IG_USER_ID = "17841477100835322"
SLOTS_PER_DAY = 3
REPO = "ZakyanGrish/old-money-mood-poster"


def iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00"))


def gather() -> dict:
    load_env()
    now = dt.datetime.now(dt.timezone.utc)
    q = json.loads(QUEUE.read_text() or "[]") if QUEUE.exists() else []
    status = json.loads(STATUS.read_text()) if STATUS.exists() else {}

    sched = [it for it in q if str(it.get("id", "")).startswith("sched-")]
    posted = [it for it in q if it.get("posted_at") and not it.get("skipped")]
    unposted = [it for it in sched if not it.get("posted_at")]
    skipped = [it for it in q if it.get("skipped")]
    failing = [it for it in q if it.get("fail_count") and not it.get("posted_at")]
    upcoming = sorted(
        [it for it in unposted if it.get("not_before")],
        key=lambda it: it["not_before"],
    )[:14]

    profile, recent = {}, []
    token = os.environ.get("META_ACCESS_TOKEN", "")
    api_error = None
    if token:
        try:
            c = MetaClient(token)
            profile = c._call(
                "GET", IG_USER_ID,
                fields="username,name,followers_count,media_count,profile_picture_url",
            )
            data = c._call(
                "GET", "%s/media" % IG_USER_ID,
                fields="id,caption,media_product_type,permalink,timestamp,"
                       "like_count,comments_count,thumbnail_url,media_url,media_type",
                limit=24,
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
                thumb = m.get("thumbnail_url") or (
                    m.get("media_url") if m.get("media_type") == "IMAGE" else None
                )
                recent.append({
                    "caption": (m.get("caption") or "").split("\n")[0],
                    "type": m.get("media_product_type") or m.get("media_type") or "",
                    "permalink": m.get("permalink"),
                    "timestamp": m.get("timestamp"),
                    "likes": m.get("like_count", 0),
                    "comments": m.get("comments_count", 0),
                    "reach": reach,
                    "thumb": thumb,
                })
        except MetaError as e:
            api_error = str(e)

    wk = now - dt.timedelta(days=7)
    mo = now - dt.timedelta(days=30)
    r_wk = [r for r in recent if r["timestamp"] and iso(r["timestamp"]) >= wk]
    r_mo = [r for r in recent if r["timestamp"] and iso(r["timestamp"]) >= mo]

    return {
        "generated_at": now.isoformat(),
        "repo": REPO,
        "profile": profile,
        "api_error": api_error,
        "status": status,
        "kpi": {
            "runway_days": len(unposted) // SLOTS_PER_DAY,
            "queued": len(unposted),
            "posted_total": len(posted),
            "posts_7d": len(r_wk),
            "posts_30d": len(r_mo),
            "likes_7d": sum(r["likes"] for r in r_wk),
            "comments_7d": sum(r["comments"] for r in r_wk),
            "skipped": len(skipped),
            "failing": len(failing),
        },
        "recent": recent,
        "upcoming": [
            {"when": it["not_before"], "id": it["id"],
             "caption": (it.get("caption") or "").split("\n")[0]}
            for it in upcoming
        ],
        "skipped_items": [
            {"id": it.get("id"), "error": (it.get("last_error") or "")[:160]}
            for it in skipped[:25]
        ],
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Old Money Mood — Poster</title>
<style>
:root{
  --bg:#f6f1e7; --card:#fffdf8; --ink:#2c2620; --muted:#8a7f6d; --line:#e4dcc9;
  --brass:#9a7b4f; --good:#4f7a4f; --warn:#b0863c; --bad:#a5503f;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#181510; --card:#221e17; --ink:#ece4d3; --muted:#9a8f7c; --line:#332c20;
  --brass:#c9a875; --good:#7fb07f; --warn:#d8ab63; --bad:#d98a77;
}}
:root[data-theme=dark]{
  --bg:#181510; --card:#221e17; --ink:#ece4d3; --muted:#9a8f7c; --line:#332c20;
  --brass:#c9a875; --good:#7fb07f; --warn:#d8ab63; --bad:#d98a77;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-serif,Georgia,"Times New Roman",serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 64px}
header{display:flex;align-items:center;gap:16px;margin-bottom:8px}
header img{width:56px;height:56px;border-radius:50%;object-fit:cover;border:1px solid var(--line)}
h1{font-size:22px;margin:0;letter-spacing:.02em}
.sub{color:var(--muted);font-size:13px;margin-top:2px}
.grid{display:grid;gap:14px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:22px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.kpi .n{font-size:26px;font-weight:600;letter-spacing:.01em}
.kpi .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:4px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
  margin:34px 0 12px;font-weight:600}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;border:1px solid var(--line)}
.pill.good{color:var(--good);border-color:var(--good)}
.pill.warn{color:var(--warn);border-color:var(--warn)}
.pill.bad{color:var(--bad);border-color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
a{color:var(--brass)}
.posts{grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.post{overflow:hidden;padding:0}
.post .thumb{aspect-ratio:1/1;width:100%;object-fit:cover;background:var(--line);display:block}
.post .body{padding:12px}
.post .cap{font-size:13px;max-height:3.1em;overflow:hidden}
.post .meta{color:var(--muted);font-size:12px;margin-top:6px;display:flex;gap:10px;flex-wrap:wrap}
.foot{margin-top:40px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:16px}
.err{color:var(--bad);font-size:13px}
.links a{margin-right:16px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <img id="pfp" alt="" src="">
    <div>
      <h1 id="acct">Old Money Mood</h1>
      <div class="sub" id="sub"></div>
    </div>
  </header>

  <div id="statusline"></div>

  <div class="grid kpis" id="kpis"></div>

  <h2>Recent posts</h2>
  <div class="grid posts" id="posts"></div>

  <h2>Next up</h2>
  <div class="card"><table id="upcoming"><thead><tr><th>When (ET)</th><th>Caption</th></tr></thead><tbody></tbody></table></div>

  <h2>Health</h2>
  <div class="card" id="health"></div>

  <div class="foot">
    <div class="links" id="links"></div>
    <div style="margin-top:10px">Regenerated automatically on every posting run · <span id="gen"></span></div>
    <div style="margin-top:4px">To change cadence, content, or captions — start a Claude Code session.</div>
  </div>
</div>

<script>window.__DATA__ = __DATA_JSON__;</script>
<script>
const D = window.__DATA__;
const esc = s => (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ET = "America/New_York";
const fmt = iso => { try{ return new Date(iso).toLocaleString("en-US", {timeZone:ET,month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})+" ET";}catch(e){return iso||"";} };
const fmtDay = iso => { try{ return new Date(iso).toLocaleString("en-US", {timeZone:ET,weekday:"short",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})+" ET";}catch(e){return iso||"";} };
const p = D.profile||{};
document.getElementById("acct").textContent = p.name || "Old Money Mood";
document.getElementById("sub").textContent =
  (p.username?("@"+p.username+"  ·  "):"") +
  (p.followers_count!=null?p.followers_count.toLocaleString()+" followers  ·  ":"") +
  (p.media_count!=null?p.media_count.toLocaleString()+" posts":"");
if(p.profile_picture_url) document.getElementById("pfp").src = p.profile_picture_url;
else document.getElementById("pfp").remove();

const st = D.status||{}, k = D.kpi||{};
const runwayCls = k.runway_days>21?"good":k.runway_days>7?"warn":"bad";
const lastAct = st.action||"—";
const actCls = lastAct==="posted"||lastAct==="recycled"?"good":lastAct==="idle"?"":lastAct.indexOf("fail")>-1||lastAct==="skipped-bad"?"bad":"";
document.getElementById("statusline").innerHTML =
  `<div class="card"><span class="pill ${actCls}">last run: ${esc(lastAct)}${st.item_id?" · "+esc(st.item_id):""}</span>
   &nbsp; <span class="pill ${runwayCls}">${k.runway_days} days of content left</span>
   ${D.api_error?`<div class="err" style="margin-top:8px">Instagram API: ${esc(D.api_error)}</div>`:""}</div>`;

const kpis = [
  ["Runway", k.runway_days+" d"],
  ["Queued posts", (k.queued||0).toLocaleString()],
  ["Posted (all-time)", (k.posted_total||0).toLocaleString()],
  ["Posts · 7d", k.posts_7d],
  ["Likes · 7d", k.likes_7d],
  ["Comments · 7d", k.comments_7d],
  ["Skipped", k.skipped],
  ["Retrying", k.failing],
];
document.getElementById("kpis").innerHTML = kpis.map(([l,n])=>
  `<div class="card kpi"><div class="n">${esc(String(n))}</div><div class="l">${esc(l)}</div></div>`).join("");

document.getElementById("posts").innerHTML = (D.recent||[]).slice(0,12).map(r=>`
  <a class="card post" href="${esc(r.permalink)}" target="_blank" rel="noopener">
    ${r.thumb?`<img class="thumb" loading="lazy" src="${esc(r.thumb)}" alt="">`:`<div class="thumb"></div>`}
    <div class="body">
      <div class="cap">${esc(r.caption)||"<span style='color:var(--muted)'>(no caption)</span>"}</div>
      <div class="meta">
        <span>${esc(r.type)}</span><span>♥ ${r.likes}</span><span>💬 ${r.comments}</span>
        ${r.reach!=null?`<span>reach ${r.reach.toLocaleString()}</span>`:""}
        <span>${fmt(r.timestamp)}</span>
      </div>
    </div>
  </a>`).join("") || `<div class="card">No posts read from Instagram.</div>`;

document.querySelector("#upcoming tbody").innerHTML = (D.upcoming||[]).map(u=>
  `<tr><td class="num">${esc(fmtDay(u.when))}</td><td>${esc(u.caption)}</td></tr>`
).join("") || `<tr><td colspan="2">Queue empty.</td></tr>`;

const sk = D.skipped_items||[];
document.getElementById("health").innerHTML =
  `<p><b>${k.skipped}</b> skipped after repeated failures · <b>${k.failing}</b> currently retrying.</p>` +
  (sk.length?`<table><thead><tr><th>Item</th><th>Last error</th></tr></thead><tbody>`+
    sk.map(s=>`<tr><td>${esc(s.id)}</td><td class="err">${esc(s.error)}</td></tr>`).join("")+
    `</tbody></table>`:`<p style="color:var(--muted)">Nothing skipped. Clean run.</p>`);

const repo = "https://github.com/"+D.repo;
document.getElementById("links").innerHTML = [
  [repo+"/actions","Run history"],
  [repo+"/issues?q=is%3Aissue+label%3Areport","Weekly reports"],
  [repo+"/issues","All alerts"],
  ["https://www.instagram.com/"+(p.username||""),"Instagram"],
].map(([h,t])=>`<a href="${h}" target="_blank" rel="noopener">${t}</a>`).join("");
document.getElementById("gen").textContent = fmt(D.generated_at);
</script>
</body>
</html>
"""


def main() -> int:
    data = gather()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = HTML.replace("__DATA_JSON__", json.dumps(data))
    OUT.write_text(html)
    print("wrote %s  (runway %d days, %d recent posts, api_error=%s)" % (
        OUT, data["kpi"]["runway_days"], len(data["recent"]), bool(data["api_error"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
