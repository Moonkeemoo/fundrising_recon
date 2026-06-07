"""Unit 3 — classify_relevance_db + CLI --classify: non-destructive pass.

TDD. Hermetic (tmp sqlite + tmp raw dir + injected judge).

3 кампанії:
  - jar-збір (raw є, is_fundraising True) -> is_campaign=True, no judge call
  - топічний (raw є, is_fundraising False, judge->False) -> is_campaign=False
  - no-raw (raw немає) -> is_campaign лишається None
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fundrec import store
from fundrec.schema import Actor, Campaign


# ---------------------------------------------------------------------------
# Helpers (дзеркало test_relevance_unit3.py)
# ---------------------------------------------------------------------------

def _make_campaign(url: str, **kwargs) -> Campaign:
    cid = "camp-" + hashlib.sha256(url.encode()).hexdigest()[:12]
    defaults = dict(
        id=cid, actor_id="act-1", title="Test", goal="military",
        type="organic_social", provenance={},
    )
    defaults.update(kwargs)
    return Campaign(**defaults)


def _write_raw(raw_dir: Path, url: str, payload: dict) -> None:
    file_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    p = raw_dir / f"{file_id}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _seed_db(conn, actor_id: str = "act-1") -> None:
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id=actor_id, name="Actor", type="foundation"))


# ---------------------------------------------------------------------------
# Тест 1: основна поведінка
# ---------------------------------------------------------------------------

def test_classify_relevance_db_three_campaigns(tmp_path):
    """jar->True (no judge); topical->False (judge False); no-raw->None."""
    from fundrec.relevance import classify_relevance_db

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url_jar = "https://example.com/jar_zbir"
    url_topical = "https://example.com/topical"
    url_no_raw = "https://example.com/no_raw"

    camp_jar = _make_campaign(url_jar, title="FPV збір")
    camp_topical = _make_campaign(url_topical, title="TCCC відео")
    camp_no_raw = _make_campaign(url_no_raw, title="Без raw")

    for c in (camp_jar, camp_topical, camp_no_raw):
        store.upsert_campaign(conn, c)

    _write_raw(raw_dir, url_jar, {
        "url": url_jar,
        "title": "FPV збір",
        "text": "Банка: send.monobank.ua/jar/FPVJAR",
    })
    _write_raw(raw_dir, url_topical, {
        "url": url_topical,
        "title": "TCCC відео",
        "text": "Навчальний контент, огляд аптечки.",
    })

    judge_calls = {"n": 0}

    def fake_judge(prompt):
        judge_calls["n"] += 1
        return {"is_campaign": False}

    summary = classify_relevance_db(conn, raw_dir, judge=fake_judge)

    # Перевіряємо прапори
    loaded = {c.id: c for c in store.load_campaigns(conn)}
    assert loaded[camp_jar.id].is_campaign is True
    assert loaded[camp_topical.id].is_campaign is False
    assert loaded[camp_no_raw.id].is_campaign is None

    # Жоден з jar-кампаній не пішов до судді
    assert judge_calls["n"] == 1  # тільки topical

    # Summary counts
    assert summary["relevant"] == 1
    assert summary["topical"] == 1
    assert summary["no_raw"] == 1
    assert summary["llm_calls"] == 1


def test_classify_relevance_db_only_unset_skips_already_set(tmp_path):
    """only_unset=True пропускає кампанії де is_campaign вже встановлено."""
    from fundrec.relevance import classify_relevance_db

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url = "https://example.com/already_set"
    camp = _make_campaign(url, title="Вже класифіковано", is_campaign=True)
    store.upsert_campaign(conn, camp)

    _write_raw(raw_dir, url, {
        "url": url,
        "title": "Вже класифіковано",
        "text": "Навчальний контент.",
    })

    judge_calls = {"n": 0}

    def fake_judge(prompt):
        judge_calls["n"] += 1
        return {"is_campaign": False}

    summary = classify_relevance_db(conn, raw_dir, judge=fake_judge, only_unset=True)

    # Judge не повинен викликатись — кампанія вже класифікована
    assert judge_calls["n"] == 0
    # is_campaign не змінилось
    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is True


def test_classify_relevance_db_only_unset_false_reclassifies(tmp_path):
    """only_unset=False повторно класифікує навіть вже встановлені."""
    from fundrec.relevance import classify_relevance_db

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    url = "https://example.com/reclassify"
    # Спочатку встановлено True
    camp = _make_campaign(url, title="Перекласифікація", is_campaign=True)
    store.upsert_campaign(conn, camp)

    _write_raw(raw_dir, url, {
        "url": url,
        "title": "Перекласифікація",
        "text": "Навчальний контент.",
    })

    def fake_judge(prompt):
        return {"is_campaign": False}

    classify_relevance_db(conn, raw_dir, judge=fake_judge, only_unset=False)

    loaded = store.load_campaigns(conn)
    assert loaded[0].is_campaign is False


# ---------------------------------------------------------------------------
# Тест 2: CLI --classify
# ---------------------------------------------------------------------------

def test_cli_classify_runs_and_prints_summary(tmp_path, capsys):
    """CLI --classify запускається, виводить summary (relevant/topical/no_raw)."""
    from fundrec.relevance import main

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    conn.close()

    result_code = main([
        "--classify",
        "--db", str(tmp_path / "t.sqlite"),
        "--raw-dir", str(tmp_path / "raw"),
        "--out", str(tmp_path / "cases.json"),
    ])

    assert result_code == 0
    captured = capsys.readouterr()
    assert "relevant" in captured.out


def test_cli_classify_exports_cases_json(tmp_path):
    """CLI --classify записує cases.json після класифікації."""
    from fundrec.relevance import main

    conn = store.connect(tmp_path / "t.sqlite")
    _seed_db(conn)
    conn.close()

    out_path = tmp_path / "cases.json"
    main([
        "--classify",
        "--db", str(tmp_path / "t.sqlite"),
        "--raw-dir", str(tmp_path / "raw"),
        "--out", str(out_path),
    ])

    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert "cases" in data
