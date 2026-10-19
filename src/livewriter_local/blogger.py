"""OAuth2-backed mirror client for the Google Blogger API v3."""

from datetime import datetime, timedelta, timezone
import logging
import time

import httpx

logger = logging.getLogger(__name__)


class BloggerError(RuntimeError):
    pass


class BloggerMirror:
    token_url = "https://oauth2.googleapis.com/token"
    api_root = "https://www.googleapis.com/blogger/v3"

    def __init__(self, config, client: httpx.Client | None = None):
        self.config = config
        self.client = client or httpx.Client(timeout=20.0)
        self._access_token = ""
        self._token_expiry = 0.0

    def _token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expiry - 60:
            return self._access_token
        try:
            response = self.client.post(self.token_url, data={
                "client_id": self.config.blogger_client_id,
                "client_secret": self.config.blogger_client_secret,
                "refresh_token": self.config.blogger_refresh_token,
                "grant_type": "refresh_token",
            })
            response.raise_for_status()
            payload = response.json()
            self._access_token = payload["access_token"]
            self._token_expiry = time.monotonic() + int(payload.get("expires_in", 3600))
            return self._access_token
        except (httpx.HTTPError, KeyError, ValueError) as error:
            logger.error("Blogger OAuth token refresh failed")
            raise BloggerError("Could not refresh Blogger authorization; check OAuth settings") from error

    def publish(self, post: dict, remote_id: str | None = None, is_draft: bool = False) -> str:
        base = f"{self.api_root}/blogs/{self.config.blogger_blog_id}/posts"
        payload = {"title": post["title"], "content": post["description"]}
        labels = post.get("categories") or []
        if labels:
            payload["labels"] = labels
        if post.get("mt_keywords"):
            payload["labels"] = list(dict.fromkeys([*payload.get("labels", []), *post["mt_keywords"].split(",")]))
        try:
            headers = {"Authorization": f"Bearer {self._token()}"}
            if remote_id:
                was_draft = bool(post.get("blogger_is_draft", False))
                if is_draft and not was_draft:
                    self.client.post(f"{base}/{remote_id}/revert", headers=headers).raise_for_status()
                response = self.client.put(f"{base}/{remote_id}", headers=headers, json=payload)
                response.raise_for_status()
                if not is_draft and was_draft:
                    response = self.client.post(f"{base}/{remote_id}/publish", headers=headers)
            else:
                response = self.client.post(base, params={"isDraft": str(is_draft).lower()},
                                            headers=headers, json=payload)
            response.raise_for_status()
            remote_post_id = response.json().get("id") or remote_id
            if not remote_post_id:
                raise BloggerError("Blogger response did not include a post ID")
            return str(remote_post_id)
        except httpx.HTTPError as error:
            logger.error("Blogger API request failed with status %s", getattr(error.response, "status_code", "unknown"))
            raise BloggerError("Blogger did not accept this post; check the Blogger API setup") from error


def create_mirror(config) -> BloggerMirror | None:
    return BloggerMirror(config) if config.blogger_enabled else None