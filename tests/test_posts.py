"""Unit 2: posts.build_posts — привʼязка постів до зборів.

TDD; герметично — tmp sqlite + tmp raw-dir; реальна БД не торкається.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from fundrec import posts, store
from fundrec.schema import Actor, Campaign


def _camp_id(url: str) -> str:
    return "camp-" + hashlib.sha256(url.encode()).hexdigest()[:12]


def _raw_path(raw_dir, url: str):
    fid = hashlib.sha256(url.encode()).hexdigest()[:16]
    return raw_dir / f"{fid}.json"


def _write_raw(raw_dir, url: str, raw: dict) -> None:
    raw = dict(raw)
    raw.setdefault("source_url", url)
    _raw_path(raw_dir, url).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    store.init_db(c)
    store.upsert_actor(c, Actor(id="a1", name="A", type="foundation"))
    return c


def _make_campaign(url: str, title: str, *, date_start=None) -> Campaign:
    return Campaign(
        id=_camp_id(url),
        actor_id="a1",
        title=title,
        goal="military",
        type="jar",
        date_start=date_start,
        provenance={"campaign": {"source_url": url}},
    )


def test_link_by_destination(conn, tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    # Campaign with a monobank jar destination.
    camp_url = "https://t.me/ch/100"
    store.upsert_campaign(conn, _make_campaign(camp_url, "Збір на дрон"))
    _write_raw(
        raw_dir,
        camp_url,
        {
            "platform": "telegram",
            "channel": "ch",
            "text": "донат https://send.monobank.ua/jar/ABC",
            "links": ["https://send.monobank.ua/jar/ABC"],
            "date": "2026-01-10T00:00:00+00:00",
            "views": 500,
        },
    )
    # A different post mentioning the SAME jar → should link.
    post_url = "https://t.me/other/55"
    _write_raw(
        raw_dir,
        post_url,
        {
            "platform": "telegram",
            "channel": "other",
            "text": "підтримай https://send.monobank.ua/jar/ABC",
            "links": ["https://send.monobank.ua/jar/ABC"],
            "date": "2026-01-12T00:00:00+00:00",
            "views": 300,
        },
    )

    res = posts.build_posts(conn, raw_dir)
    assert res["posts"] == 2
    assert res["linked"] == 2

    cid = _camp_id(camp_url)
    linked = store.load_posts(conn, campaign_id=cid)
    urls = {p.source_url for p in linked}
    assert post_url in urls
    assert camp_url in urls


def test_fuzzy_link_same_channel_no_dest(conn, tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    camp_url = "https://t.me/foo/1"
    store.upsert_campaign(
        conn, _make_campaign(camp_url, "Збір на автомобіль для підрозділу", date_start="2026-02-01")
    )
    _write_raw(
        raw_dir,
        camp_url,
        {
            "platform": "telegram",
            "channel": "foo",
            "text": "Збір на автомобіль для підрозділу https://send.monobank.ua/jar/XYZ",
            "links": ["https://send.monobank.ua/jar/XYZ"],
            "date": "2026-02-01T00:00:00+00:00",
            "views": 1000,
        },
    )
    # Same channel, similar title, NO destination, within window → fuzzy link.
    post_url = "https://t.me/foo/2"
    _write_raw(
        raw_dir,
        post_url,
        {
            "platform": "telegram",
            "channel": "foo",
            "text": "Нагадуємо: збір на автомобіль для підрозділу триває",
            "date": "2026-02-10T00:00:00+00:00",
            "views": 800,
        },
    )

    posts.build_posts(conn, raw_dir)
    cid = _camp_id(camp_url)
    linked_urls = {p.source_url for p in store.load_posts(conn, campaign_id=cid)}
    assert post_url in linked_urls


def test_unrelated_post_is_free(conn, tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    camp_url = "https://t.me/foo/1"
    store.upsert_campaign(
        conn, _make_campaign(camp_url, "Збір на дрони", date_start="2026-02-01")
    )
    _write_raw(
        raw_dir,
        camp_url,
        {
            "platform": "telegram",
            "channel": "foo",
            "text": "Збір на дрони https://send.monobank.ua/jar/JJJ",
            "links": ["https://send.monobank.ua/jar/JJJ"],
            "date": "2026-02-01T00:00:00+00:00",
            "views": 1000,
        },
    )
    # Unrelated: different channel, no destination, unrelated title.
    post_url = "https://t.me/bar/9"
    _write_raw(
        raw_dir,
        post_url,
        {
            "platform": "telegram",
            "channel": "bar",
            "text": "Концерт класичної музики у Львові цими вихідними",
            "date": "2026-02-05T00:00:00+00:00",
            "views": 50,
        },
    )

    res = posts.build_posts(conn, raw_dir)
    assert res["free"] >= 1
    free_post = [p for p in store.load_posts(conn) if p.source_url == post_url][0]
    assert free_post.campaign_id is None


def test_fuzzy_respects_day_window(conn, tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    camp_url = "https://t.me/foo/1"
    store.upsert_campaign(
        conn, _make_campaign(camp_url, "Збір на автомобіль для підрозділу", date_start="2026-02-01")
    )
    _write_raw(
        raw_dir,
        camp_url,
        {
            "platform": "telegram",
            "channel": "foo",
            "text": "Збір на автомобіль для підрозділу https://send.monobank.ua/jar/QQQ",
            "links": ["https://send.monobank.ua/jar/QQQ"],
            "date": "2026-02-01T00:00:00+00:00",
            "views": 1000,
        },
    )
    # Same channel, similar title, NO dest, but 60 days later → outside window.
    post_url = "https://t.me/foo/2"
    _write_raw(
        raw_dir,
        post_url,
        {
            "platform": "telegram",
            "channel": "foo",
            "text": "Нагадуємо: збір на автомобіль для підрозділу триває",
            "date": "2026-04-15T00:00:00+00:00",
            "views": 800,
        },
    )

    posts.build_posts(conn, raw_dir, day_window=21)
    cid = _camp_id(camp_url)
    linked_urls = {p.source_url for p in store.load_posts(conn, campaign_id=cid)}
    assert post_url not in linked_urls


def test_youtube_engagement_uses_likes(conn, tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    url = "https://youtube.com/watch?v=abc"
    _write_raw(
        raw_dir,
        url,
        {
            "platform": "youtube",
            "channel": "yt",
            "title": "Збір",
            "views": 138,
            "likes": 12,
            "published": "2026-03-01T00:00:00Z",
        },
    )
    posts.build_posts(conn, raw_dir)
    p = store.load_posts(conn)[0]
    assert p.views == 138
    assert p.engagement == 12
    assert p.date == "2026-03-01"
