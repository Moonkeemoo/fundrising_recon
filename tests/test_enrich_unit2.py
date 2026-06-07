"""Unit 2: jar_ids_from_raw — витяг jar-id з усіх полів raw-запису.

Сканує text, links, description у довільному raw dict.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Тести
# ---------------------------------------------------------------------------


def test_jar_ids_from_raw_jar_in_text():
    """jar_id у полі text → знаходиться."""
    from fundrec.jars import jar_ids_from_raw

    raw = {"text": "Банка: send.monobank.ua/jar/ABC123 — донатьте!"}
    result = jar_ids_from_raw(raw)
    assert result == ["ABC123"]


def test_jar_ids_from_raw_jar_in_links_only():
    """jar_id лише у полі links → знаходиться."""
    from fundrec.jars import jar_ids_from_raw

    raw = {
        "text": "Підтримайте збір, посилання нижче.",
        "links": ["https://send.monobank.ua/jar/XYZ789", "https://t.me/some"],
    }
    result = jar_ids_from_raw(raw)
    assert "XYZ789" in result


def test_jar_ids_from_raw_jar_in_description_only():
    """jar_id лише у полі description (YouTube) → знаходиться."""
    from fundrec.jars import jar_ids_from_raw

    raw = {
        "title": "Відео про збір",
        "description": "Банка: https://send.monobank.ua/jar/DESC99",
    }
    result = jar_ids_from_raw(raw)
    assert "DESC99" in result


def test_jar_ids_from_raw_no_jar():
    """Немає jar-id у жодному полі → []."""
    from fundrec.jars import jar_ids_from_raw

    raw = {
        "text": "Просто текст без посилань.",
        "links": ["https://t.me/channel"],
        "description": "Опис відео",
    }
    result = jar_ids_from_raw(raw)
    assert result == []


def test_jar_ids_from_raw_dedup_across_fields():
    """Той самий jar_id у text і links → повертається одним разом."""
    from fundrec.jars import jar_ids_from_raw

    raw = {
        "text": "https://send.monobank.ua/jar/DUP1 — банка",
        "links": ["https://send.monobank.ua/jar/DUP1"],
    }
    result = jar_ids_from_raw(raw)
    assert result.count("DUP1") == 1


def test_jar_ids_from_raw_order_text_first():
    """Порядок: спочатку з text, потім links, потім description."""
    from fundrec.jars import jar_ids_from_raw

    raw = {
        "text": "send.monobank.ua/jar/FIRST",
        "links": ["https://send.monobank.ua/jar/SECOND"],
        "description": "base.monobank.ua/jar/THIRD",
    }
    result = jar_ids_from_raw(raw)
    assert result == ["FIRST", "SECOND", "THIRD"]


def test_jar_ids_from_raw_missing_fields_ok():
    """Відсутні поля не спричиняють помилку."""
    from fundrec.jars import jar_ids_from_raw

    raw = {}
    assert jar_ids_from_raw(raw) == []


def test_jar_ids_from_raw_links_none_ok():
    """links=None (а не список) — не падає."""
    from fundrec.jars import jar_ids_from_raw

    raw = {"text": "send.monobank.ua/jar/OK1", "links": None}
    result = jar_ids_from_raw(raw)
    assert "OK1" in result


def test_jar_ids_from_raw_base_monobank_in_links():
    """base.monobank.ua/jar/<id> у links теж розпізнається."""
    from fundrec.jars import jar_ids_from_raw

    raw = {"links": ["https://base.monobank.ua/jar/BASE1"]}
    result = jar_ids_from_raw(raw)
    assert "BASE1" in result


def test_jar_ids_from_raw_multiple_unique_across_sources():
    """Кілька різних jar_id з різних полів повертаються всі."""
    from fundrec.jars import jar_ids_from_raw

    raw = {
        "text": "send.monobank.ua/jar/A1",
        "links": ["https://send.monobank.ua/jar/B2", "https://t.me/x"],
        "description": "https://send.monobank.ua/jar/C3",
    }
    result = jar_ids_from_raw(raw)
    assert set(result) == {"A1", "B2", "C3"}
    assert len(result) == 3
