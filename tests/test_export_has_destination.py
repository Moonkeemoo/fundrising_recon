"""Unit 3 — export збагачує кампанії полем has_destination.

has_destination = чи має кампанія БУДЬ-ЯКЕ призначення донату (jar/priv).
Деривація: jar з provenance (campaign_jar_id) АБО призначення з raw-поста
(extract_destinations), якщо передано raw_dir.
"""

from __future__ import annotations

import hashlib
import json

from fundrec import export, store
from fundrec.schema import Actor, Campaign


def _setup(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="ЗСУ", type="foundation"))
    return conn


def _jar_prov(jar_id: str, source_url: str = "https://t.me/x/1") -> dict:
    return {
        "campaign": {"source_url": source_url, "tier": 3, "confidence": 0.4},
        "amount_uah": {
            "source_url": f"https://send.monobank.ua/jar/{jar_id}",
            "tier": 1,
            "confidence": 0.95,
        },
    }


def test_export_has_destination_true_for_jar_provenance(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, Campaign(
        id="k1", actor_id="a1", title="Збір з банкою",
        goal="military", type="jar", provenance=_jar_prov("JARABC"),
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    camp = json.loads(out.read_text(encoding="utf-8"))["campaigns"][0]
    assert camp["has_destination"] is True


def test_export_has_destination_false_without_destination(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, Campaign(
        id="k2", actor_id="a1", title="Просто допис без донату",
        goal="military", type="organic_social",
        provenance={"campaign": {"source_url": "https://t.me/x/2", "tier": 3}},
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    camp = json.loads(out.read_text(encoding="utf-8"))["campaigns"][0]
    assert camp["has_destination"] is False


def test_export_has_destination_present_for_all(tmp_path):
    conn = _setup(tmp_path)
    for i in range(3):
        store.upsert_campaign(conn, Campaign(
            id=f"k{i}", actor_id="a1", title=f"Кампанія {i}",
            goal="military", type="organic_social",
        ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    for camp in json.loads(out.read_text(encoding="utf-8"))["campaigns"]:
        assert "has_destination" in camp
        assert isinstance(camp["has_destination"], bool)


def test_export_has_destination_true_from_raw_privat(tmp_path):
    """Конверт PrivatBank лише у raw-тексті → has_destination True через raw_dir."""
    conn = _setup(tmp_path)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    src = "https://t.me/x/9"
    file_id = hashlib.sha256(src.encode()).hexdigest()[:16]
    (raw_dir / f"{file_id}.json").write_text(
        json.dumps({"text": "Реквізити https://www.privat24.ua/send/ENV1"}),
        encoding="utf-8",
    )
    camp_id = "camp-" + hashlib.sha256(src.encode()).hexdigest()[:12]
    store.upsert_campaign(conn, Campaign(
        id=camp_id, actor_id="a1", title="Конверт без jar у provenance",
        goal="military", type="organic_social",
        provenance={"campaign": {"source_url": src, "tier": 3}},
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out, raw_dir=raw_dir)
    camp = json.loads(out.read_text(encoding="utf-8"))["campaigns"][0]
    assert camp["has_destination"] is True
