"""Unit 3: агрегація охоплення (reach) постів у export_cases.

Герметично — tmp sqlite + tmp out; реальна БД не торкається.
"""
from __future__ import annotations

import json

from fundrec import export, store
from fundrec.schema import Actor, Campaign, Post


def _setup(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="A", type="foundation"))
    return conn


def _camp(cid: str, title: str = "Збір") -> Campaign:
    return Campaign(id=cid, actor_id="a1", title=title, goal="military", type="jar")


def _post(pid, cid, *, views=None, eng=None, date=None, channel="ch", url=None) -> Post:
    return Post(
        id=pid,
        campaign_id=cid,
        source_url=url or f"https://t.me/{pid}",
        channel=channel,
        platform="telegram",
        date=date,
        views=views,
        engagement=eng,
        text_snippet="t",
    )


def _camp_dict(data, cid):
    return next(c for c in data["campaigns"] if c["id"] == cid)


def test_export_includes_reach_aggregation(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("camp-1"))
    store.upsert_post(conn, _post("p1", "camp-1", views=100, eng=5, date="2026-01-01", channel="a"))
    store.upsert_post(conn, _post("p2", "camp-1", views=300, eng=None, date="2026-01-05", channel="b"))

    out = tmp_path / "cases.json"
    export.export_cases(conn, out, raw_dir=tmp_path / "noraw")
    data = json.loads(out.read_text(encoding="utf-8"))
    c = _camp_dict(data, "camp-1")

    assert c["reach_total"] == 400
    assert c["engagement_total"] == 5
    assert c["post_count"] == 2
    assert c["channel_count"] == 2
    assert c["first_post"] == "2026-01-01"
    assert c["last_post"] == "2026-01-05"
    assert set(c["post_channels"]) == {"a", "b"}
    assert len(c["posts"]) == 2
    # posts sorted by date ascending
    assert c["posts"][0]["date"] == "2026-01-01"
    assert c["posts"][0]["url"] == "https://t.me/p1"


def test_export_none_safe_when_no_posts(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("camp-empty"))

    out = tmp_path / "cases.json"
    export.export_cases(conn, out, raw_dir=tmp_path / "noraw")
    data = json.loads(out.read_text(encoding="utf-8"))
    c = _camp_dict(data, "camp-empty")

    assert c["reach_total"] is None
    assert c["engagement_total"] is None
    assert c["post_count"] == 0
    assert c["channel_count"] == 0
    assert c["first_post"] is None
    assert c["last_post"] is None
    assert c["post_channels"] == []
    assert c["posts"] == []


def test_export_reach_none_when_all_views_unknown(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("camp-2"))
    store.upsert_post(conn, _post("p1", "camp-2", views=None, eng=None, date="2026-01-01"))

    out = tmp_path / "cases.json"
    export.export_cases(conn, out, raw_dir=tmp_path / "noraw")
    data = json.loads(out.read_text(encoding="utf-8"))
    c = _camp_dict(data, "camp-2")

    assert c["reach_total"] is None  # honest null, not 0
    assert c["post_count"] == 1
