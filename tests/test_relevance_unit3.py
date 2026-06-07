"""Unit 3 — purge_non_fundraising + CLI: видаляє нерелевантні кампанії з БД.

TDD: тести написані ДО реалізації. Hermetic (tmp sqlite + tmp raw dir).

3 кампанії:
  - топічна (raw є, is_fundraising=False) → видаляється
  - jar-збір (raw є, is_fundraising=True) → залишається
  - без raw-файлу → залишається (консервативно)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fundrec import store
from fundrec.schema import Actor, Campaign, CreativeAsset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_campaign(url: str, **kwargs) -> Campaign:
    cid = "camp-" + hashlib.sha256(url.encode()).hexdigest()[:12]
    defaults = dict(
        id=cid,
        actor_id="act-1",
        title="Test",
        goal="military",
        type="organic_social",
        reach=None,
        engagement=None,
        date_start=None,
        goal_reached=None,
        provenance={},
    )
    defaults.update(kwargs)
    return Campaign(**defaults)


def _make_creative(campaign_id: str, creative_id: str) -> CreativeAsset:
    return CreativeAsset(
        id=creative_id,
        campaign_id=campaign_id,
        platform="youtube",
        format="video",
        provenance={},
    )


def _write_raw(raw_dir: Path, url: str, payload: dict) -> Path:
    """Записує raw-файл для url у raw_dir (за тим же алгоритмом що й ingest)."""
    file_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    p = raw_dir / f"{file_id}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _seed_db(conn, actor_id: str = "act-1") -> None:
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id=actor_id, name="Actor", type="foundation"))


# ---------------------------------------------------------------------------
# Тест 1: основна поведінка purge_non_fundraising
# ---------------------------------------------------------------------------

def test_purge_deletes_topical_keeps_jar_keeps_no_raw(tmp_path):
    """3 кампанії: топічна видаляється, jar залишається, no-raw залишається."""
    from fundrec.relevance import purge_non_fundraising

    conn = store.connect(tmp_path / "test.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url_topical = "https://example.com/tccc_video"
    url_jar = "https://example.com/fpv_zbir"
    url_no_raw = "https://example.com/no_raw_camp"

    camp_topical = _make_campaign(url_topical, title="TCCC відео")
    camp_jar = _make_campaign(url_jar, title="FPV збір")
    camp_no_raw = _make_campaign(url_no_raw, title="Без raw-файлу")

    for c in (camp_topical, camp_jar, camp_no_raw):
        store.upsert_campaign(conn, c)

    # raw для топічного (no ask)
    _write_raw(raw_dir, url_topical, {
        "url": url_topical,
        "title": "ТАКТИЧНА АПТЕЧКА TCCC для військових",
        "raw_text": "Навчальний контент без реквізитів.",
    })

    # raw для jar-збору
    _write_raw(raw_dir, url_jar, {
        "url": url_jar,
        "title": "FPV збір",
        "raw_text": "Збираємо на FPV. Банка: send.monobank.ua/jar/FPVJAR1",
    })

    # NO raw для no_raw (файл не записуємо)

    result = purge_non_fundraising(conn, raw_dir)

    assert result["scanned"] == 3
    assert result["deleted"] == 1
    assert result["kept"] == 2
    assert result["no_raw"] == 1

    remaining = store.load_campaigns(conn)
    remaining_ids = {c.id for c in remaining}

    assert camp_topical.id not in remaining_ids, "Топічна кампанія повинна бути видалена"
    assert camp_jar.id in remaining_ids, "Jar-збір повинен залишитись"
    assert camp_no_raw.id in remaining_ids, "Кампанія без raw повинна залишитись"


# ---------------------------------------------------------------------------
# Тест 2: creative_assets видаляються разом з топічною кампанією
# ---------------------------------------------------------------------------

def test_purge_deletes_creatives_of_deleted_campaign(tmp_path):
    """creative_assets видаленої кампанії також видаляються."""
    from fundrec.relevance import purge_non_fundraising

    conn = store.connect(tmp_path / "test.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url_topical = "https://example.com/topical_with_creative"
    camp = _make_campaign(url_topical, title="Топічне з creativе")
    store.upsert_campaign(conn, camp)

    creative = _make_creative(camp.id, "cre-topical-1")
    store.upsert_creative(conn, creative)

    _write_raw(raw_dir, url_topical, {
        "url": url_topical,
        "title": "Навчальний відео",
        "raw_text": "Освітній контент без реквізитів і посилань.",
    })

    # До purge: creative існує
    creatives_before = store.load_creatives(conn, campaign_id=camp.id)
    assert len(creatives_before) == 1

    result = purge_non_fundraising(conn, raw_dir)

    assert result["deleted"] == 1
    # Після purge: кампанія видалена
    assert store.get_campaign(conn, camp.id) is None
    # Creative теж видалено
    creatives_after = store.load_creatives(conn, campaign_id=camp.id)
    assert len(creatives_after) == 0


# ---------------------------------------------------------------------------
# Тест 3: jar-кампанія залишається навіть якщо є raw
# ---------------------------------------------------------------------------

def test_purge_keeps_jar_campaign_with_raw(tmp_path):
    """Jar-кампанія з raw не видаляється."""
    from fundrec.relevance import purge_non_fundraising

    conn = store.connect(tmp_path / "test.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url = "https://example.com/real_jar_zbir"
    camp = _make_campaign(url, title="Реальний збір")
    store.upsert_campaign(conn, camp)

    _write_raw(raw_dir, url, {
        "url": url,
        "title": "FPV збір",
        "text": "Донат: send.monobank.ua/jar/KEEPJAR1",
    })

    result = purge_non_fundraising(conn, raw_dir)

    assert result["deleted"] == 0
    assert result["kept"] == 1
    assert store.get_campaign(conn, camp.id) is not None


# ---------------------------------------------------------------------------
# Тест 4: кампанія без raw-файлу не видаляється (консервативно)
# ---------------------------------------------------------------------------

def test_purge_keeps_campaign_without_raw(tmp_path):
    """Кампанія без raw-файлу НЕ видаляється (no evidence = keep)."""
    from fundrec.relevance import purge_non_fundraising

    conn = store.connect(tmp_path / "test.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url = "https://example.com/mystery_camp"
    camp = _make_campaign(url, title="Без raw")
    store.upsert_campaign(conn, camp)

    # Не записуємо raw-файл

    result = purge_non_fundraising(conn, raw_dir)

    assert result["deleted"] == 0
    assert result["no_raw"] == 1
    assert result["kept"] == 1
    assert store.get_campaign(conn, camp.id) is not None


# ---------------------------------------------------------------------------
# Тест 5: порожня БД — no crash, scanned=0
# ---------------------------------------------------------------------------

def test_purge_empty_db(tmp_path):
    """Порожня БД → scanned=0, без краша."""
    from fundrec.relevance import purge_non_fundraising

    conn = store.connect(tmp_path / "test.sqlite")
    _seed_db(conn)

    result = purge_non_fundraising(conn, tmp_path / "raw")

    assert result == {"scanned": 0, "deleted": 0, "kept": 0, "no_raw": 0}


# ---------------------------------------------------------------------------
# Тест 6: IBAN у raw → зберігається (не видаляється)
# ---------------------------------------------------------------------------

def test_purge_keeps_iban_campaign(tmp_path):
    """Кампанія з IBAN у raw зберігається."""
    from fundrec.relevance import purge_non_fundraising

    conn = store.connect(tmp_path / "test.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url = "https://example.com/iban_zbir"
    camp = _make_campaign(url, title="IBAN збір")
    store.upsert_campaign(conn, camp)

    _write_raw(raw_dir, url, {
        "url": url,
        "title": "Збір на дрони",
        "text": "Реквізити: UA213223130000026007233566001",
    })

    result = purge_non_fundraising(conn, raw_dir)

    assert result["deleted"] == 0
    assert store.get_campaign(conn, camp.id) is not None


# ---------------------------------------------------------------------------
# Тест 7: CLI --purge
# ---------------------------------------------------------------------------

def test_cli_purge_runs_and_prints_summary(tmp_path, capsys):
    """CLI --purge запускається, виводить scanned/deleted/kept/no_raw."""
    from fundrec.relevance import main

    conn = store.connect(tmp_path / "test.sqlite")
    _seed_db(conn)
    conn.close()

    result_code = main([
        "--purge",
        "--db", str(tmp_path / "test.sqlite"),
        "--raw-dir", str(tmp_path / "raw"),
        "--out", str(tmp_path / "cases.json"),
    ])

    assert result_code == 0
    captured = capsys.readouterr()
    assert "scanned" in captured.out
    assert "deleted" in captured.out


def test_cli_purge_missing_db_returns_1(tmp_path, capsys):
    """CLI --purge з відсутньою БД повертає код 1."""
    from fundrec.relevance import main

    result_code = main([
        "--purge",
        "--db", str(tmp_path / "nonexistent.sqlite"),
        "--raw-dir", str(tmp_path / "raw"),
    ])

    assert result_code == 1


def test_cli_no_args_returns_1(tmp_path, capsys):
    """CLI без --purge → код 1 та help."""
    from fundrec.relevance import main

    result_code = main([])
    assert result_code == 1


# ---------------------------------------------------------------------------
# Тест 8: CLI --purge re-exports cases.json
# ---------------------------------------------------------------------------

def test_cli_purge_exports_cases_json(tmp_path):
    """CLI --purge записує cases.json після purge."""
    from fundrec.relevance import main

    conn = store.connect(tmp_path / "test.sqlite")
    _seed_db(conn)
    conn.close()

    out_path = tmp_path / "cases.json"
    main([
        "--purge",
        "--db", str(tmp_path / "test.sqlite"),
        "--raw-dir", str(tmp_path / "raw"),
        "--out", str(out_path),
    ])

    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert "cases" in data
    assert "count" in data
