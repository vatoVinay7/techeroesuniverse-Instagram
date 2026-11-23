from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from igpost import publisher as pub_mod
from igpost import token_store
from igpost.config import load_config
from igpost.instagram import ContainerStatus, InstagramError
from igpost.plans import (LibraryItem, Plan, PlanItem, check_caption, load_library, rhythm_days,
                          suggest_reels, validate_plans)
from igpost.publisher import Publisher

CONFIG = load_config()
TZ = CONFIG.timezone


def lib(id_, type_, n, status="available"):
    return LibraryItem(id=id_, type=type_, topic=id_, status=status, caption="x", hashtags=(),
                       season=1 if type_ == "episode" else None, episode=n if type_ == "episode" else None,
                       priority=n if type_ == "explainer" else None)


# ---------------------------------------------------------------------------- library & rules
def test_real_library_is_valid():
    items = load_library()
    assert sum(i.type == "episode" for i in items) == 10
    assert all(len(i.hashtags) <= 5 for i in items)
    assert {i.hashtags[0] for i in items if i.type == "episode"} == {"#TinyDragonCodeQuest"}
    assert {i.hashtags[0] for i in items if i.type == "explainer"} == {"#TecheroesExplains"}


@pytest.mark.parametrize("stock,days", [(22, 5), (10, 5), (9, 3), (5, 3), (4, 2), (0, 2)])
def test_rhythm_thresholds(stock, days):
    assert len(rhythm_days(stock, CONFIG)) == days


def test_suggest_alternates_and_falls_back():
    library = [lib(f"e{i}", "episode", i) for i in range(1, 4)] + [lib("x1", "explainer", 1)]
    picks, stock, days = suggest_reels("2026-W49", library, set(), None, CONFIG)
    assert stock == 4 and days == ("tue", "fri")
    assert [p.item.id for p in picks] == ["e1", "x1"]
    # next week: explainers exhausted -> only episodes, still in order
    picks, _, _ = suggest_reels("2026-W50", library, {"e1", "x1"}, "explainer", CONFIG)
    assert [p.item.id for p in picks] == ["e2", "e3"]
    assert picks[0].at == datetime(2026, 12, 8, 18, 0, tzinfo=TZ)


def test_suggest_skips_hold_items():
    library = [lib("e1", "episode", 1), lib("h", "explainer", 1, status="hold")]
    picks, stock, _ = suggest_reels("2026-W49", library, set(), None, CONFIG)
    assert stock == 1 and [p.item.id for p in picks] == ["e1"]


def test_caption_rules():
    assert check_caption("Hello", ["#A", "#B"]) == []
    assert check_caption("Hello #inline", [])
    assert check_caption("Hi", [f"#t{i}" for i in range(6)])


def test_validate_catches_wrong_week_and_missing_tz():
    item = PlanItem(id="w49-mon-reel", kind="reel", at=datetime(2026, 12, 20, 18, 0), media="a.mp4",
                    week="2026-W49", caption="c")
    errors = validate_plans([Plan(week="2026-W49", approved=True, items=[item])], [], CONFIG)
    assert any("Zeitzone" in e for e in errors)
    item.at = datetime(2026, 12, 20, 18, 0, tzinfo=TZ)
    errors = validate_plans([Plan(week="2026-W49", approved=True, items=[item])], [], CONFIG)
    assert any("liegt nicht in" in e for e in errors)


# ---------------------------------------------------------------------------- token store
def test_token_roundtrip_and_reseed(tmp_path: Path):
    path = tmp_path / "token.json"
    key = "k" * 32
    store = token_store.TokenStore(seed="seed-1", passphrase=key, path=path)
    rec = store.load()
    assert rec.token == "seed-1" and path.exists()
    assert "seed-1" not in path.read_text()

    refreshed = store.apply_refresh(rec, {"access_token": "fresh", "expires_in": 5_184_000})
    assert token_store.TokenStore(seed="seed-1", passphrase=key, path=path).load().token == "fresh"
    assert refreshed.expires_at

    # Vinay sets a new secret -> new seed wins
    assert token_store.TokenStore(seed="seed-2", passphrase=key, path=path).load().token == "seed-2"

    with pytest.raises(token_store.TokenError):
        token_store.TokenStore(seed=None, passphrase="w" * 32, path=path).load()


