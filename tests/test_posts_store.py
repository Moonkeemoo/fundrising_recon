"""Unit 1: таблиця posts + store helpers (upsert_post/load_posts/clear_posts).

TDD; герметично — лише in-memory SQLite, реальна БД не торкається.
"""
from __future__ import annotations

import sqlite3

import pytest

from fundrec import store
from fundrec.schema import Post


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    store.init_db(c)
    return c


def _post(pid: str, campaign_id=None, views=None, engagement=None, date=None) -> Post:
    return Post(
        id=pid,
        campaign_id=campaign_id,
        source_url=f"https://t.me/ch/{pid}",
        channel="ch",
        platform="telegram",
        date=date,
        views=views,
        engagement=engagement,
        text_snippet="text",
    )


def test_posts_table_exists(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='posts'"
    ).fetchall()
    assert rows


def test_upsert_load_roundtrip(conn):
    p = _post("p1", campaign_id="camp-1", views=100, engagement=5, date="2026-01-01")
    store.upsert_post(conn, p)
    loaded = store.load_posts(conn)
    assert len(loaded) == 1
    assert loaded[0] == p


def test_upsert_is_idempotent_update(conn):
    store.upsert_post(conn, _post("p1", views=10))
    store.upsert_post(conn, _post("p1", views=99))
    loaded = store.load_posts(conn)
    assert len(loaded) == 1
    assert loaded[0].views == 99


def test_load_filter_by_campaign(conn):
    store.upsert_post(conn, _post("p1", campaign_id="camp-A"))
    store.upsert_post(conn, _post("p2", campaign_id="camp-B"))
    store.upsert_post(conn, _post("p3", campaign_id=None))
    only_a = store.load_posts(conn, campaign_id="camp-A")
    assert [p.id for p in only_a] == ["p1"]


def test_load_sorted_by_date(conn):
    store.upsert_post(conn, _post("p1", date="2026-03-01"))
    store.upsert_post(conn, _post("p2", date="2026-01-01"))
    store.upsert_post(conn, _post("p3", date=None))
    ids = [p.id for p in store.load_posts(conn)]
    assert ids == ["p2", "p1", "p3"]  # earliest first, None last


def test_clear_posts(conn):
    store.upsert_post(conn, _post("p1"))
    store.clear_posts(conn)
    assert store.load_posts(conn) == []


def test_views_none_safe(conn):
    p = _post("p1", views=None, engagement=None)
    store.upsert_post(conn, p)
    loaded = store.load_posts(conn)[0]
    assert loaded.views is None
    assert loaded.engagement is None
