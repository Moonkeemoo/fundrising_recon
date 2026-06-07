"""Unit 1 — is_campaign: поле схеми, round-trip store, set_campaign_relevance.

TDD: тести написані ДО реалізації.
"""
from __future__ import annotations

import pytest
from fundrec.schema import Campaign


def _base_campaign(**kw) -> Campaign:
    defaults = dict(
        id="c1", actor_id="a1", title="тест", goal="military", type="mixed",
    )
    defaults.update(kw)
    return Campaign(**defaults)


# ---------------------------------------------------------------------------
# Schema: is_campaign field exists with default None
# ---------------------------------------------------------------------------

def test_campaign_has_is_campaign_field():
    c = _base_campaign()
    assert hasattr(c, "is_campaign")
    assert c.is_campaign is None


def test_campaign_is_campaign_true():
    c = _base_campaign(is_campaign=True)
    assert c.is_campaign is True


def test_campaign_is_campaign_false():
    c = _base_campaign(is_campaign=False)
    assert c.is_campaign is False


# ---------------------------------------------------------------------------
# store round-trip: bool/None ↔ INTEGER/NULL
# ---------------------------------------------------------------------------

def _seed(conn):
    from fundrec import store
    from fundrec.schema import Actor
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="T", type="individual"))


def test_store_roundtrip_is_campaign_true(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=True)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is True


def test_store_roundtrip_is_campaign_false(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=False)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is False


def test_store_roundtrip_is_campaign_none(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=None)
    store.upsert_campaign(conn, c)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is None


# ---------------------------------------------------------------------------
# set_campaign_relevance: UPDATE the column
# ---------------------------------------------------------------------------

def test_set_campaign_relevance_sets_true(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=None)
    store.upsert_campaign(conn, c)
    store.set_campaign_relevance(conn, "c1", True)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is True


def test_set_campaign_relevance_sets_false(tmp_path):
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=None)
    store.upsert_campaign(conn, c)
    store.set_campaign_relevance(conn, "c1", False)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is False


def test_set_campaign_relevance_overwrites(tmp_path):
    """set_campaign_relevance can flip True → False."""
    from fundrec import store
    conn = store.connect(tmp_path / "t.sqlite")
    _seed(conn)
    c = _base_campaign(is_campaign=True)
    store.upsert_campaign(conn, c)
    store.set_campaign_relevance(conn, "c1", False)
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is False
