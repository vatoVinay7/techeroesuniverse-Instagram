"""Minimal client for the Instagram API with Instagram Login (graph.instagram.com).

Publishing is a two-step flow:
  1. POST /{ig_id}/media          -> container id (Instagram fetches the media URL)
  2. GET  /{container}?fields=status_code until FINISHED
  3. POST /{ig_id}/media_publish  -> media id
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

GRAPH_HOST = "https://graph.instagram.com"

# Error codes Meta documents as temporary (rate limiting / transient).
TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 368, 613, 9004, 9007}


class InstagramError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, subcode: int | None = None,
                 status: int | None = None, trace_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.status = status
        self.trace_id = trace_id

    @property
    def transient(self) -> bool:
        return (self.status is not None and self.status >= 500) or self.code in TRANSIENT_CODES

    @property
    def auth_problem(self) -> bool:
        return self.code == 190 or self.status == 401

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.code is not None:
            parts.append(f"code={self.code}")
        if self.subcode is not None:
            parts.append(f"subcode={self.subcode}")
        if self.trace_id:
            parts.append(f"trace={self.trace_id}")
        return " | ".join(parts)


@dataclass(frozen=True)
class ContainerStatus:
    code: str          # EXPIRED | ERROR | FINISHED | IN_PROGRESS | PUBLISHED
    detail: str | None


class InstagramClient:
    def __init__(self, access_token: str, api_version: str, *, session: requests.Session | None = None,
                 timeout: float = 60.0, max_retries: int = 3):
        if not access_token:
            raise ValueError("access_token fehlt")
        self._token = access_token
        self._version = api_version
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries

    # ------------------------------------------------------------------ plumbing
    def _url(self, path: str) -> str:
        return f"{GRAPH_HOST}/{self._version}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                 data: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self._url(path)
        headers = {"Authorization": f"Bearer {self._token}"}
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._session.request(method, url, params=params, data=data,
                                             headers=headers, timeout=self._timeout)
            except requests.RequestException as exc:
                if attempt <= self._max_retries:
                    wait = 5 * attempt
                    log.warning("Netzwerkfehler (%s), neuer Versuch in %ss", exc, wait)
                    time.sleep(wait)
                    continue
                raise InstagramError(f"Netzwerkfehler: {exc}") from exc

            payload = _json_or_empty(resp)
            if resp.ok and "error" not in payload:
                return payload

            err = _to_error(resp, payload)
            if err.transient and attempt <= self._max_retries:
                wait = 15 * attempt
                log.warning("Vorübergehender API-Fehler (%s), neuer Versuch in %ss", err, wait)
                time.sleep(wait)
                continue
            raise err

    # ------------------------------------------------------------------ account
    def me(self) -> dict[str, Any]:
        return self._request("GET", "me", params={"fields": "user_id,username,account_type"})

    def publishing_quota(self, ig_id: str) -> dict[str, Any]:
        data = self._request("GET", f"{ig_id}/content_publishing_limit",
                             params={"fields": "quota_usage,config"})
        items = data.get("data") or [{}]
        return items[0]

    # ------------------------------------------------------------------ publishing
    def create_container(self, ig_id: str, *, kind: str, media_url: str, is_video: bool,
                         caption: str | None = None) -> str:
        params: dict[str, Any] = {}
        if kind == "reel":
            if not is_video:
                raise ValueError("Ein Reel braucht ein Video")
            params.update(media_type="REELS", video_url=media_url, share_to_feed="true")
        elif kind == "story":
            params["media_type"] = "STORIES"
            params["video_url" if is_video else "image_url"] = media_url
        else:
            raise ValueError(f"Unbekannter Typ: {kind}")
        if caption and kind == "reel":
            params["caption"] = caption
        data = self._request("POST", f"{ig_id}/media", data=params)
        container_id = data.get("id")
        if not container_id:
            raise InstagramError(f"Keine Container-ID erhalten: {data}")
        return str(container_id)

    def container_status(self, container_id: str) -> ContainerStatus:
        data = self._request("GET", container_id, params={"fields": "status_code,status"})
        return ContainerStatus(code=str(data.get("status_code", "")), detail=data.get("status"))

    def wait_until_ready(self, container_id: str, *, timeout_s: int, interval_s: int = 20) -> ContainerStatus:
        deadline = time.monotonic() + timeout_s
        while True:
            status = self.container_status(container_id)
            if status.code != "IN_PROGRESS":
                return status
            if time.monotonic() >= deadline:
                return status
            time.sleep(interval_s)

    def publish(self, ig_id: str, container_id: str) -> str:
        data = self._request("POST", f"{ig_id}/media_publish", data={"creation_id": container_id})
        media_id = data.get("id")
        if not media_id:
            raise InstagramError(f"Keine Media-ID erhalten: {data}")
        return str(media_id)

    def permalink(self, media_id: str) -> str | None:
        try:
            return self._request("GET", media_id, params={"fields": "permalink"}).get("permalink")
        except InstagramError as exc:  # Stories haben teils keinen Permalink
            log.info("Kein Permalink für %s: %s", media_id, exc)
            return None


def refresh_long_lived_token(token: str, *, session: requests.Session | None = None,
                             timeout: float = 30.0) -> dict[str, Any]:
    """Exchange a long-lived token (>= 24 h old) for a fresh one valid 60 days."""
    sess = session or requests.Session()
    resp = sess.get(f"{GRAPH_HOST}/refresh_access_token",
                    params={"grant_type": "ig_refresh_token", "access_token": token},
                    timeout=timeout)
    payload = _json_or_empty(resp)
    if not resp.ok or "error" in payload or "access_token" not in payload:
        raise _to_error(resp, payload)
    return payload


def _json_or_empty(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _to_error(resp: requests.Response, payload: dict[str, Any]) -> InstagramError:
    err = payload.get("error") or {}
    message = err.get("error_user_msg") or err.get("message") or resp.text[:300] or resp.reason
    return InstagramError(
        str(message),
        code=err.get("code"),
        subcode=err.get("error_subcode"),
        status=resp.status_code,
        trace_id=err.get("fbtrace_id"),
    )
