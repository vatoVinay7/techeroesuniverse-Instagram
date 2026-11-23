"""Build the GitHub Pages site that serves this week's media to Instagram.

Media files live on separate branches named media/<week> (e.g. media/2026-W48) that
contain nothing but that week's files. They never touch main, and branches of weeks
that are done get deleted again (scripts/push-media.sh creates them, `prune-media`
removes them). This step copies the files that are still needed into
_site/media/<week>/ for GitHub Pages.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, Config
from .plans import Plan
from .publisher import DONE_STATES

log = logging.getLogger(__name__)

SITE_LIMIT_BYTES = 950_000_000  # GitHub Pages: max. 1 GB
BRANCH_PREFIX = "media/"


class SiteError(RuntimeError):
    pass


def media_branch(week: str) -> str:
    return f"{BRANCH_PREFIX}{week}"


def weeks_needing_media(plans: list[Plan], posted: dict, now: datetime) -> dict[str, set[str]]:
    """Approved weeks with items that are not done yet (or were due within the last day)."""
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


def _git(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=capture)


def _fetch_branch(week: str) -> str:
    branch = media_branch(week)
    ref = f"refs/remotes/origin/{branch}"
    try:
        _git("fetch", "--depth=1", "origin", f"+refs/heads/{branch}:{ref}")
    except subprocess.CalledProcessError as exc:
        raise SiteError(f"Branch {branch} fehlt – Medien der Woche wurden noch nicht hochgeladen") from exc
    return ref


def remote_media_weeks() -> list[str]:
    out = _git("ls-remote", "--heads", "origin", f"{BRANCH_PREFIX}*").stdout.decode()
    return sorted(line.split("refs/heads/" + BRANCH_PREFIX, 1)[1] for line in out.splitlines() if line.strip())


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
        ref = _fetch_branch(week)
        week_dir = out / "media" / week
        week_dir.mkdir(parents=True)
        for name in sorted(files):
            spec = f"{ref}:{name}"
            try:
                size = int(_git("cat-file", "-s", spec).stdout.decode().strip())
            except subprocess.CalledProcessError as exc:
                raise SiteError(f"{media_branch(week)}: Datei {name} fehlt") from exc
            if size > config.max_media_bytes:
                raise SiteError(f"{name} ist größer als {config.max_media_bytes} Bytes")
            with (week_dir / name).open("wb") as fh:
                subprocess.run(["git", "cat-file", "blob", spec], cwd=ROOT, check=True, stdout=fh)
            total += size
            log.info("%s/%s (%.1f MB)", week, name, size / 1e6)
    if total > SITE_LIMIT_BYTES:
        raise SiteError(f"Seite wäre {total / 1e6:.0f} MB groß – GitHub Pages erlaubt max. 1 GB")
    log.info("Pages-Seite gebaut: %d Wochen, %.1f MB", len(needed), total / 1e6)
    return total


def prune_media(plans: list[Plan], posted: dict, now: datetime | None = None, *, dry_run: bool = False) -> list[str]:
    """Delete media/<week> branches that no plan needs anymore."""
    now = now or datetime.now(timezone.utc)
    needed = set(weeks_needing_media(plans, posted, now))
    planned_unapproved = {p.week for p in plans if not p.approved}
    stale = [w for w in remote_media_weeks() if w not in needed and w not in planned_unapproved]
    for week in stale:
        log.info("Lösche alten Medien-Branch %s", media_branch(week))
        if not dry_run:
            _git("push", "origin", "--delete", media_branch(week))
    return stale