def test_needs_refresh():
    store = token_store.TokenStore(seed="s", passphrase="k" * 32, path=Path("/nonexistent"))
    now = datetime(2026, 12, 1, tzinfo=timezone.utc)
    young = token_store.TokenRecord("t", "h", (now - timedelta(hours=2)).isoformat(), None)
    assert not store.needs_refresh(young, now)
    unknown = token_store.TokenRecord("t", "h", (now - timedelta(days=2)).isoformat(), None)
    assert store.needs_refresh(unknown, now)
    fresh = token_store.TokenRecord("t", "h", (now - timedelta(days=2)).isoformat(),
                                    (now + timedelta(days=50)).isoformat())
    assert not store.needs_refresh(fresh, now)


# ---------------------------------------------------------------------------- publisher
class FakeClient:
    def __init__(self, statuses=("FINISHED",), fail_create=None):
        self.statuses = list(statuses)
        self.fail_create = fail_create
        self.created, self.published = [], []

    def create_container(self, ig_id, *, kind, media_url, is_video, caption=None, cover_url=None):
        if self.fail_create:
            raise self.fail_create
        self.created.append((kind, media_url, caption))
        self.covers = getattr(self, "covers", []) + [cover_url]
        return f"c{len(self.created)}"

    def container_status(self, cid):
        return ContainerStatus(self.statuses[0], None)

    def wait_until_ready(self, cid, *, timeout_s, interval_s=20):
        return ContainerStatus(self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0], None)

    def publish(self, ig_id, cid):
        self.published.append(cid)
        return f"m-{cid}"

    def permalink(self, media_id):
        return f"https://instagram.com/p/{media_id}"


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(pub_mod, "POSTED_PATH", tmp_path / "posted.json")
    monkeypatch.setattr(pub_mod, "PENDING_PATH", tmp_path / "pending.json")
    return tmp_path


def make_publisher(client, notes):
    return Publisher(CONFIG, lambda: (client, "ig1"), media_check=lambda *a: None,
                     notifier=lambda t, b: notes.append(t))


def reel(at, id_="w49-mon-reel", **kw):
    return PlanItem(id=id_, kind="reel", at=at, media="s1e1-index.mp4", week="2026-W49",
                    caption="Hello", hashtags=("#TinyDragonCodeQuest",), library_id="s1e1-index", **kw)


def test_posts_due_reel_once(state):
    notes, client = [], FakeClient()
    now = datetime(2026, 11, 30, 17, 5, tzinfo=timezone.utc)  # 18:05 Berlin
    item = reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ))
    result = make_publisher(client, notes).run([item], now)
    assert result.posted == ["w49-mon-reel"] and result.ok
    assert client.created[0][1].endswith("/media/2026-W49/s1e1-index.mp4")
    assert client.created[0][2] == "Hello\n\n#TinyDragonCodeQuest"
    # second run: nothing happens
    result = make_publisher(client, notes).run([item], now + timedelta(minutes=15))
    assert not result.posted and len(client.published) == 1


def test_future_item_not_posted(state):
    client = FakeClient()
    item = reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ))
    make_publisher(client, []).run([item], datetime(2026, 11, 30, 16, 0, tzinfo=timezone.utc))
    assert client.created == []


def test_waiting_container_is_resumed_not_recreated(state):
    client = FakeClient(statuses=["IN_PROGRESS"])
    item = reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ))
    now = datetime(2026, 11, 30, 17, 1, tzinfo=timezone.utc)
    assert make_publisher(client, []).run([item], now).waiting == ["w49-mon-reel"]
    client.statuses = ["FINISHED"]
    result = make_publisher(client, []).run([item], now + timedelta(minutes=15))
    assert result.posted == ["w49-mon-reel"]
    assert len(client.created) == 1 and client.published == ["c1"]


