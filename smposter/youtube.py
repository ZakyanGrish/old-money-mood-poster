"""Minimal YouTube Data API v3 uploader.

Auth is OAuth2 with a long-lived refresh token (app published-but-unverified, so
the token does not expire on a 7-day clock). The API has no pull-from-URL, so a
remote file is downloaded to a temp path and streamed up with a resumable
upload session.

Quota: an upload costs 1600 units of the default 10,000/day allowance -> ~6/day.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import List, Optional

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"


class YouTubeError(RuntimeError):
    pass


class YouTubeClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.session = requests.Session()
        self._access_token: Optional[str] = None

    @classmethod
    def from_env(cls) -> Optional["YouTubeClient"]:
        cid = os.environ.get("YOUTUBE_CLIENT_ID", "")
        sec = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
        rt = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
        if not (cid and sec and rt):
            return None
        return cls(cid, sec, rt)

    # ---- auth ----------------------------------------------------------------
    def _refresh(self) -> str:
        r = self.session.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        d = r.json()
        if "access_token" not in d:
            raise YouTubeError("token refresh failed: %s" % d)
        self._access_token = d["access_token"]
        return self._access_token

    def _auth_header(self) -> dict:
        if not self._access_token:
            self._refresh()
        return {"Authorization": "Bearer %s" % self._access_token}

    # ---- upload -----------------------------------------------------------
    def upload(
        self,
        source_url: str,
        title: str,
        description: str = "",
        tags: Optional[List[str]] = None,
        category_id: str = "22",
        privacy: str = "public",
    ) -> dict:
        title = (title or "Old Money Mood").replace("<", "").replace(">", "")[:100]
        body = {
            "snippet": {
                "title": title,
                "description": description[:4900],
                "tags": (tags or [])[:15],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        try:
            with self.session.get(source_url, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    tmp.write(chunk)
            tmp.flush()
            tmp.close()
            size = os.path.getsize(tmp.name)

            # 1. open a resumable session
            init = self.session.post(
                UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    **self._auth_header(),
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/*",
                    "X-Upload-Content-Length": str(size),
                },
                data=json.dumps(body),
                timeout=30,
            )
            if init.status_code == 401:                      # token expired mid-run
                self._refresh()
                return self.upload(source_url, title, description, tags, category_id, privacy)
            if init.status_code >= 400 or "location" not in {k.lower() for k in init.headers}:
                raise YouTubeError("resumable init failed %s: %s" % (init.status_code, init.text[:300]))
            up_url = init.headers["Location"]

            # 2. send the bytes
            with open(tmp.name, "rb") as fh:
                put = self.session.put(
                    up_url,
                    headers={"Content-Type": "video/*", "Content-Length": str(size)},
                    data=fh,
                    timeout=600,
                )
            d = put.json() if put.content else {}
            if put.status_code >= 400 or "id" not in d:
                raise YouTubeError("upload failed %s: %s" % (put.status_code, put.text[:300]))
            return d
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
