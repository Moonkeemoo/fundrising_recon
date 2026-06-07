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

_JAR_ID = "RENDERTEST1"


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


def test_render_jar_cached_miss_then_hit(tmp_path):
    """Перший виклик: cache miss → _render викликається; другий: hit → _render НЕ викликається."""
    from fundrec.collect.jar_render import render_jar_cached

    call_count = {"n": 0}

    def counting_render(jar_id):
        call_count["n"] += 1
        return _FIXTURE_BODY

    cache_file = tmp_path / "jars_cache.json"

    # Miss
    result1 = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=counting_render)
    assert result1 is not None
    assert call_count["n"] == 1

    # Hit
    result2 = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=counting_render)
    assert result2 is not None
    assert call_count["n"] == 1  # НЕ збільшився


def test_render_jar_cached_persists_to_json(tmp_path):
    """Після cache miss результат зберігається у JSON-файлі."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: _FIXTURE_BODY)

    assert cache_file.exists()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert _JAR_ID in data
    assert data[_JAR_ID]["amount_uah"] == pytest.approx(2_000_837.29)


def test_render_jar_cached_none_not_stored(tmp_path):
    """Якщо render повертає None — нічого не зберігається у кеш."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    result = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: None)

    assert result is None
    # Файл або не існує, або не містить jar_id
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert _JAR_ID not in data


def test_render_jar_cached_returns_correct_amounts(tmp_path):
    """Кешована відповідь містить правильні суми."""
    from fundrec.collect.jar_render import render_jar_cached

    cache_file = tmp_path / "jars_cache.json"
    result = render_jar_cached(_JAR_ID, cache_path=cache_file, _render=lambda jar_id: _FIXTURE_BODY)

    assert result is not None
    assert result["amount_uah"] == pytest.approx(2_000_837.29)
    assert result["goal_amount"] == pytest.approx(10_000_000.0)
