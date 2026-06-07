"""Tests for fundrec.extract._json_from_text — pure JSON extraction from LLM text."""
from __future__ import annotations

import pytest

from fundrec.extract import _json_from_text


def test_raw_json_object():
    text = '{"title": "FPV", "amount_uah": 1000}'
    result = _json_from_text(text)
    assert result["title"] == "FPV"
    assert result["amount_uah"] == 1000


def test_json_in_fenced_code_block():
    text = '```json\n{"title": "Дрони", "goal": "military"}\n```'
    result = _json_from_text(text)
    assert result["title"] == "Дрони"


def test_json_in_plain_code_block():
    text = '```\n{"title": "Дрони"}\n```'
    result = _json_from_text(text)
    assert result["title"] == "Дрони"


def test_json_with_leading_prose():
    text = 'Ось результат:\n{"title": "Тест", "year": 2024}'
    result = _json_from_text(text)
    assert result["title"] == "Тест"
    assert result["year"] == 2024


def test_json_with_trailing_prose():
    text = '{"title": "Тест"}\nЦе все що я знайшов.'
    result = _json_from_text(text)
    assert result["title"] == "Тест"


def test_json_with_both_prose():
    text = 'Аналіз:\n```json\n{"amount_uah": 500000}\n```\nГотово.'
    result = _json_from_text(text)
    assert result["amount_uah"] == 500000


def test_no_json_raises_value_error():
    with pytest.raises((ValueError, Exception)):
        _json_from_text("Немає JSON тут взагалі.")


def test_empty_string_raises():
    with pytest.raises((ValueError, Exception)):
        _json_from_text("")
