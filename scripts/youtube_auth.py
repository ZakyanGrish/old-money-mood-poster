#!/usr/bin/env python3
"""One-time: grant this app upload access to your YouTube channel.

Run once on your Mac:

    python3 scripts/youtube_auth.py

It opens a Google sign-in in your browser. Sign in with the account that owns the
Old Money Mood YouTube channel, click through the "Google hasn't verified this
app" screen (Advanced -> Go to ...), and approve. The script then prints a
refresh token -- paste it into the GitHub secret YOUTUBE_REFRESH_TOKEN.

Needs YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env (Desktop-app client).
"""

from __future__ import annotations

import http.server
import os
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smposter.config import load_env  # noqa: E402

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
PORT = 8766
REDIRECT = "http://127.0.0.1:%d/" % PORT

_code = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        _code["code"] = (params.get("code") or [None])[0]
        _code["error"] = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = "Authorized. You can close this tab and return to the terminal." if _code.get("code") \
            else "Authorization failed: %s" % _code.get("error")
        self.wfile.write(("<html><body style='font-family:sans-serif;padding:40px'>%s</body></html>" % msg).encode())

    def log_message(self, *a):  # silence
        pass


def main() -> int:
    load_env()
    cid = os.environ.get("YOUTUBE_CLIENT_ID", "")
    sec = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
    if not (cid and sec):
        print("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first.")
        return 1

    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": cid,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })

    srv = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    print("\nOpening your browser to authorize. If it doesn't open, visit:\n%s\n" % url)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print("Waiting for the redirect...")
    for _ in range(300):
        if "code" in _code or "error" in _code:
            break
        threading.Event().wait(1)

    if not _code.get("code"):
        print("No authorization code received (%s)." % _code.get("error"))
        return 1

    r = requests.post(TOKEN, data={
        "client_id": cid,
        "client_secret": sec,
        "code": _code["code"],
        "redirect_uri": REDIRECT,
        "grant_type": "authorization_code",
    }, timeout=30)
    d = r.json()
    if "refresh_token" not in d:
        print("Token exchange did not return a refresh_token: %s" % d)
        print("Tip: revoke prior access at myaccount.google.com/permissions and rerun.")
        return 1

    print("\n=== YOUTUBE_REFRESH_TOKEN ===")
    print(d["refresh_token"])
    print("\nPaste that into the GitHub secret YOUTUBE_REFRESH_TOKEN, then also add")
    print("YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET as secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