def test_missed_after_max_delay(state):
    notes, client = [], FakeClient()
    item = reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ))
    result = make_publisher(client, notes).run([item], datetime(2026, 12, 1, 9, 0, tzinfo=timezone.utc))
    assert result.missed == ["w49-mon-reel"] and client.created == [] and notes


def test_manual_story_sends_reminder(state):
    notes, client = [], FakeClient()
    story = PlanItem(id="w49-tue-story", kind="story", at=datetime(2026, 12, 1, 12, 0, tzinfo=TZ),
                     media="poll.jpg", week="2026-W49", manual=True, note="Umfrage: Lieblingsfigur")
    result = make_publisher(client, notes).run([story], datetime(2026, 12, 1, 11, 5, tzinfo=timezone.utc))
    assert result.reminded == ["w49-tue-story"] and client.created == []
    assert any("selbst posten" in n for n in notes)


def test_failure_counts_attempts_then_gives_up(state):
    notes = []
    client = FakeClient(fail_create=InstagramError("boom", code=100, status=400))
    item = reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ))
    now = datetime(2026, 11, 30, 17, 1, tzinfo=timezone.utc)
    for i in range(3):
        result = make_publisher(client, notes).run([item], now + timedelta(minutes=15 * i))
        assert not result.ok
    assert any(t.startswith("Fehlgeschlagen") for t in notes)
    result = make_publisher(client, notes).run([item], now + timedelta(minutes=60))
    assert result.ok and not result.errors  # finished as failed, no more retries


def test_auth_error_stops_run(state):
    notes = []
    client = FakeClient(fail_create=InstagramError("expired", code=190, status=400))
    items = [reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ)),
             reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ), id_="w49-mon-reel-2")]
    result = make_publisher(client, notes).run(items, datetime(2026, 11, 30, 17, 1, tzinfo=timezone.utc))
    assert len(result.errors) == 1 and "Instagram-Zugang ungültig" in notes


def test_host_detection():
    from igpost.instagram import FACEBOOK_HOST, GRAPH_HOST, host_for_token
    assert host_for_token("IGAAxyz") == GRAPH_HOST
    assert host_for_token("EAAAxyz") == FACEBOOK_HOST


# ---------------------------------------------------------------------------- feed image posts
def test_feed_post_gets_caption_and_image(state):
    client = FakeClient()
    item = PlanItem(id="w48-mon-intro", kind="post", at=datetime(2026, 11, 23, 19, 45, tzinfo=TZ),
                    media="intro.jpg", week="2026-W48", caption="Meet Tiny", hashtags=("#TinyDragonCodeQuest",))
    result = make_publisher(client, []).run([item], datetime(2026, 11, 23, 18, 50, tzinfo=timezone.utc))
    assert result.posted == ["w48-mon-intro"]
    kind, url, caption = client.created[0]
    assert kind == "post" and url.endswith("/media/2026-W48/intro.jpg")
    assert caption == "Meet Tiny\n\n#TinyDragonCodeQuest"


def test_story_never_sends_caption(state):
    client = FakeClient()
    item = PlanItem(id="w48-mon-story", kind="story", at=datetime(2026, 11, 23, 20, 0, tzinfo=TZ),
                    media="s.jpg", week="2026-W48")
    make_publisher(client, []).run([item], datetime(2026, 11, 23, 19, 5, tzinfo=timezone.utc))
    assert client.created[0][2] is None


def test_validate_post_rules():
    at = datetime(2026, 11, 23, 19, 45, tzinfo=TZ)
    bad = [
        PlanItem(id="w48-video-post", kind="post", at=at, media="a.mp4", week="2026-W48", caption="x"),
        PlanItem(id="w48-no-caption", kind="post", at=at, media="a.jpg", week="2026-W48"),
        PlanItem(id="w48-story-caption", kind="story", at=at, media="b.jpg", week="2026-W48", caption="x"),
        PlanItem(id="w48-manual-post", kind="post", at=at, media="c.jpg", week="2026-W48", caption="x", manual=True),
    ]
    errors = validate_plans([Plan(week="2026-W48", approved=False, items=bad)], load_library(), CONFIG)
    text = "\n".join(errors)
    assert ".jpg-Datei" in text and "ohne Caption" in text and "keine Caption" in text and "manual" in text
    good = PlanItem(id="w48-intro", kind="post", at=at, media="c.jpg", week="2026-W48", caption="x")
    assert validate_plans([Plan(week="2026-W48", approved=False, items=[good])], load_library(), CONFIG) == []


