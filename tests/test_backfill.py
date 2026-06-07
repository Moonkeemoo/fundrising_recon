"""Тести бекфілу сигналів: hermetic (tmp sqlite + tmp raw dir)."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from fundrec import store
from fundrec.schema import Campaign
from fundrec.backfill import backfill_campaign, backfill_database


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_campaign(url: str, **kwargs) -> Campaign:
    cid = "camp-" + hashlib.sha256(url.encode()).hexdigest()[:12]
    defaults = dict(
        id=cid, actor_id="act-1", title="Test", goal="military",
        type="organic_social",
        reach=None, engagement=None, date_start=None, goal_reached=None,
        provenance={},
    )
    defaults.update(kwargs)
    return Campaign(**defaults)


def _raw_file(raw_dir: Path, url: str, payload: dict) -> Path:
    file_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    p = raw_dir / f"{file_id}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _seed_db(conn, campaigns: list[Campaign]) -> None:
    store.init_db(conn)
    from fundrec.schema import Actor
    store.upsert_actor(conn, Actor(id="act-1", name="Actor", type="foundation"))
    for c in campaigns:
        store.upsert_campaign(conn, c)


# ── backfill_campaign unit tests ──────────────────────────────────────────────

def test_backfill_campaign_telegram_views_forwards():
    """Telegram: reach=views, engagement=forwards; провіненс tier-3 backfill."""
    c = _make_campaign("https://t.me/ch/1")
    raw = {"platform": "telegram", "source_url": "https://t.me/ch/1",
           "views": 5000, "forwards": 120, "date": "2024-03-15"}
    changed = backfill_campaign(c, raw)
    assert changed is True
    assert c.reach == 5000
    assert c.engagement == 120
    assert c.date_start == "2024-03-15"
    assert c.goal_reached is None  # немає closing-тексту
    # провіненс
    assert c.provenance["reach"]["tier"] == 3
    assert c.provenance["engagement"]["note"] == "platform signal backfill"


def test_backfill_campaign_telegram_no_forwards_uses_views():
    """Telegram без forwards: engagement=views."""
    c = _make_campaign("https://t.me/ch/2")
    raw = {"platform": "telegram", "source_url": "https://t.me/ch/2",
           "views": 3000, "date": "2024-06-01"}
    changed = backfill_campaign(c, raw)
    assert changed is True
    assert c.engagement == 3000


def test_backfill_campaign_youtube():
    """YouTube: reach=views, engagement=likes."""
    c = _make_campaign("https://youtube.com/watch?v=abc")
    raw = {"platform": "youtube", "source_url": "https://youtube.com/watch?v=abc",
           "views": 80000, "likes": 2400, "published": "2023-11-10T12:00:00Z"}
    changed = backfill_campaign(c, raw)
    assert changed is True
    assert c.reach == 80000
    assert c.engagement == 2400
    assert c.date_start == "2023-11-10"


def test_backfill_campaign_youtube_no_likes_uses_views():
    """YouTube без likes: engagement=views."""
    c = _make_campaign("https://youtube.com/watch?v=def")
    raw = {"platform": "youtube", "source_url": "https://youtube.com/watch?v=def",
           "views": 12000, "published": "2024-01-05"}
    backfill_campaign(c, raw)
    assert c.engagement == 12000


def test_backfill_campaign_goal_reached_from_text():
    """goal_reached=True коли текст містить closing-патерн."""
    c = _make_campaign("https://t.me/ch/3")
    raw = {"platform": "telegram", "source_url": "https://t.me/ch/3",
           "views": 100, "text": "Дякуємо! Ціль досягнута! Зібрали повністю."}
    changed = backfill_campaign(c, raw)
    assert changed is True
    assert c.goal_reached is True


def test_backfill_campaign_skips_existing_values():
    """Якщо reach/engagement вже встановлені — не перезаписувати."""
    c = _make_campaign("https://t.me/ch/4", reach=999, engagement=50)
    raw = {"platform": "telegram", "source_url": "https://t.me/ch/4",
           "views": 1000, "forwards": 200}
    changed = backfill_campaign(c, raw)
    # дати і goal_reached — None, але signals не перезаписані
    assert c.reach == 999
    assert c.engagement == 50
    # changed може бути False якщо більше нічого не змінилось
    assert changed is False


def test_backfill_campaign_date_from_telegram_date_field():
    """date_start береться з raw['date'] для Telegram."""
    c = _make_campaign("https://t.me/ch/5")
    raw = {"platform": "telegram", "source_url": "https://t.me/ch/5",
           "date": "2024-08-20T10:30:00+03:00"}
    backfill_campaign(c, raw)
    assert c.date_start == "2024-08-20"


def test_backfill_campaign_date_from_published_field():
    """date_start береться з raw['published'] якщо нема date."""
    c = _make_campaign("https://youtube.com/watch?v=xyz")
    raw = {"platform": "youtube", "source_url": "https://youtube.com/watch?v=xyz",
           "views": 100, "published": "2023-05-01"}
    backfill_campaign(c, raw)
    assert c.date_start == "2023-05-01"


def test_backfill_campaign_no_change_when_nothing_to_fill():
    """Кампанія вже заповнена — returns False."""
    c = _make_campaign("https://t.me/ch/6",
                       reach=100, engagement=10,
                       date_start="2024-01-01", goal_reached=True)
    raw = {"platform": "telegram", "source_url": "https://t.me/ch/6",
           "views": 999, "forwards": 99, "date": "2025-01-01",
           "text": "Ціль досягнута"}
    changed = backfill_campaign(c, raw)
    assert changed is False
    assert c.reach == 100  # не перезаписане


def test_backfill_campaign_unknown_platform_no_signals():
    """Невідома платформа — signals не встановлюємо, honest null."""
    c = _make_campaign("https://example.com/unknown")
    raw = {"platform": "web", "source_url": "https://example.com/unknown",
           "views": 500}
    backfill_campaign(c, raw)
    assert c.reach is None
    assert c.engagement is None


# ── backfill_database integration tests ──────────────────────────────────────

def test_backfill_database_fills_and_counts(tmp_path):
    """Кампанії з raw-файлами оновлюються; кампанія без raw — не чіпається."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url_tg = "https://t.me/test/1"
    url_yt = "https://youtube.com/watch?v=yt1"
    url_no = "https://example.com/no-raw"

    camps = [
        _make_campaign(url_tg),
        _make_campaign(url_yt),
        _make_campaign(url_no),
    ]
    _seed_db(conn, camps)

    _raw_file(raw_dir, url_tg, {
        "platform": "telegram", "source_url": url_tg,
        "views": 4000, "forwards": 80, "date": "2024-05-10"
    })
    _raw_file(raw_dir, url_yt, {
        "platform": "youtube", "source_url": url_yt,
        "views": 60000, "likes": 1800, "published": "2024-07-22"
    })

    result = backfill_database(conn, raw_dir)
    assert result["scanned"] == 3
    assert result["raw_found"] == 2
    assert result["updated"] == 2

    # перевіряємо в БД
    id_tg = _make_campaign(url_tg).id
    id_yt = _make_campaign(url_yt).id
    id_no = _make_campaign(url_no).id
    updated_camps = {c.id: c for c in store.load_campaigns(conn)}
    tg = updated_camps[id_tg]
    assert tg.reach == 4000
    assert tg.engagement == 80
    assert tg.date_start == "2024-05-10"
    assert tg.provenance["reach"]["note"] == "platform signal backfill"

    yt = updated_camps[id_yt]
    assert yt.reach == 60000
    assert yt.engagement == 1800
    assert yt.date_start == "2024-07-22"

    no = updated_camps[id_no]
    assert no.reach is None
    assert no.engagement is None


