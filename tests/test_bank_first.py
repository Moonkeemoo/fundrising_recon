"""Тести bank-first: підняття осиротілих банок у збір-кампанії.

Покриває:
  - corpus_banks: sweep raw-постів → {jar_id: [post-meta]}, дедуп по source_url;
  - orphan_banks: виключення банок, що вже є призначенням кампанії;
  - build_campaign_from_bank: детерміноване будівництво (з render / без render),
    КРИТИЧНА перевірка campaign_jar_id(built) == jar_id;
  - run_bank_first: інтеграція з temp БД + fake render, ідемпотентність.

Усі зовнішні ефекти інжектуються (fake render); жодної реальної мережі/рендеру/
запису у живу БД.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fundrec import bank_first, dedup, store
from fundrec.schema import Actor, Campaign

_NOW = "2024-03-01T00:00:00+00:00"


# ── фабрики ──────────────────────────────────────────────────────────────────


def _write_raw(raw_dir: Path, payload: dict) -> None:
    """Записує raw-файл під sha256[:16](source_url).json (ingest-схема)."""
    url = payload.get("source_url") or payload.get("url") or ""
    file_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    (raw_dir / f"{file_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _seed_db(tmp_path: Path):
    """Створює tmp БД + порожній raw_dir; повертає (conn, db_path, raw_dir)."""
    db_path = tmp_path / "test.sqlite"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(db_path)
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Тест-актор", type="unknown"))
    return conn, db_path, raw_dir


# ── corpus_banks ─────────────────────────────────────────────────────────────


def test_corpus_banks_maps_jars_to_posts(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_raw(raw_dir, {
        "source_url": "https://t.me/chanA/1",
        "text": "Збір на дрон https://send.monobank.ua/jar/AAA",
        "date": "2024-01-10",
        "views": 100,
    })
    _write_raw(raw_dir, {
        "source_url": "https://t.me/chanA/2",
        "text": "Той самий збір https://send.monobank.ua/jar/AAA ще раз",
        "date": "2024-01-12",
        "views": 200,
    })
    _write_raw(raw_dir, {
        "source_url": "https://t.me/chanB/9",
        "text": "Інший збір https://send.monobank.ua/jar/BBB",
        "date": "2024-01-15",
        "views": 50,
    })

    banks = bank_first.corpus_banks(raw_dir)
    assert set(banks) == {"AAA", "BBB"}
    assert len(banks["AAA"]) == 2  # дві окремі пост-мети
    assert len(banks["BBB"]) == 1
    # channel деривовано з t.me URL
    assert {m["channel"] for m in banks["AAA"]} == {"chanA"}
    assert banks["BBB"][0]["channel"] == "chanB"


def test_corpus_banks_dedups_by_source_url(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    # Той самий source_url у двох файлах — пост-мета має лишитись одна.
    payload = {
        "source_url": "https://t.me/chanA/1",
        "text": "https://send.monobank.ua/jar/AAA",
        "views": 10,
    }
    _write_raw(raw_dir, payload)
    # другий файл вручну з тим самим url але іншим іменем
    (raw_dir / "dup.json").write_text(json.dumps(payload), encoding="utf-8")

    banks = bank_first.corpus_banks(raw_dir)
    assert len(banks["AAA"]) == 1


# ── orphan_banks ─────────────────────────────────────────────────────────────


def test_orphan_banks_excludes_existing_destination(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    # Кампанія з призначенням-банкою AAA вже існує.
    existing = Campaign(
        id="camp-existing",
        actor_id="a1",
        title="Існуючий збір",
        goal="other",
        type="jar",
        provenance={"destination": {
            "source_url": "https://send.monobank.ua/jar/AAA", "tier": 1
        }},
    )
    store.upsert_campaign(conn, existing)

    _write_raw(raw_dir, {
        "source_url": "https://t.me/chanA/1",
        "text": "https://send.monobank.ua/jar/AAA",
    })
    _write_raw(raw_dir, {
        "source_url": "https://t.me/chanB/2",
        "text": "https://send.monobank.ua/jar/BBB",
    })

    orphans = bank_first.orphan_banks(conn, raw_dir)
    assert "AAA" not in orphans  # вже призначення
    assert "BBB" in orphans


# ── build_campaign_from_bank ─────────────────────────────────────────────────


def test_build_campaign_with_render_sets_fields_and_jar_id():
    post_metas = [
        {"channel": "chanA", "source_url": "https://t.me/chanA/1",
         "text": "Збір на дрон", "date": "2024-01-10", "views": 300},
        {"channel": "chanA", "source_url": "https://t.me/chanA/2",
         "text": "донат сюди", "date": "2024-01-12", "views": 100},
    ]
    render = {"amount_uah": 12345.0, "goal_amount": 50000.0, "title": "Дрон для бригади"}

    c = bank_first.build_campaign_from_bank("JARX", post_metas, render=render, now=_NOW)

    # КРИТИЧНА перевірка: dedup бачить банку.
    assert dedup.campaign_jar_id(c) == "JARX"

    assert c.id == "camp-" + hashlib.sha256(b"jar:JARX").hexdigest()[:12]
    assert c.title == "Дрон для бригади"
    assert c.amount_uah == 12345.0
    assert c.goal_amount == 50000.0
    assert c.type == "jar"
    assert c.goal == "other"
    assert c.channels == ["telegram"]
    assert c.reach == 400  # 300 + 100
    assert c.engagement is None
    assert c.date_start == "2024-01-10"
    assert c.date_end == "2024-01-12"
    assert c.year == 2024
    assert c.is_campaign is True
    assert c.verification_status == "verified"
    assert c.confidence_overall == 0.9
    assert c.extracted_at == _NOW
    assert c.extracted_by_model == "bank-first"
    # стиль лишається порожнім (заповнить пізніше LLM-аудит)
    assert c.tone == []
    assert c.form_factor == []
    assert c.face is None
    assert c.cta_type is None
    # actor_id деривовано з каналу max-views (chanA)
    assert c.actor_id == "auto-" + hashlib.sha256(b"chanA").hexdigest()[:8]


def test_build_campaign_without_render_fallback_title_and_auto_status():
    post_metas = [
        {"channel": "chanA", "source_url": "https://t.me/chanA/1",
         "text": "Короткий", "date": "2024-02-01", "views": 10},
        {"channel": "chanA", "source_url": "https://t.me/chanA/2",
         "text": "Терміновий збір на донати для підрозділу, дуже довгий текст про потреби",
         "date": "2024-02-03", "views": 20},
    ]
    c = bank_first.build_campaign_from_bank("JARY", post_metas, render=None, now=_NOW)

    assert dedup.campaign_jar_id(c) == "JARY"
    assert c.amount_uah is None
    assert c.goal_amount is None
    assert c.verification_status == "auto"
    assert c.confidence_overall == 0.5
    # title — деривовано з найдовшого «збір/донат»-тексту, обрізано
    assert "збір" in c.title.lower() or "донат" in c.title.lower()
    assert len(c.title) <= 60


def test_build_campaign_title_fallback_when_no_signal_text():
    post_metas = [
        {"channel": "chanA", "source_url": "https://t.me/chanA/1",
         "text": "просто текст", "date": "2024-02-01", "views": 10},
    ]
    c = bank_first.build_campaign_from_bank("JARZ", post_metas, render=None, now=_NOW)
    assert c.title == "Збір (банка JARZ)"


def test_build_campaign_reach_none_when_all_views_none():
    post_metas = [
        {"channel": "chanA", "source_url": "https://t.me/chanA/1",
         "text": "x", "date": "2024-02-01", "views": None},
    ]
    c = bank_first.build_campaign_from_bank("JARW", post_metas, render=None, now=_NOW)
    assert c.reach is None


# ── run_bank_first ───────────────────────────────────────────────────────────


def _fake_render(jar_id):
    """Канонічне тіло сторінки банки (parse_rendered_jar формат)."""
    return f"Збір банки {jar_id}\n1 000 ₴\n10 000 ₴"


def test_run_bank_first_creates_orphans_skips_existing_idempotent(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    cases_json = tmp_path / "cases.json"
    jars_cache = tmp_path / "jars.json"

    # Існуюча кампанія з банкою AAA — не має дублюватись.
    existing = Campaign(
        id="camp-existing", actor_id="a1", title="Існуючий", goal="other", type="jar",
        provenance={"destination": {
            "source_url": "https://send.monobank.ua/jar/AAA", "tier": 1}},
    )
    store.upsert_campaign(conn, existing)

    # Raw-пости: AAA (existing), BBB та CCC (orphans).
    _write_raw(raw_dir, {"source_url": "https://t.me/chanA/1",
                         "text": "https://send.monobank.ua/jar/AAA", "views": 5})
    _write_raw(raw_dir, {"source_url": "https://t.me/chanB/1",
                         "text": "Збір https://send.monobank.ua/jar/BBB", "views": 50})
    _write_raw(raw_dir, {"source_url": "https://t.me/chanC/1",
                         "text": "Збір https://send.monobank.ua/jar/CCC", "views": 70})

    summary = bank_first.run_bank_first(
        conn, raw_dir=raw_dir, jars_cache_path=jars_cache,
        _render=_fake_render, now=_NOW,
        cases_json=cases_json,
    )

    assert summary["orphans"] == 2
    assert summary["created"] == 2
    assert summary["with_amount"] == 2  # fake render дає суму
    assert summary["campaigns_before"] == 1
    assert summary["campaigns_after"] == 3

    # У БД тепер 3 кампанії; банки BBB/CCC мають кампанії.
    all_jars = {dedup.campaign_jar_id(c) for c in store.load_campaigns(conn)}
    assert {"AAA", "BBB", "CCC"} <= all_jars

    # Ідемпотентність: повторний запуск нічого не створює.
    summary2 = bank_first.run_bank_first(
        conn, raw_dir=raw_dir, jars_cache_path=jars_cache,
        _render=_fake_render, now=_NOW, cases_json=cases_json,
    )
    assert summary2["created"] == 0
    assert summary2["orphans"] == 0
    assert summary2["campaigns_after"] == 3


def test_run_bank_first_no_render_amounts_null(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    cases_json = tmp_path / "cases.json"

    _write_raw(raw_dir, {"source_url": "https://t.me/chanB/1",
                         "text": "Збір https://send.monobank.ua/jar/BBB", "views": 50})

    summary = bank_first.run_bank_first(
        conn, raw_dir=raw_dir, render=False, now=_NOW, cases_json=cases_json,
    )
    assert summary["created"] == 1
    assert summary["with_amount"] == 0
    created = [c for c in store.load_campaigns(conn) if dedup.campaign_jar_id(c) == "BBB"][0]
    assert created.amount_uah is None
    assert created.verification_status == "auto"


def test_run_bank_first_max_items_caps(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    cases_json = tmp_path / "cases.json"
    for jid in ("BBB", "CCC", "DDD"):
        _write_raw(raw_dir, {"source_url": f"https://t.me/ch/{jid}",
                             "text": f"Збір https://send.monobank.ua/jar/{jid}", "views": 5})

    summary = bank_first.run_bank_first(
        conn, raw_dir=raw_dir, render=False, now=_NOW,
        max_items=1, cases_json=cases_json,
    )
    assert summary["created"] == 1
    assert summary["campaigns_after"] == 1


def test_run_bank_first_attaches_posts(tmp_path):
    """Після створення кампаній build_posts привʼязує пости до зборів."""
    conn, _db, raw_dir = _seed_db(tmp_path)
    cases_json = tmp_path / "cases.json"
    _write_raw(raw_dir, {"source_url": "https://t.me/chanB/1", "channel": "chanB",
                         "platform": "telegram",
                         "text": "Збір https://send.monobank.ua/jar/BBB", "views": 50})

    bank_first.run_bank_first(
        conn, raw_dir=raw_dir, render=False, now=_NOW, cases_json=cases_json,
    )
    created = [c for c in store.load_campaigns(conn) if dedup.campaign_jar_id(c) == "BBB"][0]
    linked = store.load_posts(conn, campaign_id=created.id)
    assert len(linked) >= 1
