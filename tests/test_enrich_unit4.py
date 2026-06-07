"""Unit 4: enrich_amounts_from_text та enrich_jars — hermetic (tmp sqlite + tmp raw).

enrich_amounts_from_text(conn) -> {scanned, updated}:
  - Заповнює amount_uah/goal_amount з тексту raw-файлу (tier-2)
  - Пропускає кампанії де amount_uah вже є (tier-1)

enrich_jars(conn, *, render) -> {scanned, jars_found, rendered_ok, updated}:
  - Знаходить jar_ids_from_raw, рендерить (inject render), застосовує tier-1
  - Встановлює verification_status="verified" якщо amount отримано
  - Пропускає кампанії де вже є tier-1 amount
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fundrec import store
from fundrec.schema import Campaign


# ---------------------------------------------------------------------------
# Helpers — ті самі що у test_backfill.py, щоб не імпортувати
# ---------------------------------------------------------------------------

def _make_campaign(url: str, **kwargs) -> Campaign:
    cid = "camp-" + hashlib.sha256(url.encode()).hexdigest()[:12]
    defaults = dict(
        id=cid, actor_id="act-1", title="Test", goal="military",
        type="organic_social",
        amount_uah=None, goal_amount=None,
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
    from fundrec.schema import Actor
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="act-1", name="Actor", type="foundation"))
    for c in campaigns:
        store.upsert_campaign(conn, c)


# ---------------------------------------------------------------------------
# enrich_amounts_from_text
# ---------------------------------------------------------------------------


def test_enrich_amounts_fills_amount_from_text(tmp_path):
    """Кампанія без amount_uah + raw з текстом «зібрали 2 млн» → заповнюється tier-2."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/1"
    camp = _make_campaign(url)
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "text": "зібрали 2 млн грн для ЗСУ",
    })

    from fundrec.enrich import enrich_amounts_from_text
    result = enrich_amounts_from_text(conn, raw_dir=raw_dir)

    assert result["scanned"] == 1
    assert result["updated"] == 1

    updated = store.load_campaigns(conn)[0]
    assert updated.amount_uah == 2_000_000.0
    assert updated.provenance["amount_uah"]["tier"] == 2
    assert "text amount" in updated.provenance["amount_uah"]["note"]


def test_enrich_amounts_fills_goal_from_text(tmp_path):
    """goal_amount=None + raw «ціль 5 млн» → заповнюється."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/2"
    camp = _make_campaign(url)
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "text": "ціль 5 млн грн",
    })

    from fundrec.enrich import enrich_amounts_from_text
    result = enrich_amounts_from_text(conn, raw_dir=raw_dir)
    assert result["updated"] == 1

    updated = store.load_campaigns(conn)[0]
    assert updated.goal_amount == 5_000_000.0
    assert updated.provenance["goal_amount"]["tier"] == 2


def test_enrich_amounts_skips_campaign_with_existing_tier1(tmp_path):
    """Кампанія з tier-1 amount_uah — не перезаписується."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/3"
    # Кампанія вже має amount_uah з tier-1 provenance
    camp = _make_campaign(
        url,
        amount_uah=1_000_000.0,
        provenance={
            "amount_uah": {
                "source_url": "https://send.monobank.ua/jar/X",
                "confidence": 0.95,
                "tier": 1,
                "note": "monobank jar tier-1",
            }
        },
    )
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "text": "зібрали 9 млн грн",  # інша сума
    })

    from fundrec.enrich import enrich_amounts_from_text
    result = enrich_amounts_from_text(conn, raw_dir=raw_dir)
    assert result["updated"] == 0

    updated = store.load_campaigns(conn)[0]
    assert updated.amount_uah == 1_000_000.0  # не перезаписано


def test_enrich_amounts_no_text_not_updated(tmp_path):
    """Raw без тексту → not updated."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/4"
    camp = _make_campaign(url)
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "text": None,
    })

    from fundrec.enrich import enrich_amounts_from_text
    result = enrich_amounts_from_text(conn, raw_dir=raw_dir)
    assert result["updated"] == 0


def test_enrich_amounts_no_raw_not_updated(tmp_path):
    """Немає raw-файлу → not updated."""
    raw_dir = tmp_path / "empty_raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/5"
    camp = _make_campaign(url)
    _seed_db(conn, [camp])

    from fundrec.enrich import enrich_amounts_from_text
    result = enrich_amounts_from_text(conn, raw_dir=raw_dir)
    assert result["scanned"] == 1
    assert result["updated"] == 0


def test_enrich_amounts_multiple_campaigns(tmp_path):
    """Кілька кампаній: одна заповнена, одна ні, одна без raw."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url1 = "https://t.me/ch/10"  # заповниться
    url2 = "https://t.me/ch/11"  # вже має tier-1 → skip
    url3 = "https://t.me/ch/12"  # немає raw → skip

    camp1 = _make_campaign(url1)
    camp2 = _make_campaign(
        url2,
        amount_uah=500_000.0,
        provenance={"amount_uah": {"tier": 1, "note": "monobank jar tier-1", "source_url": "", "confidence": 0.95}},
    )
    camp3 = _make_campaign(url3)

    _seed_db(conn, [camp1, camp2, camp3])

    _raw_file(raw_dir, url1, {"source_url": url1, "text": "зібрали 1,5 млн грн"})
    _raw_file(raw_dir, url2, {"source_url": url2, "text": "зібрали 3 млн грн"})

    from fundrec.enrich import enrich_amounts_from_text
    result = enrich_amounts_from_text(conn, raw_dir=raw_dir)
    assert result["scanned"] == 3
    assert result["updated"] == 1

    camps = {c.id: c for c in store.load_campaigns(conn)}
    assert camps[_make_campaign(url1).id].amount_uah == 1_500_000.0
    assert camps[_make_campaign(url2).id].amount_uah == 500_000.0  # не перезаписано
    assert camps[_make_campaign(url3).id].amount_uah is None


