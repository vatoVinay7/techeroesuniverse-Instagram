"""Post everything from approved plans that is due now.

Run by GitHub Actions every 15 minutes. Idempotent and crash-safe:
  * state/posted.json records every finished item (posted, missed, manual, failed)
  * state/pending.json records containers created but not yet published, so a
    crashed or timed-out run continues with the same container instead of
    creating a duplicate post.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import requests

from .config import PENDING_PATH, POSTED_PATH, Config
from .instagram import ContainerStatus, InstagramError
from .notify import notify
from .plans import PlanItem
from .statefile import read_json, write_json

log = logging.getLogger(__name__)

DONE_STATES = {"posted", "missed", "manual", "failed"}
MAX_ATTEMPTS = 3
VIDEO_READY_TIMEOUT_S = 600
IMAGE_READY_TIMEOUT_S = 120


class Client(Protocol):
    def create_container(self, ig_id: str, *, kind: str, media_url: str, is_video: bool,
                         caption: str | None = None) -> str: ...
    def container_status(self, container_id: str) -> ContainerStatus: ...
    def wait_until_ready(self, container_id: str, *, timeout_s: int, interval_s: int = 20) -> ContainerStatus: ...
    def publish(self, ig_id: str, container_id: str) -> str: ...
    def permalink(self, media_id: str) -> str | None: ...


class MediaNotReady(RuntimeError):
    pass


@dataclass
class RunResult:
    posted: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    reminded: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def due_items(items: list[PlanItem], posted: dict, now: datetime) -> list[PlanItem]:
    out = []
    for item in items:
        entry = posted.get(item.id)
        if entry and entry.get("status") in DONE_STATES:
            continue
        if item.at <= now:
            out.append(item)
    return sorted(out, key=lambda i: (i.at, i.id))


def check_media_url(url: str, item: PlanItem, max_bytes: int,
                    session: requests.Session | None = None) -> None:
    sess = session or requests.Session()
    try:
        resp = sess.head(url, allow_redirects=True, timeout=30)
    except requests.RequestException as exc:
        raise MediaNotReady(f"Medium nicht erreichbar ({exc}): {url}") from exc
    if resp.status_code != 200:
        raise MediaNotReady(f"Medium nicht online (HTTP {resp.status_code}): {url} – "
                            "wurde der Pages-Workflow für diese Woche ausgeführt?")
    ctype = resp.headers.get("Content-Type", "")
    expected = "video/" if item.is_video else "image/jpeg"
    if not ctype.startswith(expected):
        raise MediaNotReady(f"Falscher Dateityp {ctype!r} für {url}")
    size = int(resp.headers.get("Content-Length") or 0)
    if size > max_bytes:
        raise MediaNotReady(f"Datei zu groß ({size} Bytes) für {url}")


class Publisher:
    def __init__(self, config: Config, client_factory: Callable[[], tuple[Client, str]], *,
                 media_check: Callable[[str, PlanItem, int], None] = check_media_url,
                 notifier: Callable[[str, str], None] = notify):
        self.config = config
        self._client_factory = client_factory
        self._client: Client | None = None
        self._ig_id: str | None = None
        self._media_check = media_check
        self._notify = notifier
        self.posted: dict = read_json(POSTED_PATH, {})
        self.pending: dict = read_json(PENDING_PATH, {})

    # ------------------------------------------------------------------ state
    def _save(self) -> None:
        write_json(POSTED_PATH, self.posted)
        write_json(PENDING_PATH, self.pending)

    def _finish(self, item: PlanItem, status: str, now: datetime, **extra) -> None:
        self.posted[item.id] = {
            "status": status, "kind": item.kind, "week": item.week, "library_id": item.library_id,
            "media": item.media, "planned_at": item.at.isoformat(), "done_at": now.isoformat(), **extra,
        }
        self.pending.pop(item.id, None)
        self._save()

    def _client_and_id(self) -> tuple[Client, str]:
        if self._client is None:
            self._client, self._ig_id = self._client_factory()
        return self._client, self._ig_id  # type: ignore[return-value]

    # ------------------------------------------------------------------ run
    def run(self, items: list[PlanItem], now: datetime | None = None) -> RunResult:
        now = now or datetime.now(timezone.utc)
        result = RunResult()
        due = due_items(items, self.posted, now)
        if not due:
            log.info("Nichts fällig.")
            return result

        max_delay = timedelta(minutes=self.config.max_delay_minutes)
        for item in due[: self.config.max_posts_per_run]:
            label = f"{item.kind} {item.id} ({item.at.astimezone(self.config.timezone):%a %d.%m. %H:%M})"
            if now - item.at > max_delay and item.id not in self.pending:
                self._finish(item, "missed", now)
                result.missed.append(item.id)
                self._notify(f"Verpasst: {item.id}",
                             f"{label} wurde nicht rechtzeitig gepostet (mehr als "
                             f"{self.config.max_delay_minutes} Minuten zu spät) und wird übersprungen.")
                continue

            if item.manual:
                url = self.config.media_url(item.week, item.media)
                self._finish(item, "manual", now)
                result.reminded.append(item.id)
                self._notify(f"Jetzt selbst posten: Story {item.id}",
                             f"Diese Story hat einen Sticker (Umfrage/Quiz/Link) und muss in der "
                             f"Instagram-App gepostet werden.\n\n- Bild/Video: {url}\n"
                             f"- Hinweis: {item.note or '–'}")
                continue

            try:
                outcome = self._post(item, now)
            except InstagramError as exc:
                if exc.auth_problem:
                    result.errors.append(f"{item.id}: {exc}")
                    self._notify("Instagram-Zugang ungültig",
                                 f"Der Instagram-Token wurde abgelehnt ({exc}). Bitte in Meta for "
                                 "Developers einen neuen Token erzeugen und das Secret "
                                 "IG_ACCESS_TOKEN in GitHub ersetzen.")
                    break
                self._record_failure(item, str(exc), now, label, result)
            except MediaNotReady as exc:
                self._record_failure(item, str(exc), now, label, result)
            else:
                if outcome == "posted":
                    result.posted.append(item.id)
                elif outcome == "waiting":
                    result.waiting.append(item.id)
        return result

    def _record_failure(self, item: PlanItem, error: str, now: datetime, label: str, result: RunResult) -> None:
        log.error("%s: %s", item.id, error)
        result.errors.append(f"{item.id}: {error}")
        entry = self.pending.setdefault(item.id, {})
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_error"] = error
        entry.pop("container_id", None)
        if entry["attempts"] >= MAX_ATTEMPTS:
            self._finish(item, "failed", now, error=error)
            self._notify(f"Fehlgeschlagen: {item.id}",
                         f"{label} konnte nach {MAX_ATTEMPTS} Versuchen nicht gepostet werden.\n\n"
                         f"Letzter Fehler: `{error}`")
        else:
            self._save()

    def _post(self, item: PlanItem, now: datetime) -> str:
        client, ig_id = self._client_and_id()
        url = self.config.media_url(item.week, item.media)
        timeout = VIDEO_READY_TIMEOUT_S if item.is_video else IMAGE_READY_TIMEOUT_S

        container_id = (self.pending.get(item.id) or {}).get("container_id")
        if container_id:
            status = client.container_status(container_id)
            log.info("%s: vorhandener Container %s ist %s", item.id, container_id, status.code)
            if status.code == "PUBLISHED":
                self._finish(item, "posted", now, container_id=container_id, note="bereits veröffentlicht")
                return "posted"
            if status.code in {"ERROR", "EXPIRED"}:
                self.pending[item.id].pop("container_id", None)
                self._save()
                container_id = None

        if not container_id:
            self._media_check(url, item, self.config.max_media_bytes)
            caption = item.full_caption() if item.kind == "reel" else None
            container_id = client.create_container(ig_id, kind=item.kind, media_url=url,
                                                   is_video=item.is_video, caption=caption)
            entry = self.pending.setdefault(item.id, {})
            entry.update(container_id=container_id, created_at=now.isoformat())
            self._save()
            log.info("%s: Container %s angelegt", item.id, container_id)

        status = client.wait_until_ready(container_id, timeout_s=timeout)
        if status.code == "IN_PROGRESS":
            log.info("%s: Instagram verarbeitet noch – nächster Lauf macht weiter", item.id)
            return "waiting"
        if status.code == "PUBLISHED":
            self._finish(item, "posted", now, container_id=container_id)
            return "posted"
        if status.code != "FINISHED":
            raise InstagramError(f"Container {container_id} ist {status.code}: {status.detail or ''}".strip())

        media_id = client.publish(ig_id, container_id)
        permalink = client.permalink(media_id)
        self._finish(item, "posted", now, container_id=container_id, media_id=media_id, permalink=permalink)
        log.info("%s: veröffentlicht als %s %s", item.id, media_id, permalink or "")
        return "posted"
