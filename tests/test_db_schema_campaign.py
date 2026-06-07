"""Перевірка що нові таблиці campaigns/creative_assets/partners/campaign_partners
існують після init_db (F1)."""
from __future__ import annotations

import sqlite3

from fundrec import store


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_campaigns_table_exists(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    assert "campaigns" in _tables(conn)


def test_creative_assets_table_exists(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    assert "creative_assets" in _tables(conn)


def test_partners_table_exists(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    assert "partners" in _tables(conn)


def test_campaign_partners_table_exists(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    assert "campaign_partners" in _tables(conn)


def test_campaigns_columns(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    info = conn.execute("PRAGMA table_info(campaigns)").fetchall()
    col_names = {row[1] for row in info}
    expected = {
        "id", "actor_id", "title", "goal", "type",
        "channels", "date_start", "date_end", "year",
        "form_factor", "cta_type", "tone", "face", "cadence", "playbook_note",
        "amount_uah", "amount_usd", "reach", "engagement", "spend", "assets_count",
        "case_id", "partner_ids", "provenance",
        "confidence_overall", "verification_status", "verdict_reason",
        "extracted_at", "extracted_by_model",
    }
    assert expected <= col_names


def test_creative_assets_columns(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    info = conn.execute("PRAGMA table_info(creative_assets)").fetchall()
    col_names = {row[1] for row in info}
    expected = {
        "id", "campaign_id", "platform", "format",
        "copy_text", "hook", "cta", "media_url", "published",
        "impressions_range", "spend_range", "views", "likes", "provenance",
    }
    assert expected <= col_names


def test_partners_columns(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    info = conn.execute("PRAGMA table_info(partners)").fetchall()
    col_names = {row[1] for row in info}
    assert {"id", "name", "role", "links"} <= col_names


def test_campaign_partners_columns(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    info = conn.execute("PRAGMA table_info(campaign_partners)").fetchall()
    col_names = {row[1] for row in info}
    assert {"campaign_id", "partner_id"} <= col_names
