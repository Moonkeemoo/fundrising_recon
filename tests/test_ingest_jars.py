"""Тести Unit 3: підключення jar-даних до ingest.

Перевіряє:
1. Якщо пост містить jar-id і fake jar fetcher повертає amount:
   - campaign.amount_uah перезаписується значенням банки
   - provenance['amount_uah'] має tier=1 і source_url банки
2. Два пости з ОДНАКОВИМ jar-id → лише ОДНА кампанія (jar-деdup).
3. Jar-id вже в БД (provenance) → ПРОПУСКАЄТЬСЯ.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

_FAKE_LLM_CASE = {
    "title": "FPV дрони",
    "goal": "military/fpv",
    "style": ["urgency"],
    "method": ["monobank_jar"],
    "year": 2024,
    "amount_uah": None,   # не дало LLM — буде замінено банкою
    "amount_usd": None,
    "goal_amount": 500_000.0,
    "currency_raw": "UAH",
}

_FAKE_LLM_CAMPAIGN = {
    "title": "FPV кампанія",
    "goal": "military/fpv",
    "type": "jar",
    "channels": ["telegram"],
    "date_start": None,
    "date_end": None,
    "year": 2024,
    "form_factor": ["text"],
    "cta_type": "jar",
    "tone": ["urgency"],
    "face": None,
    "cadence": None,
    "playbook_note": "Jar-based fundraising",
    "amount_uah": None,   # не дало LLM
    "amount_usd": None,
    "reach": None,
    "engagement": None,
    "spend": None,
    "assets_count": None,
    "case_id": None,
    "creatives": [],
    "partners": [],
}

# Telegram-пост з jar-id JARTEST01
_POST_WITH_JAR = {
    "source_url": "https://t.me/testchan/101",
    "platform": "telegram",
    "channel": "testchan",
    "text": "Збираємо на FPV! Банка: send.monobank.ua/jar/JARTEST01 — донатьте!",
    "views": 5000,
    "date": "2024-03-15T10:00:00+00:00",
    "message_id": 101,
}

# Другий пост з ТИМ САМИМ jar-id JARTEST01
_POST_WITH_SAME_JAR = {
    "source_url": "https://t.me/testchan/105",
    "platform": "telegram",
    "channel": "testchan",
    "text": "Нагадуємо про збір! send.monobank.ua/jar/JARTEST01",
    "views": 2000,
    "date": "2024-03-16T10:00:00+00:00",
    "message_id": 105,
}

_JAR_DATA_JARTEST01 = {
    "jar_id": "JARTEST01",
    "url": "https://send.monobank.ua/jar/JARTEST01",
    "title": "FPV дрони для 47-ї бригади",
    "amount_uah": 125_000.0,
    "goal_amount": 500_000.0,
}


def _make_jar_ingest_components(*, posts, jar_data=None):
    """Будує _components з fake telegram collector і fake jar fetcher."""

    def fake_telegram(theme):
        return list(posts)

    def fake_jar_fetch(jar_id, *, _client=None):
        return jar_data  # може бути None або dict

    def fake_complete(prompt):
        if "creatives" in prompt:
            return _FAKE_LLM_CAMPAIGN.copy()
        return _FAKE_LLM_CASE.copy()

    return {
        "search": lambda q: [],
        "collect": {
            "telegram": fake_telegram,
            "jar": fake_jar_fetch,
        },
        "complete": fake_complete,
        "judge": lambda p: {"supported": True, "confidence": 0.9, "reason": "ok"},
        "sleep": lambda s: None,
    }


# ---------------------------------------------------------------------------
# Тест 1: Jar amount стає tier-1 і перезаписує campaign.amount_uah
# ---------------------------------------------------------------------------


def test_jar_amount_stored_as_tier1(tmp_path):
    """Якщо jar fetcher повертає amount → campaign.amount_uah = jar.amount_uah,
    provenance['amount_uah'] має tier=1 і source_url банки."""
    from fundrec import ingest, store

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR],
        jar_data=_JAR_DATA_JARTEST01,
    )
    ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    camp = campaigns[0]

    # Значення amount_uah з банки
    assert camp.amount_uah == 125_000.0

    # Provenance tier=1 для amount_uah
    prov = camp.provenance.get("amount_uah", {})
    assert prov.get("tier") == 1
    assert prov.get("source_url") == "https://send.monobank.ua/jar/JARTEST01"
    assert prov.get("confidence") == 0.95  # _TIER_CONFIDENCE[1]


def test_jar_amount_in_case_tier1(tmp_path):
    """Case.amount_uah теж перезаписується jar amount з tier-1 provenance."""
    from fundrec import ingest, store

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR],
        jar_data=_JAR_DATA_JARTEST01,
    )
    ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    cases = store.load_cases(conn)
    assert len(cases) >= 1
    case = cases[0]

    assert case.amount_uah == 125_000.0
    prov = case.provenance.get("amount_uah", {})
    assert prov.get("tier") == 1


# ---------------------------------------------------------------------------
# Тест 2: Два пости з ОДНАКОВИМ jar-id → лише 1 кампанія (jar-dedup)
# ---------------------------------------------------------------------------


def test_same_jar_two_posts_dedup_to_one_campaign(tmp_path):
    """Два пости з однаковим jar-id JARTEST01 → ДЕДУПлікуються → 1 кампанія."""
    from fundrec import ingest, store

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR, _POST_WITH_SAME_JAR],
        jar_data=_JAR_DATA_JARTEST01,
    )
    summary = ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=10,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    # Незважаючи на 2 пости — тільки 1 кампанія (jar-dedup)
    assert len(campaigns) == 1
    assert summary["campaigns"] == 1


def test_same_jar_dedup_second_run(tmp_path):
    """Повторний запуск з тим самим jar-id не дублює кампанію."""
    from fundrec import ingest, store

    db_path = tmp_path / "test.sqlite"
    out_path = tmp_path / "cases.json"
    raw_dir = tmp_path / "raw"

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR],
        jar_data=_JAR_DATA_JARTEST01,
    )
    ingest.run_ingest(
        "FPV", sources=["telegram"], max_items=5,
        db_path=db_path, out_path=out_path, raw_dir=raw_dir,
        _components=components,
    )
    ingest.run_ingest(
        "FPV", sources=["telegram"], max_items=5,
        db_path=db_path, out_path=out_path, raw_dir=raw_dir,
        _components=components,
    )

    conn = store.connect(db_path)
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1


# ---------------------------------------------------------------------------
# Тест 3: jar fetcher повертає None → не чіпаємо amount, не деdupin
# ---------------------------------------------------------------------------


def test_no_jar_data_leaves_llm_amount(tmp_path):
    """Якщо jar fetcher повертає None → amount_uah залишається з LLM (може бути None)."""
    from fundrec import ingest, store

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR],
        jar_data=None,  # jar не повернув даних
    )
    ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    # Кампанія створена, але amount_uah = None (LLM повернув None, jar теж None)
    assert len(campaigns) == 1
    camp = campaigns[0]
    assert camp.amount_uah is None
    # Provenance для amount_uah — відсутнє (бо None)
    assert "amount_uah" not in camp.provenance


def test_post_without_jar_id_processes_normally(tmp_path):
    """Пост без jar-id обробляється нормально (jar fetcher не викликається)."""
    from fundrec import ingest, store

    post_no_jar = {
        "source_url": "https://t.me/testchan/999",
        "platform": "telegram",
        "channel": "testchan",
        "text": "Збір на автомобіль! Реквізити у нас на сайті.",
        "views": 1000,
        "date": "2024-03-15T10:00:00+00:00",
        "message_id": 999,
    }
    jar_calls = []

    def fake_jar_fetch(jar_id, *, _client=None):
        jar_calls.append(jar_id)
        return None

    components = {
        "search": lambda q: [],
        "collect": {
            "telegram": lambda theme: [post_no_jar],
            "jar": fake_jar_fetch,
        },
        "complete": lambda p: _FAKE_LLM_CAMPAIGN.copy() if "creatives" in p else _FAKE_LLM_CASE.copy(),
        "judge": lambda p: {"supported": True, "confidence": 0.9, "reason": "ok"},
        "sleep": lambda s: None,
    }

    ingest.run_ingest(
        "FPV дрони",
        sources=["telegram"],
        max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    campaigns = store.load_campaigns(conn)
    assert len(campaigns) == 1
    # jar fetcher не викликався (немає jar-id у тексті)
    assert jar_calls == []


# ---------------------------------------------------------------------------
# Тест 4: _jar_already_in_db — перевіряє helper напряму
# ---------------------------------------------------------------------------


def test_jar_already_in_db_false_when_empty(tmp_path):
    """Порожня БД → _jar_already_in_db повертає False."""
    from fundrec import ingest, store

    conn = store.connect(tmp_path / "test.sqlite")
    store.init_db(conn)
    assert ingest._jar_already_in_db(conn, "SOMEJAR") is False


def test_jar_already_in_db_true_after_insert(tmp_path):
    """Після збереження кампанії з jar provenance → _jar_already_in_db повертає True."""
    from fundrec import ingest, store

    components = _make_jar_ingest_components(
        posts=[_POST_WITH_JAR],
        jar_data=_JAR_DATA_JARTEST01,
    )
    ingest.run_ingest(
        "FPV", sources=["telegram"], max_items=5,
        db_path=tmp_path / "test.sqlite",
        out_path=tmp_path / "cases.json",
        raw_dir=tmp_path / "raw",
        _components=components,
    )

    conn = store.connect(tmp_path / "test.sqlite")
    assert ingest._jar_already_in_db(conn, "JARTEST01") is True
    assert ingest._jar_already_in_db(conn, "NONEXISTENT") is False
