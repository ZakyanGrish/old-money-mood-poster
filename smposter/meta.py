"""Thin wrapper around the Meta Graph API for Instagram + Facebook Page publishing.

Instagram publishing is a two-step flow:
  1. POST /{ig-user-id}/media        -> returns a creation_id (a "media container")
  2. POST /{ig-user-id}/media_publish -> publishes that container

Images and videos must be reachable at a public HTTPS URL — Meta fetches them,
you cannot upload bytes directly for Instagram. Images must be JPEG.
"""

from __future__ import annotations

import time
from typing import List, Optional

import requests

GRAPH = "https://graph.facebook.com"
DEFAULT_VERSION = "v21.0"


class MetaError(RuntimeError):
    pass


class MetaClient:
    def __init__(self, access_token: str, api_version: str = DEFAULT_VERSION):
        self.token = access_token
        self.base = "%s/%s" % (GRAPH, api_version)
        self.session = requests.Session()

    # ---- low-level ---------------------------------------------------------
    def _call(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        url = "%s/%s" % (self.base, path.lstrip("/"))
        resp = self.session.request(method, url, params=params, timeout=60)
        try:
            data = resp.json()
        except ValueError:
            raise MetaError("Non-JSON response (%s): %s" % (resp.status_code, resp.text[:300]))
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            raise MetaError(
                "Graph API error %s: %s (type=%s, code=%s, subcode=%s)"
                % (
                    resp.status_code,
                    err.get("message", data),
                    err.get("type"),
                    err.get("code"),
                    err.get("error_subcode"),
                )
            )
        return data

    # ---- discovery ------------------------------------------------------------
    def list_pages(self) -> List[dict]:
        """Pages the token can manage, each with its linked IG business account."""
        out: List[dict] = []
        data = self._call(
            "GET", "me/accounts",
            fields="id,name,access_token,instagram_business_account{id,username}",
        )
        out.extend(data.get("data", []))
        while data.get("paging", {}).get("next"):
            resp = self.session.get(data["paging"]["next"], timeout=60)
            data = resp.json()
            out.extend(data.get("data", []))
        return out

    def publishing_limit(self, ig_user_id: str) -> dict:
        data = self._call(
            "GET", "%s/content_publishing_limit" % ig_user_id,
            fields="config,quota_usage",
        )
        return (data.get("data") or [{}])[0]

    def media_score(self, media_id: str) -> float:
        """A single 'how well did this do' number for ranking past posts.

        Prefers reach (from insights); falls back to likes + comments; 0 on error.
        """
        try:
            data = self._call("GET", "%s/insights" % media_id, metric="reach")
            for row in data.get("data", []):
                vals = row.get("values") or []
                if vals and isinstance(vals[0], dict) and "value" in vals[0]:
                    return float(vals[0]["value"])
        except MetaError:
            pass
        try:
            d = self._call("GET", media_id, fields="like_count,comments_count")
            return float(d.get("like_count", 0)) + float(d.get("comments_count", 0))
        except MetaError:
            return 0.0

    # ---- instagram publishing ----------------------------------------------
    def _create_container(self, ig_user_id: str, **params) -> str:
        data = self._call("POST", "%s/media" % ig_user_id, **params)
        cid = data.get("id")
        if not cid:
            raise MetaError("No container id returned: %s" % data)
        return cid

    def _wait_ready(self, container_id: str, timeout_s: int = 300, interval_s: int = 5) -> None:
        """Poll a container until it reports FINISHED.

        Every container — image, carousel, video — must reach FINISHED before
        media_publish will accept it; publishing sooner returns OAuthException
        9007 / subcode 2207027 ("Media ID is not available").
        """
        deadline = time.time() + timeout_s
        last = None
        while time.time() < deadline:
            data = self._call("GET", container_id, fields="status_code,status")
            last = data.get("status_code")
            if last == "FINISHED":
                return
            if last == "ERROR":
                raise MetaError("Container %s failed: %s" % (container_id, data.get("status")))
            time.sleep(interval_s)
        raise MetaError("Container %s not FINISHED after %ss (last=%s)" % (container_id, timeout_s, last))

    def _publish(self, ig_user_id: str, creation_id: str) -> dict:
        return self._call("POST", "%s/media_publish" % ig_user_id, creation_id=creation_id)

    def post_image(self, ig_user_id: str, image_url: str, caption: str = "") -> dict:
        cid = self._create_container(ig_user_id, image_url=image_url, caption=caption)
        self._wait_ready(cid, timeout_s=120, interval_s=3)
        return self._publish(ig_user_id, cid)

    def post_reel(
        self,
        ig_user_id: str,
        video_url: str,
        caption: str = "",
        cover_url: Optional[str] = None,
        share_to_feed: bool = True,
    ) -> dict:
        params = dict(
            media_type="REELS",
            video_url=video_url,
            caption=caption,
            share_to_feed="true" if share_to_feed else "false",
        )
        if cover_url:
            params["cover_url"] = cover_url
        cid = self._create_container(ig_user_id, **params)
        self._wait_ready(cid)
        return self._publish(ig_user_id, cid)

    def post_carousel(self, ig_user_id: str, image_urls: List[str], caption: str = "") -> dict:
        if not 2 <= len(image_urls) <= 10:
            raise MetaError("Carousel needs 2-10 images, got %d" % len(image_urls))
        child_ids = []
        for url in image_urls:
            child_ids.append(
                self._create_container(ig_user_id, image_url=url, is_carousel_item="true")
            )
        for cid in child_ids:
            self._wait_ready(cid, timeout_s=120, interval_s=3)
        parent = self._create_container(
            ig_user_id, media_type="CAROUSEL", children=",".join(child_ids), caption=caption
        )
        self._wait_ready(parent, timeout_s=120, interval_s=3)
        return self._publish(ig_user_id, parent)

    def post_story(
        self,
        ig_user_id: str,
        image_url: Optional[str] = None,
        video_url: Optional[str] = None,
    ) -> dict:
        """Publish a photo or video Story. No stickers/polls/music/links via API."""
        if bool(image_url) == bool(video_url):
            raise MetaError("post_story needs exactly one of image_url / video_url")
        params = dict(media_type="STORIES")
        if image_url:
            params["image_url"] = image_url
        else:
            params["video_url"] = video_url
        cid = self._create_container(ig_user_id, **params)
        self._wait_ready(cid, timeout_s=300 if video_url else 120, interval_s=5 if video_url else 3)
        return self._publish(ig_user_id, cid)

    # ---- facebook page ----------------------------------------------------
    def page_post_text(self, page_id: str, page_token: str, message: str, link: Optional[str] = None) -> dict:
        params = {"message": message, "access_token": page_token}
        if link:
            params["link"] = link
        url = "%s/%s/feed" % (self.base, page_id)
        resp = self.session.post(url, params=params, timeout=60)
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            raise MetaError("Page post failed: %s" % data.get("error", data))
        return data

    def page_post_photo(self, page_id: str, page_token: str, image_url: str, caption: str = "") -> dict:
        params = {"url": image_url, "caption": caption, "access_token": page_token}
        url = "%s/%s/photos" % (self.base, page_id)
        resp = self.session.post(url, params=params, timeout=60)
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            raise MetaError("Page photo failed: %s" % data.get("error", data))
        return data