def test_instagram_client_post_params():
    from igpost.instagram import InstagramClient

    class S:
        def request(self, method, url, params=None, data=None, headers=None, timeout=None):
            self.data = data
            class R:
                ok = True
                status_code = 200
                headers = {}
                def json(self_inner):
                    return {"id": "c9"}
            return R()

    sess = S()
    client = InstagramClient("IGtoken", "v25.0", session=sess)
    assert client.create_container("ig1", kind="post", media_url="https://x/a.jpg", is_video=False,
                                   caption="Hi") == "c9"
    assert sess.data == {"image_url": "https://x/a.jpg", "caption": "Hi"}
    with pytest.raises(ValueError):
        client.create_container("ig1", kind="post", media_url="https://x/a.mp4", is_video=True)


def test_validate_rejects_same_reel_twice():
    a = reel(datetime(2026, 11, 23, 20, 15, tzinfo=TZ), id_="w48-mon-reel")
    a.week = "2026-W48"
    b = reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ), id_="w49-mon-reel")
    plans = [Plan(week="2026-W48", approved=True, items=[a]), Plan(week="2026-W49", approved=False, items=[b])]
    errors = validate_plans(plans, load_library(), CONFIG)
    assert any("schon in" in e for e in errors)


# ---------------------------------------------------------------------------- reel covers (poster)
def test_reel_cover_is_checked_and_sent(state):
    client, checked = FakeClient(), []
    pub = Publisher(CONFIG, lambda: (client, "ig1"), media_check=lambda url, item, mb: checked.append((url, item.is_video)),
                    notifier=lambda t, b: None)
    item = reel(datetime(2026, 11, 30, 18, 0, tzinfo=TZ), cover="s1e1-index-cover.jpg")
    assert pub.run([item], datetime(2026, 11, 30, 17, 5, tzinfo=timezone.utc)).posted
    assert client.covers[0].endswith("/media/2026-W49/s1e1-index-cover.jpg")
    assert checked[1] == (client.covers[0], False)   # Titelbild als Bild geprüft


def test_cover_validation_and_site_files():
    from igpost.site import weeks_needing_media
    at = datetime(2026, 11, 30, 18, 0, tzinfo=TZ)
    ok = reel(at, cover="c.jpg")
    bad_story = PlanItem(id="w49-s", kind="story", at=at, media="s.jpg", week="2026-W49", cover="c.jpg")
    bad_ext = reel(at, id_="w49-x", cover="c.png")
    bad_ext.library_id = None
    errors = validate_plans([Plan(week="2026-W49", approved=False, items=[ok, bad_story, bad_ext])], load_library(), CONFIG)
    assert sum("cover" in e for e in errors) == 2
    needed = weeks_needing_media([Plan(week="2026-W49", approved=True, items=[ok])], {}, at)
    assert needed == {"2026-W49": {"s1e1-index.mp4", "c.jpg"}}


def test_instagram_client_reel_cover_param():
    from igpost.instagram import InstagramClient

    class S:
        def request(self, method, url, params=None, data=None, headers=None, timeout=None):
            self.data = data
            class R:
                ok = True
                status_code = 200
                headers = {}
                def json(self_inner):
                    return {"id": "c1"}
            return R()

    sess = S()
    InstagramClient("IGt", "v25.0", session=sess).create_container(
        "ig1", kind="reel", media_url="https://x/v.mp4", is_video=True, caption="c", cover_url="https://x/c.jpg")
    assert sess.data["cover_url"] == "https://x/c.jpg" and sess.data["media_type"] == "REELS"
