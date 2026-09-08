#!/usr/bin/env python3
"""Upload a local media file to Cloudinary and append a post to content/queue.json.

Examples:
    python scripts/upload_and_queue.py --type reel  --file ./clips/rules.mp4 \
        --caption "The 5 rules old money lives by.\n\nSave this.\n#oldmoneyaesthetic #oldmoneymood"

    python scripts/upload_and_queue.py --type image --file ./img/estate.jpg --caption "..." \
        --not-before 2026-02-10T17:00:00Z

    python scripts/upload_and_queue.py --type carousel --file a.jpg b.jpg c.jpg --caption "..."

    python scripts/upload_and_queue.py --type story --file ./img/story.jpg

Needs CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET in .env.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smposter.config import load_env  # noqa: E402

QUEUE_PATH = Path(__file__).resolve().parent.parent / "content" / "queue.json"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
VIDEO_EXT = (".mp4", ".mov", ".m4v")


def _cloudinary():
    load_env()
    name = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    key = os.environ.get("CLOUDINARY_API_KEY", "")
    secret = os.environ.get("CLOUDINARY_API_SECRET", "")
    if not (name and key and secret):
        raise SystemExit("Set CLOUDINARY_CLOUD_NAME / _API_KEY / _API_SECRET in .env first.")
    import cloudinary  # noqa: WPS433

    cloudinary.config(cloud_name=name, api_key=key, api_secret=secret, secure=True)
    return cloudinary


def _upload(path: Path, folder: str = "omm") -> str:
    cloudinary = _cloudinary()
    from cloudinary import uploader  # noqa: WPS433

    is_video = path.suffix.lower() in VIDEO_EXT
    kwargs = dict(folder=folder, resource_type="video" if is_video else "image", overwrite=False)
    if is_video and path.stat().st_size > 90 * 1024 * 1024:
        res = uploader.upload_large(str(path), chunk_size=20 * 1024 * 1024, **kwargs)
    else:
        res = uploader.upload(str(path), **kwargs)
    url = res.get("secure_url")
    if not url:
        raise SystemExit("Cloudinary upload returned no secure_url: %s" % res)
    return url


def _load_queue() -> list:
    if QUEUE_PATH.exists():
        return json.loads(QUEUE_PATH.read_text() or "[]")
    return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", required=True, choices=["reel", "image", "carousel", "story"])
    ap.add_argument("--file", required=True, nargs="+", help="local file(s); 2-10 for carousel")
    ap.add_argument("--caption", default="")
    ap.add_argument("--not-before", dest="not_before", default=None,
                    help="ISO-8601 UTC; item won't post before this")
    ap.add_argument("--id", default=None, help="queue id (default: date + filename)")
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.file]
    for p in paths:
        if not p.is_file():
            raise SystemExit("Not a file: %s" % p)
    if args.type == "carousel" and not 2 <= len(paths) <= 10:
        raise SystemExit("carousel needs 2-10 files")
    if args.type != "carousel" and len(paths) != 1:
        raise SystemExit("%s needs exactly one file" % args.type)

    print("Uploading %d file(s) to Cloudinary..." % len(paths))
    urls = [_upload(p) for p in paths]
    for u in urls:
        print("  ->", u)

    item = {
        "id": args.id or ("%s-%s" % (dt.date.today().isoformat(), paths[0].stem)),
        "type": args.type,
        "caption": args.caption,
        "not_before": args.not_before,
        "posted_at": None,
        "result_id": None,
    }
    if args.type == "carousel":
        item["media_urls"] = urls
    else:
        item["media_url"] = urls[0]

    queue = _load_queue()
    if any(it.get("id") == item["id"] for it in queue):
        raise SystemExit("Queue already has id %r — pass a different --id" % item["id"])
    queue.append(item)
    QUEUE_PATH.write_text(json.dumps(queue, indent=2) + "\n")
    print("\nQueued id=%s (%d item(s) now in queue)." % (item["id"], len(queue)))
    print("Commit + push content/queue.json to schedule it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
