#!/usr/bin/env python3
"""Post to a configured account.

Examples:
    python post.py --account brand-a --image https://example.com/pic.jpg --caption "hello"
    python post.py --account brand-a --reel  https://example.com/clip.mp4 --caption "new reel"
    python post.py --account brand-a --carousel https://e.com/1.jpg https://e.com/2.jpg --caption "x"
    python post.py --account brand-a --check          # show remaining publish quota

Notes:
  * Instagram fetches media from the URL you pass — it must be public HTTPS.
    Images must be JPEG. Use --dry-run to validate config without posting.
"""

from __future__ import annotations

import argparse
import sys

from smposter.config import get_account
from smposter.meta import MetaClient, MetaError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--account", required=True, help="account key from accounts.json")
    p.add_argument("--caption", default="", help="caption / post text")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--image", metavar="URL", help="single image post (public JPEG URL)")
    g.add_argument("--reel", metavar="URL", help="Reel / video post (public MP4 URL)")
    g.add_argument("--carousel", nargs="+", metavar="URL", help="2-10 image URLs")
    g.add_argument("--story", metavar="URL", help="photo or video Story (public URL)")
    g.add_argument("--check", action="store_true", help="print publishing quota and exit")
    p.add_argument("--no-feed", action="store_true", help="Reel only: do not also share to feed")
    p.add_argument("--dry-run", action="store_true", help="resolve account + token, do not post")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    acct = get_account(args.account)
    client = MetaClient(acct.access_token)

    print("account=%s  ig_user_id=%s  fb_page_id=%s" % (acct.name, acct.ig_user_id, acct.fb_page_id or "-"))

    if args.check:
        info = client.publishing_limit(acct.ig_user_id)
        quota = info.get("config", {}).get("quota_total", 100)
        used = info.get("quota_usage", 0)
        print("Instagram publishing: %s / %s used in last 24h" % (used, quota))
        return 0

    if args.dry_run:
        print("dry-run OK — token resolved, account valid. Nothing posted.")
        return 0

    try:
        if args.image:
            res = client.post_image(acct.ig_user_id, args.image, args.caption)
        elif args.reel:
            res = client.post_reel(
                acct.ig_user_id, args.reel, args.caption, share_to_feed=not args.no_feed
            )
        elif args.carousel:
            res = client.post_carousel(acct.ig_user_id, args.carousel, args.caption)
        elif args.story:
            is_video = args.story.lower().split("?")[0].endswith((".mp4", ".mov"))
            res = client.post_story(
                acct.ig_user_id,
                video_url=args.story if is_video else None,
                image_url=None if is_video else args.story,
            )
        else:
            print("Nothing to post. Pass --image / --reel / --carousel / --story / --check.")
            return 2
    except MetaError as e:
        print("POST FAILED:\n  %s" % e)
        return 1

    print("Published. media id: %s" % res.get("id"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
