"""Library, weekly plans, validation and the weekly reel suggestion."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable

import yaml

from .config import LIBRARY_PATH, PLANS_DIR, WEEKDAYS, Config

WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
MEDIA_RE = re.compile(r"^[A-Za-z0-9._-]+\.(mp4|mov|jpg|jpeg)$")
VIDEO_EXT = {".mp4", ".mov"}
MAX_CAPTION = 2200
MAX_HASHTAGS = 5


# ---------------------------------------------------------------------------- library
@dataclass(frozen=True)
class LibraryItem:
    id: str
    type: str                 # episode | explainer
    topic: str
    status: str               # available | hold
    caption: str
    hashtags: tuple[str, ...]
    drive_id: str | None = None
    source_name: str | None = None
    season: int | None = None
    episode: int | None = None
    priority: int | None = None

    @property
    def sort_key(self) -> tuple:
        if self.type == "episode":
            return (self.season or 0, self.episode or 0)
        return (self.priority or 999, self.id)


def load_library(path: Path = LIBRARY_PATH) -> list[LibraryItem]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = []
    seen = set()
    for entry in raw.get("items", []):
        item = LibraryItem(
            id=entry["id"], type=entry["type"], topic=entry["topic"], status=entry["status"],
            caption=entry["caption"].strip(), hashtags=tuple(entry.get("hashtags", [])),
            drive_id=entry.get("drive_id"), source_name=entry.get("source_name"),
            season=entry.get("season"), episode=entry.get("episode"), priority=entry.get("priority"),
        )
        if item.id in seen:
            raise ValueError(f"library.yaml: doppelte id {item.id}")
        if item.type not in {"episode", "explainer"}:
            raise ValueError(f"library.yaml: {item.id} hat unbekannten type {item.type}")
        if item.status not in {"available", "hold"}:
            raise ValueError(f"library.yaml: {item.id} hat unbekannten status {item.status}")
        problems = check_caption(item.caption, item.hashtags)
        if problems:
            raise ValueError(f"library.yaml: {item.id}: {'; '.join(problems)}")
        seen.add(item.id)
        items.append(item)
    return items


# ---------------------------------------------------------------------------- plans
@dataclass
class PlanItem:
    id: str
    kind: str                         # reel | story
    at: datetime                      # timezone-aware
    media: str
    week: str
    caption: str = ""
    hashtags: tuple[str, ...] = ()
    library_id: str | None = None
    manual: bool = False              # story with sticker -> Vinay posts it himself
    note: str | None = None

    @property
    def is_video(self) -> bool:
        return Path(self.media).suffix.lower() in VIDEO_EXT

    def full_caption(self) -> str:
        text = self.caption.strip()
        if self.hashtags:
            text = f"{text}\n\n{' '.join(self.hashtags)}" if text else " ".join(self.hashtags)
        return text


@dataclass
class Plan:
    week: str
    approved: bool
    items: list[PlanItem] = field(default_factory=list)
    approved_at: str | None = None
    path: Path | None = None


def load_plan(path: Path) -> Plan:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    week = str(raw.get("week", ""))
    items = []
    for entry in raw.get("items") or []:
        at = entry["at"]
        if isinstance(at, str):
            at = datetime.fromisoformat(at)
        items.append(PlanItem(
            id=str(entry["id"]), kind=str(entry["kind"]), at=at, media=str(entry["media"]), week=week,
            caption=str(entry.get("caption") or ""), hashtags=tuple(entry.get("hashtags") or ()),
            library_id=entry.get("library_id"), manual=bool(entry.get("manual", False)),
            note=entry.get("note"),
        ))
    return Plan(week=week, approved=bool(raw.get("approved", False)), items=items,
                approved_at=raw.get("approved_at"), path=path)


def load_plans(plans_dir: Path = PLANS_DIR) -> list[Plan]:
    return [load_plan(p) for p in sorted(plans_dir.glob("*.yaml"))]


def approved_items(plans: Iterable[Plan]) -> list[PlanItem]:
    out = [item for plan in plans if plan.approved for item in plan.items]
    return sorted(out, key=lambda i: (i.at, i.id))


# ---------------------------------------------------------------------------- validation
def check_caption(caption: str, hashtags: Iterable[str]) -> list[str]:
    problems = []
    tags = list(hashtags)
    inline = re.findall(r"(?<!\w)#\w+", caption)
    if inline:
        problems.append(f"Hashtags gehören in 'hashtags', nicht in den Text: {inline}")
    if len(tags) > MAX_HASHTAGS:
        problems.append(f"{len(tags)} Hashtags – erlaubt sind höchstens {MAX_HASHTAGS}")
    for tag in tags:
        if not re.fullmatch(r"#\w+", tag):
            problems.append(f"Ungültiger Hashtag: {tag!r}")
    if len(caption) + sum(len(t) + 1 for t in tags) + 2 > MAX_CAPTION:
        problems.append("Caption zu lang (max. 2200 Zeichen)")
    return problems


def validate_plans(plans: list[Plan], library: list[LibraryItem], config: Config) -> list[str]:
    errors: list[str] = []
    lib_ids = {i.id for i in library}
    all_ids: dict[str, str] = {}
    for plan in plans:
        where = plan.path.name if plan.path else plan.week
        m = WEEK_RE.match(plan.week)
        if not m:
            errors.append(f"{where}: 'week' muss wie 2026-W48 aussehen")
            continue
        if plan.path and plan.path.stem != plan.week:
            errors.append(f"{where}: Dateiname muss {plan.week}.yaml sein")
        monday = week_monday(plan.week)
        for item in plan.items:
            pre = f"{where}/{item.id}"
            if not ID_RE.match(item.id):
                errors.append(f"{pre}: ungültige id (nur a-z, 0-9, -)")
            if item.id in all_ids:
                errors.append(f"{pre}: id auch in {all_ids[item.id]} vergeben")
            all_ids[item.id] = where
            if item.kind not in {"reel", "story"}:
                errors.append(f"{pre}: kind muss reel oder story sein")
            if item.at.tzinfo is None:
                errors.append(f"{pre}: 'at' braucht eine Zeitzone, z. B. +01:00")
            elif not (monday <= item.at.astimezone(config.timezone).date() <= monday + timedelta(days=6)):
                errors.append(f"{pre}: Termin {item.at.isoformat()} liegt nicht in {plan.week}")
            if not MEDIA_RE.match(item.media):
                errors.append(f"{pre}: media-Dateiname ungültig: {item.media}")
            if item.kind == "reel":
                if not item.is_video:
                    errors.append(f"{pre}: ein Reel braucht eine .mp4/.mov-Datei")
                if not item.caption.strip():
                    errors.append(f"{pre}: Reel ohne Caption")
                if item.library_id and item.library_id not in lib_ids:
                    errors.append(f"{pre}: library_id {item.library_id} gibt es nicht")
                if item.manual:
                    errors.append(f"{pre}: manual gibt es nur für Stories")
            for problem in check_caption(item.caption, item.hashtags):
                errors.append(f"{pre}: {problem}")
    return errors


# ---------------------------------------------------------------------------- weeks & rhythm
def week_monday(week: str) -> date:
    m = WEEK_RE.match(week)
    if not m:
        raise ValueError(f"Ungültige Woche: {week}")
    return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)


def week_of(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def rhythm_days(stock: int, config: Config) -> tuple[str, ...]:
    for step in config.rhythm:
        if stock >= step.min_stock:
            return step.days
    return config.rhythm[-1].days


def slot(day: date, hhmm: str, config: Config) -> datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hh, mm), tzinfo=config.timezone)


@dataclass(frozen=True)
class ReelSuggestion:
    day: str
    at: datetime
    item: LibraryItem


def suggest_reels(week: str, library: list[LibraryItem], used_ids: set[str],
                  last_type: str | None, config: Config) -> tuple[list[ReelSuggestion], int, tuple[str, ...]]:
    """Pick the reels for a week following the alternation and throttling rules.

    used_ids: library ids already posted or planned in other weeks.
    last_type: type of the most recent posted/planned reel (episode/explainer), or None.
    Returns (suggestions, stock_before, days).
    """
    queue = {
        t: sorted((i for i in library if i.type == t and i.status == "available" and i.id not in used_ids),
                  key=lambda i: i.sort_key)
        for t in ("episode", "explainer")
    }
    stock = len(queue["episode"]) + len(queue["explainer"])
    days = rhythm_days(stock, config)
    monday = week_monday(week)
    next_type = "explainer" if last_type == "episode" else "episode"
    picks: list[ReelSuggestion] = []
    for day_name in days:
        if not queue["episode"] and not queue["explainer"]:
            break
        chosen_type = next_type if queue[next_type] else _other(next_type)
        item = queue[chosen_type].pop(0)
        day = monday + timedelta(days=WEEKDAYS.index(day_name))
        picks.append(ReelSuggestion(day=day_name, at=slot(day, config.reel_time, config), item=item))
        next_type = _other(chosen_type)
    return picks, stock, days


def _other(t: str) -> str:
    return "explainer" if t == "episode" else "episode"
