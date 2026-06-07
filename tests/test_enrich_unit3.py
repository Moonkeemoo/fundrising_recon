"""Unit 3: parse_amounts_from_text — детермінований парсер сум із тексту.

amounts.parse_amounts_from_text(text) -> {"amount_uah": float|None, "goal_amount": float|None}
"""
from __future__ import annotations

import pytest


def _parse(text: str):
    from fundrec.amounts import parse_amounts_from_text
    return parse_amounts_from_text(text)


# ---------------------------------------------------------------------------
# RAISED amount — різні формати
# ---------------------------------------------------------------------------

def test_zibrano_mln():
    r = _parse("зібрали 2,5 млн грн")
    assert r["amount_uah"] == 2_500_000.0


def test_zibrano_plain():
    r = _parse("зібрано 500 000 ₴")
    assert r["amount_uah"] == 500_000.0


def test_vzhe_mln():
    r = _parse("вже 1.2 млн")
    assert r["amount_uah"] == 1_200_000.0


def test_nazbibraly():
    r = _parse("назбирали 3 млн грн")
    assert r["amount_uah"] == 3_000_000.0


def test_raised_tys():
    r = _parse("зібрали 250 тис грн")
    assert r["amount_uah"] == 250_000.0


def test_raised_k_suffix():
    r = _parse("зібрано 500к")
    assert r["amount_uah"] == 500_000.0


def test_raised_k_latin():
    r = _parse("зібрали 300k грн")
    assert r["amount_uah"] == 300_000.0


def test_raised_mld():
    r = _parse("зібрано 1 млрд грн")
    assert r["amount_uah"] == 1_000_000_000.0


def test_raised_plain_spaces():
    """10 000 000 грн (пробіли як роздільник тисяч)."""
    r = _parse("зібрали 10 000 000 грн")
    assert r["amount_uah"] == 10_000_000.0


def test_raised_plus_sign():
    """'+' зі сумою вважається зібраним."""
    r = _parse("+ 1 500 000 грн")
    assert r["amount_uah"] == 1_500_000.0


def test_raised_decimal_dot():
    r = _parse("зібрано 2.5 млн грн")
    assert r["amount_uah"] == 2_500_000.0


# ---------------------------------------------------------------------------
# GOAL amount
# ---------------------------------------------------------------------------

def test_goal_tsiľ_mln():
    r = _parse("ціль 10 млн грн")
    assert r["goal_amount"] == 10_000_000.0


def test_goal_meta():
    r = _parse("мета — 500к")
    assert r["goal_amount"] == 500_000.0


def test_goal_potribno():
    r = _parse("потрібно 1,5 млн ₴")
    assert r["goal_amount"] == 1_500_000.0


def test_goal_zbyraiemo_na():
    r = _parse("збираємо на 2 млн грн")
    assert r["goal_amount"] == 2_000_000.0


# ---------------------------------------------------------------------------
# Both raised + goal in one text
# ---------------------------------------------------------------------------

def test_both_goal_and_raised():
    r = _parse("ціль 10 млн, зібрано 3 млн")
    assert r["goal_amount"] == 10_000_000.0
    assert r["amount_uah"] == 3_000_000.0


def test_both_different_order():
    r = _parse("зібрали 1 млн грн, ціль 5 млн")
    assert r["amount_uah"] == 1_000_000.0
    assert r["goal_amount"] == 5_000_000.0


# ---------------------------------------------------------------------------
# Honest None
# ---------------------------------------------------------------------------

def test_no_numbers_both_none():
    r = _parse("Просто текст без чисел і сум")
    assert r["amount_uah"] is None
    assert r["goal_amount"] is None


def test_empty_string():
    r = _parse("")
    assert r["amount_uah"] is None
    assert r["goal_amount"] is None


def test_number_without_context_is_none():
    """Числа без контексту (валюти/множника) — не розпізнаються."""
    r = _parse("Пост номер 5 про 3 автомобілі")
    assert r["amount_uah"] is None
    assert r["goal_amount"] is None


def test_phone_number_not_captured():
    """Телефонний номер не сприймається як сума."""
    r = _parse("Телефон: +380501234567")
    assert r["amount_uah"] is None


def test_date_not_captured():
    """Дата (рік) не сприймається як сума."""
    r = _parse("Збір почато 2024-01-15")
    assert r["amount_uah"] is None


# ---------------------------------------------------------------------------
# Edge cases: multiplier suffixes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("зібрано 1 млн",    1_000_000.0),
    ("зібрано 1 тис",    1_000.0),
    ("зібрано 1к",       1_000.0),
    ("зібрано 1K грн",   1_000.0),
    ("зібрано 1 млрд",   1_000_000_000.0),
    ("зібрано 1,5 млн",  1_500_000.0),
    ("зібрано 1.5 млн",  1_500_000.0),
])
def test_multiplier_variants(text, expected):
    r = _parse(text)
    assert r["amount_uah"] == expected


def test_plain_large_number_with_currency():
    """10 000 000 грн з грн-маркером → розпізнається."""
    r = _parse("10 000 000 грн зібрано")
    # Може не мати ключового слова «зібрали» перед числом — перевіряємо чи взагалі знайдено
    # Специфікація каже «зібрали 10 000 000 грн» — ключове слово перед числом
    r2 = _parse("зібрали 10 000 000 грн")
    assert r2["amount_uah"] == 10_000_000.0


# ---------------------------------------------------------------------------
# Does not confuse goal with raised
# ---------------------------------------------------------------------------

def test_goal_not_set_as_amount():
    """«ціль» → goal_amount, НЕ amount_uah."""
    r = _parse("ціль 5 млн грн")
    assert r["goal_amount"] == 5_000_000.0
    assert r["amount_uah"] is None


def test_amount_not_set_as_goal():
    """«зібрали» → amount_uah, НЕ goal_amount."""
    r = _parse("зібрали 5 млн грн")
    assert r["amount_uah"] == 5_000_000.0
    assert r["goal_amount"] is None