# ---------------------------------------------------------------------------
# enrich_jars
# ---------------------------------------------------------------------------


def _fake_render(jar_id: str) -> dict:
    """Фейковий рендерер: повертає фіктивні дані для jar_id='TESTJAR'."""
    if jar_id == "TESTJAR":
        return {
            "jar_id": jar_id,
            "url": f"https://send.monobank.ua/jar/{jar_id}",
            "title": "Банка тест",
            "amount_uah": 3_000_000.0,
            "goal_amount": 10_000_000.0,
        }
    return {
        "jar_id": jar_id,
        "url": f"https://send.monobank.ua/jar/{jar_id}",
        "title": None,
        "amount_uah": None,
        "goal_amount": None,
    }


def test_enrich_jars_fills_from_jar_in_links(tmp_path):
    """Кампанія з jar у links → enrich_jars заповнює amount tier-1 + verified."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/jar1"
    camp = _make_campaign(url)
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "text": "Підтримайте збір!",
        "links": ["https://send.monobank.ua/jar/TESTJAR"],
    })

    from fundrec.enrich import enrich_jars
    result = enrich_jars(conn, raw_dir=raw_dir, render=_fake_render)

    assert result["scanned"] >= 1
    assert result["jars_found"] >= 1
    assert result["rendered_ok"] >= 1
    assert result["updated"] >= 1

    updated = store.load_campaigns(conn)[0]
    assert updated.amount_uah == 3_000_000.0
    assert updated.goal_amount == 10_000_000.0
    assert updated.provenance["amount_uah"]["tier"] == 1
    assert updated.verification_status == "verified"


def test_enrich_jars_fills_from_jar_in_text(tmp_path):
    """Кампанія з jar у text → enrich_jars знаходить і заповнює."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/jar2"
    camp = _make_campaign(url)
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "text": "Банка: send.monobank.ua/jar/TESTJAR — донатьте!",
    })

    from fundrec.enrich import enrich_jars
    result = enrich_jars(conn, raw_dir=raw_dir, render=_fake_render)

    assert result["updated"] >= 1
    updated = store.load_campaigns(conn)[0]
    assert updated.amount_uah == 3_000_000.0
    assert updated.verification_status == "verified"


def test_enrich_jars_skips_if_already_tier1(tmp_path):
    """Кампанія вже з tier-1 amount → enrich_jars не чіпає."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/jar3"
    camp = _make_campaign(
        url,
        amount_uah=500_000.0,
        provenance={"amount_uah": {"tier": 1, "note": "monobank jar tier-1", "source_url": "", "confidence": 0.95}},
    )
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "links": ["https://send.monobank.ua/jar/TESTJAR"],
    })

    from fundrec.enrich import enrich_jars
    result = enrich_jars(conn, raw_dir=raw_dir, render=_fake_render)

    assert result["updated"] == 0
    updated = store.load_campaigns(conn)[0]
    assert updated.amount_uah == 500_000.0  # не перезаписано


def test_enrich_jars_no_jar_not_updated(tmp_path):
    """Немає jar_id у raw → not updated."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/jar4"
    camp = _make_campaign(url)
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "text": "Просто текст без банки",
    })

    from fundrec.enrich import enrich_jars
    result = enrich_jars(conn, raw_dir=raw_dir, render=_fake_render)
    assert result["updated"] == 0
    assert result["jars_found"] == 0


def test_enrich_jars_render_returns_no_amount(tmp_path):
    """Render повертає amount_uah=None → updated=0 (honest null)."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    conn = store.connect(":memory:")

    url = "https://t.me/zbir/jar5"
    camp = _make_campaign(url)
    _seed_db(conn, [camp])

    _raw_file(raw_dir, url, {
        "platform": "telegram",
        "source_url": url,
        "links": ["https://send.monobank.ua/jar/CLOSED_JAR"],  # _fake_render повертає None
    })

    from fundrec.enrich import enrich_jars
    result = enrich_jars(conn, raw_dir=raw_dir, render=_fake_render)
    assert result["rendered_ok"] == 0  # рендер не дав суми
    assert result["updated"] == 0

    updated = store.load_campaigns(conn)[0]
    assert updated.amount_uah is None
    assert updated.verification_status != "verified"
