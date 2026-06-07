"""Тести fundrec.collect.jar_render — render_jar, render_jar_cached."""

from __future__ import annotations

import json

import pytest


_FIXTURE_BODY = """\
Постійна банка для закупівлі FPV. Наша мета — купувати мінімум 300 дронів
2 000 837.29 ₴
10 000 000 ₴
Minimum amount: 10 ₴. Maximum amount: 29 999 ₴
"""

_FIXTURE_BODY_V2 = """\
Постійна банка для закупівлі FPV. Наша мета — купувати мінімум 300 дронів
2 100 000 ₴
10 000 000 ₴
Minimum amount: 10 ₴. Maximum amount: 29 999 ₴
"""

_JAR_ID = "RENDERTEST1"

_TS1 = "2024-01-01T10:00:00+00:00"
_TS2_SOON = "2024-01-01T11:00:00+00:00"   # 1 год після — не перевищує 6 год
_TS2_LATER = "2024-01-02T10:00:00+00:00"   # 24 год після — перевищує 6 год


# ---------------------------------------------------------------------------
# render_jar — з ін'єктованим _render
# ---------------------------------------------------------------------------


def test_render_jar_parses_fixture():
    """render_jar з ін'єктованим _render повертає dict із правильними сумами."""
    from fundrec.collect.jar_render import render_jar

    result = render_jar(_JAR_ID, _render=lambda jar_id: _FIXTURE_BODY)

    assert result is not None
    assert result["jar_id"] == _JAR_ID
    assert result["amount_uah"] == pytest.approx(2_000_837.29)
    assert result["goal_amount"] == pytest.approx(10_000_000.0)
    assert result["title"] is not None
    assert result["title"].startswith("Постійна банка")


def test_render_jar_returns_none_when_render_fails():
    """render_jar повертає None якщо _render повертає None."""
    from fundrec.collect.jar_render import render_jar

    result = render_jar(_JAR_ID, _render=lambda jar_id: None)
    assert result is None


def test_render_jar_returns_none_on_empty_body():
    """render_jar повертає None якщо _render повертає порожній рядок."""
    from fundrec.collect.jar_render import render_jar

    result = render_jar(_JAR_ID, _render=lambda jar_id: "")
    assert result is None


def test_render_jar_url_correct():
    """URL у результаті вказує на правильний jar."""
    from fundrec.collect.jar_render import render_jar

    result = render_jar(_JAR_ID, _render=lambda jar_id: _FIXTURE_BODY)
    assert result is not None
    assert result["url"] == f"https://send.monobank.ua/jar/{_JAR_ID}"


# ---------------------------------------------------------------------------
# render_jar_cached — cache hit / miss
# ---------------------------------------------------------------------------


def test_render_jar_cached_always_renders(tmp_path):
    """render_jar_cached завжди викликає _render (щоб записувати свіжі snapshot-и)."""
    from fundrec.collect.jar_render import render_jar_cached

    call_count = {"n": 0}

    def counting_render(jar_id):
        call_count["n"] += 1
        return _FIXTURE_BODY

    cache_file = tmp_path / "jars_cache.json"

    result1 = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=counting_render, now=_TS1)
    assert result1 is not None
    assert call_count["n"] == 1

    # Другий виклик також рендерить
    result2 = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=counting_render, now=_TS2_LATER)
    assert result2 is not None
    assert call_count["n"] == 2


def test_render_jar_cached_persists_to_json(tmp_path):
    """Після рендеру результат зберігається у JSON-файлі."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: _FIXTURE_BODY, now=_TS1)

    assert cache_file.exists()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert _JAR_ID in data
    assert data[_JAR_ID]["amount_uah"] == pytest.approx(2_000_837.29)


def test_render_jar_cached_none_not_stored(tmp_path):
    """Якщо render повертає None — нічого не зберігається у кеш."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    result = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: None, now=_TS1)

    assert result is None
    # Файл або не існує, або не містить jar_id
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert _JAR_ID not in data


def test_render_jar_cached_returns_correct_amounts(tmp_path):
    """Кешована відповідь містить правильні суми."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    result = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: _FIXTURE_BODY, now=_TS1)

    assert result is not None
    assert result["amount_uah"] == pytest.approx(2_000_837.29)
    assert result["goal_amount"] == pytest.approx(10_000_000.0)


# ---------------------------------------------------------------------------
# Unit 1: timestamped snapshot history
# ---------------------------------------------------------------------------


def test_first_render_creates_history_len_1(tmp_path):
    """Перший рендер → history містить рівно 1 snapshot."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    result = render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS1
    )

    assert result is not None
    assert "history" in result
    assert len(result["history"]) == 1
    assert result["history"][0]["ts"] == _TS1
    assert result["history"][0]["amount_uah"] == pytest.approx(2_000_837.29)


def test_second_render_same_amount_soon_no_new_snapshot(tmp_path):
    """Другий рендер з тією самою сумою менш ніж через 6 годин → history залишається len 1."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS1
    )
    result2 = render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS2_SOON
    )

    assert result2 is not None
    assert len(result2["history"]) == 1  # не додається — сума та сама, проміжок < 6 год


def test_second_render_changed_amount_adds_snapshot(tmp_path):
    """Другий рендер із зміненою сумою → history len 2 з правильними значеннями."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS1
    )
    result2 = render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY_V2, now=_TS2_SOON, force=True
    )

    assert result2 is not None
    assert len(result2["history"]) == 2
    assert result2["history"][0]["ts"] == _TS1
    assert result2["history"][1]["ts"] == _TS2_SOON
    assert result2["history"][1]["amount_uah"] == pytest.approx(2_100_000.0)


def test_second_render_same_amount_later_adds_snapshot(tmp_path):
    """Другий рендер з тією самою сумою але через 24 год → history len 2."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS1
    )
    result2 = render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS2_LATER
    )

    assert result2 is not None
    assert len(result2["history"]) == 2


def test_history_persisted_in_cache_file(tmp_path):
    """history зберігається у JSON-файлі кешу."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS1)
    render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY_V2, now=_TS2_SOON, force=True)

    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "history" in data[_JAR_ID]
    assert len(data[_JAR_ID]["history"]) == 2


def test_old_format_cache_migrates_gracefully(tmp_path):
    """Стара запис кешу без 'history' → не падає, починає history заново."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    # Записуємо старий формат (без history)
    old_entry = {
        "jar_id": _JAR_ID,
        "url": f"https://send.monobank.ua/jar/{_JAR_ID}",
        "title": "Стара банка",
        "amount_uah": 500_000.0,
        "goal_amount": 1_000_000.0,
    }
    cache_file.write_text(json.dumps({_JAR_ID: old_entry}), encoding="utf-8")

    result = render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS1
    )

    assert result is not None
    # Не падає, history починається з поточного рендеру
    assert "history" in result
    assert len(result["history"]) >= 1


def test_render_none_returns_cached_latest(tmp_path):
    """Якщо render повертає None після попереднього запису — повертає кешовані дані."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda j: _FIXTURE_BODY, now=_TS1)

    # Тепер render повертає None (наприклад, мережева помилка)
    result = render_jar_cached(
        _JAR_ID, cache_path=cache_file, _render=lambda j: None, now=_TS2_LATER
    )

    assert result is not None
    assert result["amount_uah"] == pytest.approx(2_000_837.29)
    # history НЕ включається у fallback-результат
    assert "history" not in result
