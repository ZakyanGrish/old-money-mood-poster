#!/usr/bin/env python3
"""Exchange a short-lived Graph API Explorer token for a 60-day long-lived token.

Usage:
    python scripts/exchange_token.py <short_lived_user_token>

Needs META_APP_ID and META_APP_SECRET in .env. Prints the long-lived token
and its expiry; paste it into .env as META_ACCESS_TOKEN.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smposter.config import load_env  # noqa: E402


def main() -> int:
    load_env()
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    app_id = os.environ.get("META_APP_ID", "")
    app_secret = os.environ.get("META_APP_SECRET", "")
    if not (app_id and app_secret):
        print("Set META_APP_ID and META_APP_SECRET in .env first.")
        return 1

    resp = requests.get(
        "https://graph.facebook.com/v21.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": sys.argv[1],
        },
        timeout=60,
    )
    data = resp.json()
    if "access_token" not in data:
        print("Exchange failed: %s" % data)
        return 1
    print("Long-lived token:\n%s\n" % data["access_token"])
    if "expires_in" in data:
        print("Expires in ~%d days" % (int(data["expires_in"]) // 86400))
    print("\nPaste it into .env as META_ACCESS_TOKEN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
