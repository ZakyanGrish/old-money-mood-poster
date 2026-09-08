#!/usr/bin/env python3
"""Discover the Page IDs and Instagram Business Account IDs your token can reach.

Usage:
    python scripts/meta_get_ids.py                 # uses META_ACCESS_TOKEN from .env
    python scripts/meta_get_ids.py <access_token>  # or pass one explicitly

Prints a ready-to-paste accounts.json skeleton.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smposter.config import load_env  # noqa: E402
from smposter.meta import MetaClient, MetaError  # noqa: E402


def main() -> int:
    load_env()
    token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        print("No token. Pass one as an argument or set META_ACCESS_TOKEN in .env.")
        return 1

    client = MetaClient(token)
    try:
        pages = client.list_pages()
    except MetaError as e:
        print("Failed to list pages:\n  %s" % e)
        return 1

    if not pages:
        print("Token reached no Pages. Check that your token has pages_show_list and")
        print("that your Facebook user has a role on the Page.")
        return 1

    skeleton = {}
    for p in pages:
        iga = p.get("instagram_business_account") or {}
        print("Page:  %s" % p.get("name"))
        print("  page_id:        %s" % p.get("id"))
        if iga:
            print("  ig_user_id:     %s  (@%s)" % (iga.get("id"), iga.get("username")))
        else:
            print("  ig_user_id:     (none — no Instagram Business account linked to this Page)")
        print()
        key = (iga.get("username") or p.get("name") or p.get("id"))
        key = str(key).lower().replace(" ", "-")
        skeleton[key] = {
            "ig_user_id": iga.get("id"),
            "fb_page_id": p.get("id"),
            "token_env": None,
        }

    print("---- paste into accounts.json ----")
    print(json.dumps(skeleton, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
