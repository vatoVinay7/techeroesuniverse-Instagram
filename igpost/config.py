"""Load config.yaml and resolve repository paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
LIBRARY_PATH = ROOT / "content" / "library.yaml"
PLANS_DIR = ROOT / "plans"
STATE_DIR = ROOT / "state"
POSTED_PATH = STATE_DIR / "posted.json"
PENDING_PATH = STATE_DIR / "pending.json"
TOKEN_PATH = STATE_DIR / "token.enc.json"

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass(frozen=True)
class RhythmStep:
    min_stock: int
    days: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    account: str
    timezone: ZoneInfo
    graph_api_version: str
    pages_base_url: str
    github_repo: str
    reel_time: str
    story_content_time: str
    story_announce_time: str
    max_delay_minutes: int
    rhythm: tuple[RhythmStep, ...]
    max_posts_per_run: int
    max_media_bytes: int
    root: Path = field(default=ROOT)

    def media_url(self, week: str, filename: str) -> str:
        return f"{self.pages_base_url.rstrip('/')}/media/{week}/{filename}"


def load_config(path: Path = CONFIG_PATH) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    posting = raw["posting"]
    rhythm = tuple(
        RhythmStep(min_stock=int(step["min_stock"]), days=tuple(step["days"]))
        for step in posting["rhythm"]
    )
    for step in rhythm:
        bad = [d for d in step.days if d not in WEEKDAYS]
        if bad:
            raise ValueError(f"config.yaml: unbekannte Wochentage {bad}")
    rhythm = tuple(sorted(rhythm, key=lambda s: s.min_stock, reverse=True))
    if not rhythm or rhythm[-1].min_stock != 0:
        raise ValueError("config.yaml: rhythm braucht eine Stufe mit min_stock: 0")
    limits = raw.get("limits", {})
    return Config(
        account=raw["account"],
        timezone=ZoneInfo(raw["timezone"]),
        graph_api_version=raw["graph_api_version"],
        pages_base_url=raw["pages_base_url"],
        github_repo=raw["github_repo"],
        reel_time=posting["reel_time"],
        story_content_time=posting["story_content_time"],
        story_announce_time=posting["story_announce_time"],
        max_delay_minutes=int(posting["max_delay_minutes"]),
        rhythm=rhythm,
        max_posts_per_run=int(limits.get("max_posts_per_run", 6)),
        max_media_bytes=int(limits.get("max_media_bytes", 99_000_000)),
    )
