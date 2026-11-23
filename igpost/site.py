"""Build the GitHub Pages site that serves this week's media to Instagram.

Media files live as assets of GitHub releases named media-<week> (e.g. media-2026-W48),
so they never bloat the git history. This step copies the assets that are still
needed into _site/media/<week>/ for GitHub Pages.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import Config
from .plans import Plan
from .publisher import DONE_STATES

log = logging.getLogger(__name__)

API = "https://api.github.com"
SITE_LIMIT_BYTES = 950_000_000  # GitHub Pages: max. 1 GB


class SiteError(RuntimeError):
    pass


def release_tag(week: str) -> str:
    return f"media-{week}"


def weeks_needing_media(plans: list[Plan], posted: dict, now: datetime) -> dict[str, set[str]]:
    """Approved weeks with items that are not done yet (or were due in the last day)."""
    keep_until = now - timedelta(days=1)
    needed: dict[str, set[str]] = {}
    for plan in plans:
        if not plan.approved:
            continue
        for item in plan.items:
            done = (posted.get(item.id) or {}).get("status") in DONE_STATES
            if not done or item.at >= keep_until:
                needed.setdefault(plan.week, set()).add(item.media)
    return needed


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return h


def _release_assets(repo: str, tag: str) -> dict[str, dict]:
    resp = requests.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=_headers(), timeout=30)
    if resp.status_code == 404:
        raise SiteError(f"Release {tag} fehlt – Medien der Woche wurden noch nicht hochgeladen")
    resp.raise_for_status()
    return {a["name"]: a for a in resp.json().get("assets", [])}


def _download(asset: dict, target: Path) -> None:
    headers = _headers() | {"Accept": "application/octet-stream"}
    with requests.get(asset["url"], headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        tmp = target.with_suffix(target.suffix + ".part")
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        tmp.replace(target)


def build_site(out: Path, plans: list[Plan], posted: dict, config: Config,
               now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if out.exists():
        shutil.rmtree(out)
    (out / "media").mkdir(parents=True)
    (out / ".nojekyll").write_text("")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><meta name=robots content=noindex>"
        "<title>techeroesuniverse media</title><p>Media host for @techeroesuniverse.</p>\n",
        encoding="utf-8",
    )

    total = 0
    needed = weeks_needing_media(plans, posted, now)
    for week, files in sorted(needed.items()):
        assets = _release_assets(config.github_repo, release_tag(week))
        missing = sorted(f for f in files if f not in assets)
        if missing:
            raise SiteError(f"{release_tag(week)}: fehlende Dateien {missing}")
        week_dir = out / "media" / week
        week_dir.mkdir(parents=True)
        for name in sorted(files):
            asset = assets[name]
            if asset["size"] > config.max_media_bytes:
                raise SiteError(f"{name} ist größer als {config.max_media_bytes} Bytes")
            _download(asset, week_dir / name)
            total += asset["size"]
            log.info("%s/%s (%.1f MB)", week, name, asset["size"] / 1e6)
    if total > SITE_LIMIT_BYTES:
        raise SiteError(f"Seite wäre {total / 1e6:.0f} MB groß – GitHub Pages erlaubt max. 1 GB")
    log.info("Pages-Seite gebaut: %d Wochen, %.1f MB", len(needed), total / 1e6)
    return total