def test_backfill_database_goal_reached_from_text(tmp_path):
    """goal_reached встановлюється з closing-тексту в raw-файлі."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/done"
    camps = [_make_campaign(url)]
    _seed_db(conn, camps)

    _raw_file(raw_dir, url, {
        "platform": "telegram", "source_url": url,
        "views": 200,
        "text": "Збір завершено! Зібрали повністю. Дякуємо всім!"
    })

    result = backfill_database(conn, raw_dir)
    assert result["updated"] == 1

    updated = store.load_campaigns(conn)[0]
    assert updated.goal_reached is True


def test_backfill_database_no_raw_dir(tmp_path):
    """Порожній raw_dir → нічого не оновлюється, підрахунки коректні."""
    raw_dir = tmp_path / "empty_raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    camps = [_make_campaign("https://t.me/x/1"), _make_campaign("https://t.me/x/2")]
    _seed_db(conn, camps)

    result = backfill_database(conn, raw_dir)
    assert result["scanned"] == 2
    assert result["raw_found"] == 0
    assert result["updated"] == 0


def test_backfill_database_idempotent(tmp_path):
    """Повторний бекфіл не змінює вже заповнені поля."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/idem/1"
    camps = [_make_campaign(url)]
    _seed_db(conn, camps)

    _raw_file(raw_dir, url, {
        "platform": "telegram", "source_url": url,
        "views": 300, "forwards": 30, "date": "2024-09-01"
    })

    r1 = backfill_database(conn, raw_dir)
    assert r1["updated"] == 1

    # другий запуск — нічого не змінено (вже заповнено)
    r2 = backfill_database(conn, raw_dir)
    assert r2["updated"] == 0
