"""Command line: python -m igpost <command>."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import media
from .config import POSTED_PATH, load_config
from .instagram import InstagramClient, InstagramError, refresh_long_lived_token
from .notify import notify
from .plans import (approved_items, load_library, load_plans, suggest_reels, validate_plans,
                    week_monday, week_of)
from .publisher import DONE_STATES, Publisher
from .statefile import read_json
from .token_store import TokenError, TokenStore

log = logging.getLogger("igpost")


class _PlanDumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_PlanDumper.add_representer(str, _str_presenter)


# ---------------------------------------------------------------------------- helpers
def _token(refresh: bool) -> str:
    store = TokenStore.from_env()
    record = store.load()
    if refresh and store.needs_refresh(record):
        try:
            record = store.apply_refresh(record, refresh_long_lived_token(record.token))
            log.info("Token erneuert, gültig bis %s", record.expires_at)
        except InstagramError as exc:
            log.warning("Token-Erneuerung fehlgeschlagen: %s", exc)
    return record.token


def _client_factory(config):
    def factory():
        client = InstagramClient(_token(refresh=True), config.graph_api_version)
        me = client.me()
        ig_id = str(me.get("user_id") or me.get("id"))
        log.info("Angemeldet als @%s (%s)", me.get("username"), me.get("account_type"))
        return client, ig_id
    return factory


# ---------------------------------------------------------------------------- commands
def cmd_post(args) -> int:
    config = load_config()
    plans = load_plans()
    errors = validate_plans(plans, load_library(), config)
    if errors:
        notify("Wochenplan fehlerhaft", "Der Plan hat Fehler, es wird nichts gepostet:\n\n- " + "\n- ".join(errors))
        log.error("Plan-Fehler:\n%s", "\n".join(errors))
        return 1
    result = Publisher(config, _client_factory(config)).run(approved_items(plans))
    log.info("Gepostet: %s | wartet: %s | Erinnerungen: %s | verpasst: %s | Fehler: %s",
             result.posted, result.waiting, result.reminded, result.missed, result.errors)
    return 0 if result.ok else 1


def cmd_refresh_token(args) -> int:
    store = TokenStore.from_env()
    record = store.load()
    if store.needs_refresh(record) or args.force:
        try:
            record = store.apply_refresh(record, refresh_long_lived_token(record.token))
            log.info("Token erneuert.")
        except InstagramError as exc:
            notify("Instagram-Token: Erneuerung fehlgeschlagen",
                   f"Fehler: `{exc}`\n\nAblauf laut Speicher: {record.expires_at or 'unbekannt'}. "
                   "Falls das so bleibt: in Meta for Developers neuen Token erzeugen und das Secret "
                   "IG_ACCESS_TOKEN ersetzen.")
            return 1
    me = InstagramClient(record.token, load_config().graph_api_version).me()
    log.info("Token ok für @%s, gültig bis %s", me.get("username"), record.expires_at or "unbekannt")
    return 0


def cmd_check(args) -> int:
    config = load_config()
    library = load_library()
    plans = load_plans()
    errors = validate_plans(plans, library, config)
    for e in errors:
        print(f"FEHLER: {e}")
    print(f"{len(library)} Bibliothekseinträge, {len(plans)} Wochenpläne – "
          f"{'OK' if not errors else f'{len(errors)} Fehler'}")
    return 1 if errors else 0


def _used_library_ids(plans, posted, exclude_week: str | None = None) -> tuple[set[str], str | None]:
    used = {e["library_id"] for e in posted.values() if e.get("library_id") and e.get("status") == "posted"}
    last_type, last_at = None, None
    library = {i.id: i for i in load_library()}
    for plan in plans:
        if plan.week == exclude_week:
            continue
        for item in plan.items:
            if item.kind == "reel" and item.library_id:
                status = (posted.get(item.id) or {}).get("status")
                if status in {"missed", "failed"}:
                    continue
                used.add(item.library_id)
                if (last_at is None or item.at > last_at) and item.library_id in library:
                    last_at, last_type = item.at, library[item.library_id].type
    return used, last_type


def cmd_suggest(args) -> int:
    config = load_config()
    library = load_library()
    plans = load_plans()
    posted = read_json(POSTED_PATH, {})
    week = args.week or week_of(date.today())
    week_monday(week)  # validates format
    used, last_type = _used_library_ids(plans, posted, exclude_week=week)
    picks, stock, days = suggest_reels(week, library, used, last_type, config)
    by_id = {i.id: i for i in library}
    plan = {
        "week": week,
        "approved": False,
        "approved_at": None,
        "items": [
            {
                "id": f"{week.lower()}-{p.day}-reel",
                "kind": "reel",
                "at": p.at.isoformat(),
                "library_id": p.item.id,
                "media": f"{p.item.id}.mp4",
                "caption": by_id[p.item.id].caption + "\n",
                "hashtags": list(by_id[p.item.id].hashtags),
            }
            for p in picks
        ],
    }
    print(f"# Vorrat vor dieser Woche: {stock} Reels -> Posting-Tage: {', '.join(days)}")
    print(f"# Letzter Reel-Typ davor: {last_type or '–'}")
    print(yaml.dump(plan, Dumper=_PlanDumper, sort_keys=False, allow_unicode=True, width=200))
    return 0


def cmd_status(args) -> int:
    config = load_config()
    library = load_library()
    plans = load_plans()
    posted = read_json(POSTED_PATH, {})
    used, last_type = _used_library_ids(plans, posted)
    available = [i for i in library if i.status == "available" and i.id not in used]
    print(f"Unverplante Reels: {len(available)} "
          f"({sum(i.type == 'episode' for i in available)} Folgen, "
          f"{sum(i.type == 'explainer' for i in available)} Erklärvideos)")
    now = datetime.now(timezone.utc)
    upcoming = [i for i in approved_items(plans)
                if (posted.get(i.id) or {}).get("status") not in DONE_STATES and i.at >= now]
    print(f"Freigegeben und noch offen: {len(upcoming)}")
    for item in upcoming[:15]:
        print(f"  {item.at.astimezone(config.timezone):%a %d.%m. %H:%M}  {item.kind:<5}  {item.id}")
    counts: dict[str, int] = {}
    for entry in posted.values():
        counts[entry.get("status", "?")] = counts.get(entry.get("status", "?"), 0) + 1
    print(f"Protokoll: {counts or 'noch leer'}")
    return 0


def cmd_prepare(args) -> int:
    config = load_config()
    src, dst = Path(args.src), Path(args.dst)
    if args.kind == "reel":
        info = media.prepare_reel(src, dst, max_bytes=config.max_media_bytes)
        print(f"{dst}: {info.width}x{info.height}, {info.duration:.1f} s, {info.size / 1e6:.1f} MB")
    else:
        media.prepare_story(src, dst, max_bytes=config.max_media_bytes)
        print(f"Story vorbereitet: {dst.with_suffix('.jpg' if dst.suffix.lower() in {'.jpg', '.jpeg'} else '.mp4')}")
    return 0


def cmd_build_site(args) -> int:
    from .site import SiteError, build_site
    config = load_config()
    try:
        build_site(Path(args.out), load_plans(), read_json(POSTED_PATH, {}), config)
    except SiteError as exc:
        notify("Medien-Seite konnte nicht gebaut werden", f"`{exc}`")
        log.error("%s", exc)
        return 1
    return 0


def cmd_whoami(args) -> int:
    config = load_config()
    client = InstagramClient(_token(refresh=False), config.graph_api_version)
    me = client.me()
    print(f"@{me.get('username')} – Kontotyp: {me.get('account_type')} – ID: {me.get('user_id')}")
    quota = client.publishing_quota(str(me.get("user_id")))
    print(f"Posts in den letzten 24 h: {quota.get('quota_usage')} / {(quota.get('config') or {}).get('quota_total')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="igpost", description="Automatisches Posten für @techeroesuniverse")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("post", help="fällige Reels/Stories posten").set_defaults(fn=cmd_post)
    p = sub.add_parser("refresh-token", help="Instagram-Token erneuern")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_refresh_token)
    sub.add_parser("check", help="Bibliothek und Pläne prüfen").set_defaults(fn=cmd_check)
    p = sub.add_parser("suggest", help="Reels für eine Woche vorschlagen")
    p.add_argument("week", nargs="?", help="z. B. 2026-W49")
    p.set_defaults(fn=cmd_suggest)
    sub.add_parser("status", help="Überblick").set_defaults(fn=cmd_status)
    p = sub.add_parser("prepare", help="Medium für Instagram umwandeln")
    p.add_argument("kind", choices=["reel", "story"])
    p.add_argument("src")
    p.add_argument("dst")
    p.set_defaults(fn=cmd_prepare)
    p = sub.add_parser("build-site", help="Pages-Seite mit Medien bauen")
    p.add_argument("out")
    p.set_defaults(fn=cmd_build_site)
    sub.add_parser("whoami", help="Token und Konto prüfen").set_defaults(fn=cmd_whoami)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except TokenError as exc:
        notify("Instagram-Token fehlt oder ist unlesbar", f"`{exc}`")
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
