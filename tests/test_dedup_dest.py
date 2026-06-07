"""Unit 2 — destination-centric regroup у dedup_pass.

Кампанії, що ділять БУДЬ-ЯКЕ призначення (jar:<id> / priv:<id>) з raw-постів,
зливаються в один збір. Тести: tmp sqlite + tmp raw-директорія (hermetic).
Реальна БД/raw не торкаються.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from fundrec import store
from fundrec.dedup_pass import dedup_database
from fundrec.schema import Actor, Campaign, CreativeAsset
from fundrec.store import init_db, upsert_actor, upsert_campaign, upsert_creative


@pytest.fixture()
def tmp_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    upsert_actor(conn, Actor(id="a1", name="Actor", type="foundation"))
    return conn


def _raw_file_for(raw_dir: Path, source_url: str, payload: dict) -> str:
    """Записує raw-файл за тим самим іменем, що очікує backfill-style lookup.

    Ім'я: sha256(source_url)[:16].json. id кампанії: camp-<sha256(url)[:12]>.
    """
    file_id = hashlib.sha256(source_url.encode()).hexdigest()[:16]
    (raw_dir / f"{file_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return "camp-" + hashlib.sha256(source_url.encode()).hexdigest()[:12]


def _camp(camp_id: str, *, title: str, source_url: str, amount: float | None = None) -> Campaign:
    prov: dict = {"campaign": {"source_url": source_url, "tier": 3, "confidence": 0.4}}
    if amount is not None:
        prov["amount_uah"] = {
            "source_url": source_url,
            "tier": 1,
            "confidence": 0.95,
            "note": "jar",
        }
    return Campaign(
        id=camp_id,
        actor_id="a1",
        title=title,
        goal="military",
        type="jar",
        amount_uah=amount,
        provenance=prov,
    )


def test_regroup_merges_two_campaigns_sharing_jar(tmp_conn, tmp_path):
    """Дві кампанії з різними постами, що містять той самий jar → 1 збір з сумою."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url1 = "https://t.me/ch/1"
    url2 = "https://t.me/ch/2"
    # Обидва пости містять той самий jar, але різні назви (Pass-1 identity не зловить
    # бо jar лише в text raw, не в provenance source_url).
    id1 = _raw_file_for(raw_dir, url1, {"text": "Збір! send.monobank.ua/jar/SHAREDJAR"})
    id2 = _raw_file_for(raw_dir, url2, {"text": "Терміново send.monobank.ua/jar/SHAREDJAR"})

    upsert_campaign(tmp_conn, _camp(id1, title="Допомога підрозділу А", source_url=url1, amount=300_000.0))
    upsert_campaign(tmp_conn, _camp(id2, title="Збір на техніку Б", source_url=url2))

    summary = dedup_database(tmp_conn, raw_dir=raw_dir)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    assert remaining[0].amount_uah == 300_000.0
    assert summary["dest_merged"] == 1


def test_regroup_merges_pair_sharing_privat(tmp_conn, tmp_path):
    """Пара кампаній зі спільним PrivatBank-конвертом → зливається."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url1 = "https://t.me/ch/10"
    url2 = "https://t.me/ch/11"
    id1 = _raw_file_for(raw_dir, url1, {"text": "https://www.privat24.ua/send/ENVELOPE1"})
    id2 = _raw_file_for(raw_dir, url2, {"text": "Реквізити: https://www.privat24.ua/send/ENVELOPE1"})

    upsert_campaign(tmp_conn, _camp(id1, title="Конверт перший пост", source_url=url1))
    upsert_campaign(tmp_conn, _camp(id2, title="Конверт другий пост", source_url=url2))

    summary = dedup_database(tmp_conn, raw_dir=raw_dir)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    assert summary["dest_merged"] == 1


def test_regroup_leaves_unrelated_alone(tmp_conn, tmp_path):
    """Кампанії з різними призначеннями не зливаються."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url1 = "https://t.me/ch/20"
    url2 = "https://t.me/ch/21"
    id1 = _raw_file_for(raw_dir, url1, {"text": "send.monobank.ua/jar/JARONE"})
    id2 = _raw_file_for(raw_dir, url2, {"text": "send.monobank.ua/jar/JARTWO"})

    upsert_campaign(tmp_conn, _camp(id1, title="Перший унікальний збір", source_url=url1))
    upsert_campaign(tmp_conn, _camp(id2, title="Другий зовсім інший збір", source_url=url2))

    summary = dedup_database(tmp_conn, raw_dir=raw_dir)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 2
    assert summary["dest_merged"] == 0


def test_regroup_repoints_creatives(tmp_conn, tmp_path):
    """Креативи loser-кампанії переприв'язуються до canonical."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url1 = "https://t.me/ch/30"
    url2 = "https://t.me/ch/31"
    id1 = _raw_file_for(raw_dir, url1, {"text": "send.monobank.ua/jar/CJAR"})
    id2 = _raw_file_for(raw_dir, url2, {"text": "send.monobank.ua/jar/CJAR"})

    upsert_campaign(tmp_conn, _camp(id1, title="Канон збір", source_url=url1, amount=100_000.0))
    upsert_campaign(tmp_conn, _camp(id2, title="Дублюючий пост", source_url=url2))
    upsert_creative(tmp_conn, CreativeAsset(id="cr1", campaign_id=id2, platform="telegram", format="text"))

    dedup_database(tmp_conn, raw_dir=raw_dir)

    remaining = store.load_campaigns(tmp_conn)
    assert len(remaining) == 1
    canonical_id = remaining[0].id
    creatives = store.load_creatives(tmp_conn)
    assert len(creatives) == 1
    assert creatives[0].campaign_id == canonical_id


def test_regroup_skipped_when_no_raw_dir(tmp_conn):
    """Без raw_dir destination-pass не виконується (зворотна сумісність)."""
    upsert_campaign(tmp_conn, _camp("c1", title="Збір A", source_url="https://t.me/x/1"))
    summary = dedup_database(tmp_conn)
    assert summary.get("dest_merged", 0) == 0


def test_regroup_summary_always_has_key(tmp_conn, tmp_path):
    """dest_merged присутній у summary навіть коли raw_dir переданий."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    summary = dedup_database(tmp_conn, raw_dir=raw_dir)
    assert "dest_merged" in summary
