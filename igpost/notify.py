"""Notifications via GitHub Issues (Vinay gets an e-mail / app notification).

Inside GitHub Actions GITHUB_TOKEN and GITHUB_REPOSITORY are set. Locally the
message is only printed.
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

API = "https://api.github.com"
OWNER_MENTION = "@vatoVinay7"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def notify(title: str, body: str, *, label: str = "bot") -> None:
    """Open an issue, or comment on an open issue with the same title (no duplicates)."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    text = f"{OWNER_MENTION}\n\n{body}"
    if not token or not repo:
        log.warning("[Meldung] %s\n%s", title, body)
        return
    try:
        resp = requests.get(f"{API}/repos/{repo}/issues", headers=_headers(token),
                            params={"state": "open", "labels": label, "per_page": 100}, timeout=30)
        resp.raise_for_status()
        existing = next((i for i in resp.json() if i.get("title") == title), None)
        if existing:
            requests.post(f"{API}/repos/{repo}/issues/{existing['number']}/comments",
                          headers=_headers(token), json={"body": text}, timeout=30).raise_for_status()
        else:
            requests.post(f"{API}/repos/{repo}/issues", headers=_headers(token),
                          json={"title": title, "body": text, "labels": [label]}, timeout=30).raise_for_status()
    except requests.RequestException as exc:
        # A failed notification must never hide the original problem in the logs.
        log.error("Meldung konnte nicht als Issue angelegt werden (%s): %s – %s", exc, title, body)
